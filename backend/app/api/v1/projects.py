from __future__ import annotations

import asyncio
from datetime import datetime, timezone
import io
import json
from typing import Any, AsyncIterator, Dict, List, Optional
from docx import Document
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse, Response, StreamingResponse
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core import (
    accept_map_extract_proposal,
    apply_agent_actions,
    build_branch_tree,
    build_map_extract_proposal,
    extract_map_from_script,
    extract_map_smart,
    export_to_renpy,
    lint_narrative_draft,
    normalize_project,
    project_from_plain_text,
    run_agent,
    run_ai,
    run_voice_check,
    touch_project,
    uid,
)
from app.core.ai import DeepSeekConfig
from app.core.snapshots import decode_snapshot_payload
from app.core.voice_reports import persist_voice_report
from app.db import get_db
from app.domain.types import AgentRequest, AiRequest, VnProject
from app.models import AgentSession, Project, Share, User
from app.schemas import (
    AgentConversationCreateIn,
    AgentConversationOut,
    AgentConversationPutIn,
    AgentConversationRenameIn,
    AgentConversationSummary,
    AgentRunIn,
    AgentRunOut,
    AgentSessionOut,
    AgentSessionPutIn,
    AiRunIn,
    LintIn,
    FactsAcceptIn,
    FactsAckStaleIn,
    FactsRejectIn,
    FactsScanIn,
    AgentIngestSettingsIn,
    ChapterReviseIn,
    ChapterReviseApplyIn,
    MapExtractAcceptIn,
    MapExtractIn,
    ProjectCreateIn,
    ProjectPatchIn,
    ProjectPutIn,
    ProjectSummary,
    ShareCreateOut,
    SnapshotCreateIn,
    VoiceCheckIn,
)
from app.security import get_current_user
from app.services.novel_memory import get_latest_continuity
from app.services.projects import (
    create_project_row,
    get_owned_project,
    get_project_readable,
    merge_project_changes,
    project_to_dict,
    resolve_llm_credentials,
    row_to_vn,
    sync_row_from_vn,
)
from app.services.snapshots import (
    create_snapshot as create_snapshot_row,
    delete_snapshot as delete_snapshot_row,
    get_snapshot_payload,
    list_snapshots as list_snapshot_rows,
)

router = APIRouter(prefix="/projects", tags=["projects"])


@router.get("", response_model=List[ProjectSummary])
async def list_projects(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    result = await db.execute(
        select(Project)
        .where(Project.owner_id == user.id)
        .order_by(Project.updated_at.desc())
    )
    rows = result.scalars().all()
    return [
        ProjectSummary(
            id=r.id,
            title=r.title,
            logline=r.logline,
            genre=r.genre,
            updated_at=r.updated_at,
            created_at=r.created_at,
        )
        for r in rows
    ]


@router.post("", response_model=dict)
async def create_project(
    body: ProjectCreateIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await create_project_row(
        db, user, title=body.title, from_demo=body.from_demo
    )
    return project_to_dict(row_to_vn(row))


@router.post("/import", response_model=dict)
async def import_project(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    file: Optional[UploadFile] = File(None),
    text: Optional[str] = Form(None),
    title: Optional[str] = Form(None),
    json_body: Optional[str] = Form(None),
):
    vn: Optional[VnProject] = None
    if json_body:
        try:
            raw = json.loads(json_body)
        except json.JSONDecodeError as exc:
            raise HTTPException(status_code=400, detail="无效 JSON") from exc
        vn = normalize_project(raw)
        vn = normalize_project({**project_to_dict(vn), "id": uid("proj")})
    elif file is not None:
        content = await file.read()
        name = (file.filename or "").lower()
        if name.endswith(".json") or name.endswith(".vnss-share.json"):
            raw = json.loads(content.decode("utf-8"))
            if isinstance(raw, dict) and "project" in raw:
                raw = raw["project"]
            vn = normalize_project(raw)
            vn = normalize_project({**project_to_dict(vn), "id": uid("proj")})
        elif name.endswith(".docx"):
            doc = Document(io.BytesIO(content))
            plain = "\n".join(p.text for p in doc.paragraphs)
            vn = project_from_plain_text(title or name.rsplit(".", 1)[0], plain)
        else:
            plain = content.decode("utf-8", errors="replace")
            vn = project_from_plain_text(
                title or (name.rsplit(".", 1)[0] if name else "导入剧本"),
                plain,
            )
    elif text:
        vn = project_from_plain_text(title or "导入剧本", text)
    else:
        raise HTTPException(status_code=400, detail="请提供文件或文本")

    if title:
        vn.title = title
    row = await create_project_row(db, user, vn=vn)
    return project_to_dict(row_to_vn(row))


@router.get("/{project_id}", response_model=dict)
async def get_project(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await get_project_readable(db, user, project_id)
    return project_to_dict(row_to_vn(row))


@router.put("/{project_id}", response_model=dict)
async def put_project(
    project_id: str,
    body: ProjectPutIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await get_owned_project(db, user, project_id)

    chapter_ids = body.chapter_ids or []
    sections = body.sections or []

    if chapter_ids or sections:
        # Collaboration stage B: chapter-scoped save.
        # Only the declared chapters / sections are merged; everything else keeps
        # the server version so concurrent edits to other chapters survive.
        if not body.force and chapter_ids:
            from app.services import collab

            await collab.assert_chapters_unlocked(db, project_id, chapter_ids, user.id)
        server_vn = row_to_vn(row)
        client_vn = normalize_project(dict(body.data))
        merged = merge_project_changes(server_vn, client_vn, chapter_ids, sections)
        sync_row_from_vn(row, merged)
        await db.commit()
        await db.refresh(row)
        return project_to_dict(row_to_vn(row))

    if body.updated_at and not body.force:
        client_ts = body.updated_at.replace("Z", "+00:00")
        try:
            client_dt = datetime.fromisoformat(client_ts)
            if client_dt.tzinfo is None:
                client_dt = client_dt.replace(tzinfo=timezone.utc)
            server_dt = row.updated_at
            if server_dt.tzinfo is None:
                server_dt = server_dt.replace(tzinfo=timezone.utc)
            if abs((server_dt - client_dt).total_seconds()) > 0.5 and server_dt > client_dt:
                raise HTTPException(
                    status_code=409,
                    detail={
                        "code": "project_conflict",
                        "message": "项目已在别处更新。可保留本地稿覆盖，或改用服务器版本。",
                        "serverUpdatedAt": server_dt.isoformat(),
                        "clientUpdatedAt": client_dt.isoformat(),
                    },
                )
        except ValueError:
            pass

    data = dict(body.data)
    data["id"] = project_id
    vn = normalize_project(data)
    sync_row_from_vn(row, vn)
    await db.commit()
    await db.refresh(row)
    return project_to_dict(row_to_vn(row))


@router.patch("/{project_id}", response_model=dict)
async def patch_project(
    project_id: str,
    body: ProjectPatchIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await get_owned_project(db, user, project_id)
    vn = row_to_vn(row)
    if body.title is not None:
        vn.title = body.title
    if body.logline is not None:
        vn.logline = body.logline
    if body.genre is not None:
        vn.genre = body.genre
    sync_row_from_vn(row, vn)
    await db.commit()
    await db.refresh(row)
    return project_to_dict(row_to_vn(row))


@router.delete("/{project_id}")
async def delete_project(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await get_owned_project(db, user, project_id)
    # cascade-ish cleanup
    sess = await db.execute(
        select(AgentSession).where(AgentSession.project_id == project_id)
    )
    for s in sess.scalars().all():
        await db.delete(s)
    shares = await db.execute(select(Share).where(Share.project_id == project_id))
    for s in shares.scalars().all():
        await db.delete(s)
    await db.delete(row)
    await db.commit()
    return {"ok": True}


@router.post("/{project_id}/duplicate", response_model=dict)
async def duplicate_project(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await get_owned_project(db, user, project_id)
    vn = row_to_vn(row)
    data = project_to_dict(vn)
    data["id"] = uid("proj")
    data["title"] = f"{vn.title}（副本）"
    data.pop("shareId", None)
    new_row = await create_project_row(db, user, vn=normalize_project(data))
    return project_to_dict(row_to_vn(new_row))


@router.get("/{project_id}/export/rpy")
async def export_rpy(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await get_project_readable(db, user, project_id)
    text = export_to_renpy(row_to_vn(row))
    return PlainTextResponse(text, media_type="text/plain; charset=utf-8")


@router.get("/{project_id}/export/bundle")
async def export_bundle(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Download a full Ren'Py project skeleton (script/options/gui/README) as zip."""
    import io as _io
    import zipfile

    from app.core.renpy import export_project_bundle

    row = await get_project_readable(db, user, project_id)
    vn = row_to_vn(row)
    files = export_project_bundle(vn)
    buf = _io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, content in files.items():
            zf.writestr(name, content)
    buf.seek(0)
    safe = re.sub(r"[^\w\u4e00-\u9fff]+", "_", vn.title or "vn")[:40] or "vn"
    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={
            "Content-Disposition": f'attachment; filename="{safe}-renpy.zip"'
        },
    )


@router.get("/{project_id}/export/json")
async def export_json(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await get_project_readable(db, user, project_id)
    payload = json.dumps(project_to_dict(row_to_vn(row)), ensure_ascii=False, indent=2)
    return Response(
        content=payload,
        media_type="application/json; charset=utf-8",
        headers={
            "Content-Disposition": f'attachment; filename="{row.id}.json"'
        },
    )


@router.post("/{project_id}/map/extract", response_model=dict)
async def map_extract(
    project_id: str,
    body: MapExtractIn = MapExtractIn(),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Dry-run map extract — returns a reviewable proposal, does not write.

    - mode=rules: scene bg tags only (fast, offline)
    - mode=smart (default): scene + lexicon + DeepSeek over dialogue/bible
    """
    row = await get_owned_project(db, user, project_id)
    vn = row_to_vn(row)
    mode = body.mode or "smart"

    if mode == "rules":
        result = extract_map_from_script(vn)
        result = {
            **result,
            "mode": "rules",
            "llmUsed": False,
            "llmAddedCount": 0,
            "llmLinkCount": 0,
            "warnings": [],
        }
    else:
        creds = await resolve_llm_credentials(db, user.id, settings)
        cfg = DeepSeekConfig(
            apiKey=creds["api_key"],
            baseUrl=creds["base_url"],
            model=creds["model"],
        )
        result = await extract_map_smart(vn, cfg, use_llm=True)

    proposal = build_map_extract_proposal(vn, result)
    return {
        "project": project_to_dict(vn),
        "proposal": proposal,
        "addedCount": len(proposal["newPlaceIds"]),
        "linkCount": len(proposal["newLinkIds"]),
        "llmAddedCount": result.get("llmAddedCount", 0),
        "llmLinkCount": result.get("llmLinkCount", 0),
        "mode": result.get("mode", mode),
        "llmUsed": bool(result.get("llmUsed")),
        "warnings": result.get("warnings") or [],
    }


@router.post("/{project_id}/map/extract/accept", response_model=dict)
async def map_extract_accept(
    project_id: str,
    body: MapExtractAcceptIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Apply checked new places/links from a prior dry-run proposal."""
    row = await get_owned_project(db, user, project_id)
    vn = row_to_vn(row)
    try:
        merged = accept_map_extract_proposal(
            vn,
            proposal_locations=body.proposal.locations,
            proposal_links=body.proposal.locationLinks,
            place_ids=body.placeIds,
            link_ids=body.linkIds,
            new_place_ids=body.proposal.newPlaceIds,
            new_link_ids=body.proposal.newLinkIds,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    vn.locations = merged["locations"]
    vn.locationLinks = merged["locationLinks"]
    sync_row_from_vn(row, vn)
    await db.commit()
    await db.refresh(row)
    return {
        "project": project_to_dict(row_to_vn(row)),
        "addedCount": merged.get("addedCount", 0),
        "linkCount": merged.get("linkCount", 0),
    }


def _branch_node_to_dict(node: Any) -> dict:
    return {
        "id": node.id,
        "kind": node.kind,
        "title": node.title,
        "children": [_branch_node_to_dict(c) for c in (node.children or [])],
    }


@router.post("/{project_id}/analysis/branch-tree")
async def analysis_branch_tree(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await get_owned_project(db, user, project_id)
    tree = build_branch_tree(row_to_vn(row))
    return {"nodes": [_branch_node_to_dict(n) for n in tree]}


@router.post("/{project_id}/analysis/facts/reconcile")
async def analysis_facts_reconcile(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.core.fact_extract import compute_fingerprints, diff_fingerprints, reconcile_stale

    row = await get_owned_project(db, user, project_id)
    vn = row_to_vn(row)
    delta = diff_fingerprints(vn, vn.analysisMeta)
    new_vn = reconcile_stale(vn)
    stale_links = sum(1 for l in (new_vn.characterLinks or []) if l.stale)
    stale_tl = sum(1 for t in (new_vn.timeline or []) if t.stale)

    def _sig(p: VnProject) -> str:
        links = [
            (l.id, bool(l.stale), l.staleReason or "")
            for l in (p.characterLinks or [])
        ]
        events = [
            (t.id, bool(t.stale), t.staleReason or "")
            for t in (p.timeline or [])
        ]
        return str((links, events))

    wrote = False
    if _sig(vn) != _sig(new_vn):
        sync_row_from_vn(row, new_vn)
        await db.commit()
        await db.refresh(row)
        wrote = True
        out = row_to_vn(row)
    else:
        # No fact drift — avoid bumping updated_at (prevents client autosave 409)
        out = vn

    return {
        "project": project_to_dict(out),
        "changed": {
            "chapters": delta.changed_chapter_ids,
            "bible": delta.bible_changed,
            "characters": delta.changed_character_ids,
            "isFirstScan": delta.is_first_scan,
        },
        "staleCount": stale_links + stale_tl,
        "fingerprints": compute_fingerprints(out).model_dump(mode="json"),
        "wrote": wrote,
    }


@router.post("/{project_id}/analysis/facts/scan")
async def analysis_facts_scan(
    project_id: str,
    body: FactsScanIn = FactsScanIn(),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    from app.core.fact_extract import build_scan_candidates, filter_new_candidates
    from app.services import analysis_inbox as inbox_svc

    row = await get_owned_project(db, user, project_id)
    vn = row_to_vn(row)
    force = [body.chapter_id] if body.chapter_id else None
    if body.persist_paste and body.paste_text:
        await inbox_svc.insert_source_snippet(db, project_id, body.paste_text, source="paste")
    cands, delta, fresh_meta = build_scan_candidates(
        vn,
        force_chapter_ids=force,
        paste_text=body.paste_text,
        full=body.full,
    )
    pending_keys = await inbox_svc.blocked_dedupe_keys(db, project_id)
    fresh = filter_new_candidates(vn, cands, pending_keys)
    llm_info: Optional[Dict[str, Any]] = None
    if body.llm and fresh:
        from app.core.fact_llm import enrich_fact_candidates

        creds = await resolve_llm_credentials(db, user.id, settings)
        cfg = DeepSeekConfig(
            apiKey=creds["api_key"],
            baseUrl=creds["base_url"],
            model=creds["model"],
        )
        enriched = await enrich_fact_candidates(cfg, vn, fresh)
        # Refined labels may collide with accepted/pending keys → re-filter.
        fresh = filter_new_candidates(vn, enriched.candidates, pending_keys)
        s = enriched.stats
        llm_info = {
            "used": s.llm_used,
            "sent": s.sent,
            "kept": s.kept,
            "dropped": s.dropped,
            "refined": s.refined,
            "model": s.model or None,
            "error": s.error,
        }
    created = await inbox_svc.insert_candidates(db, project_id, fresh)
    vn = vn.model_copy(update={"analysisMeta": fresh_meta})
    sync_row_from_vn(row, vn)
    await db.commit()
    await db.refresh(row)
    return {
        "project": project_to_dict(row_to_vn(row)),
        "changed": {
            "chapters": delta.changed_chapter_ids,
            "bible": delta.bible_changed,
            "characters": delta.changed_character_ids,
            "isFirstScan": delta.is_first_scan,
        },
        "summary": {
            "added": len(created),
            "characterLinks": sum(1 for c in created if c.kind == "character_link"),
            "timelineEvents": sum(1 for c in created if c.kind == "timeline_event"),
        },
        "llm": llm_info,
        "inbox": [inbox_svc.inbox_row_to_dict(r) for r in created],
    }


@router.get("/{project_id}/analysis/facts/inbox")
async def analysis_facts_inbox(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services import analysis_inbox as inbox_svc

    await get_project_readable(db, user, project_id)
    rows = await inbox_svc.list_inbox(
        db,
        project_id,
        status="pending",
        kinds=["character_link", "timeline_event"],
    )
    return {"items": [inbox_svc.inbox_row_to_dict(r) for r in rows]}


@router.post("/{project_id}/analysis/facts/accept")
async def analysis_facts_accept(
    project_id: str,
    body: FactsAcceptIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.core.fact_extract import (
        accept_character_link,
        accept_timeline_event,
        existing_dedupe_keys,
        link_dedupe_key,
        timeline_dedupe_key,
    )
    from app.services import analysis_inbox as inbox_svc

    row = await get_owned_project(db, user, project_id)
    vn = row_to_vn(row)
    items = await inbox_svc.get_inbox_items(db, project_id, body.ids)
    accepted_ids: list[str] = []
    skipped_ids: list[str] = []
    for item in items:
        if item.status != "pending":
            continue
        payload = item.payload or {}
        evidence = item.evidence or []
        before_keys = existing_dedupe_keys(vn)
        if item.kind == "character_link":
            from_id = str(payload.get("fromId") or "")
            to_id = str(payload.get("toId") or "")
            label = str(payload.get("label") or "关系")
            key = link_dedupe_key(from_id, to_id, label)
            vn = accept_character_link(
                vn,
                from_id=from_id,
                to_id=to_id,
                label=label,
                evidence=evidence,
                sync_cards=True,
            )
            if key in before_keys:
                skipped_ids.append(item.id)
            else:
                accepted_ids.append(item.id)
        elif item.kind == "timeline_event":
            title = str(payload.get("title") or "节点")
            chapter_ref = payload.get("chapterRef")
            key = timeline_dedupe_key(title, chapter_ref)
            vn = accept_timeline_event(
                vn,
                title=title,
                when=payload.get("when"),
                summary=payload.get("summary"),
                chapter_ref=chapter_ref,
                order=payload.get("order"),
                evidence=evidence,
            )
            if key in before_keys:
                skipped_ids.append(item.id)
            else:
                accepted_ids.append(item.id)
        else:
            skipped_ids.append(item.id)
    # Close pending either way (accepted or already-present duplicate)
    await inbox_svc.set_status(
        db,
        [i for i in items if i.id in accepted_ids or i.id in skipped_ids],
        "accepted",
    )
    sync_row_from_vn(row, touch_project(vn))
    await db.commit()
    await db.refresh(row)
    return {
        "acceptedIds": accepted_ids,
        "skippedIds": skipped_ids,
        "project": project_to_dict(row_to_vn(row)),
    }


@router.post("/{project_id}/analysis/facts/reject")
async def analysis_facts_reject(
    project_id: str,
    body: FactsRejectIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.services import analysis_inbox as inbox_svc

    await get_owned_project(db, user, project_id)
    items = await inbox_svc.get_inbox_items(db, project_id, body.ids)
    await inbox_svc.set_status(db, items, "rejected")
    await db.commit()
    return {"rejectedIds": [i.id for i in items]}


@router.post("/{project_id}/analysis/facts/ack-stale")
async def analysis_facts_ack_stale(
    project_id: str,
    body: FactsAckStaleIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    from app.core.fact_extract import clear_stale_flags

    row = await get_owned_project(db, user, project_id)
    vn = clear_stale_flags(
        row_to_vn(row),
        link_ids=body.linkIds,
        timeline_ids=body.timelineIds,
        all_stale=body.all,
    )
    sync_row_from_vn(row, touch_project(vn))
    await db.commit()
    await db.refresh(row)
    return {"project": project_to_dict(row_to_vn(row))}


@router.post("/{project_id}/analysis/lint")
async def analysis_lint(
    project_id: str,
    body: LintIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_owned_project(db, user, project_id)
    issues = lint_narrative_draft(body.draft)
    out = []
    for i in issues:
        if isinstance(i, dict):
            out.append(i)
        elif hasattr(i, "__dataclass_fields__"):
            out.append({k: getattr(i, k) for k in i.__dataclass_fields__})
        else:
            out.append(getattr(i, "__dict__", {"raw": str(i)}))
    return {"issues": out}


@router.get("/{project_id}/snapshots")
async def list_snapshots(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_project_readable(db, user, project_id)
    return await list_snapshot_rows(db, project_id)


@router.post("/{project_id}/snapshots")
async def create_snapshot(
    project_id: str,
    body: SnapshotCreateIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await get_owned_project(db, user, project_id)
    vn = row_to_vn(row)
    out = await create_snapshot_row(db, project_id, vn, label=body.label)
    await db.commit()
    return out


@router.post("/{project_id}/snapshots/{snap_id}/restore", response_model=dict)
async def restore_snapshot(
    project_id: str,
    snap_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await get_owned_project(db, user, project_id)
    payload = await get_snapshot_payload(db, project_id, snap_id)
    if payload is None:
        raise HTTPException(status_code=404, detail="快照不存在")
    try:
        decoded = decode_snapshot_payload(payload)
    except (TypeError, json.JSONDecodeError) as exc:
        raise HTTPException(status_code=400, detail=f"快照损坏：{exc}") from exc
    restored = normalize_project(decoded)
    restored.id = project_id
    sync_row_from_vn(row, restored)
    await db.commit()
    await db.refresh(row)
    return project_to_dict(row_to_vn(row))


@router.delete("/{project_id}/snapshots/{snap_id}")
async def delete_snapshot(
    project_id: str,
    snap_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_owned_project(db, user, project_id)
    ok = await delete_snapshot_row(db, project_id, snap_id)
    if not ok:
        raise HTTPException(status_code=404, detail="快照不存在")
    await db.commit()
    return {"ok": True}


def _conversation_out(sess: AgentSession) -> AgentConversationOut:
    return AgentConversationOut(
        id=sess.id,
        title=sess.title or "新对话",
        messages=list(sess.messages or []),
        chat_memory=sess.chat_memory or "",
        undo_stack=list(sess.undo_stack or []),
        created_at=sess.created_at,
        updated_at=sess.updated_at,
    )


def _title_from_messages(messages: list[Any] | None, fallback: str = "新对话") -> str:
    if not messages:
        return fallback
    for m in messages:
        if not isinstance(m, dict):
            continue
        if m.get("role") != "user":
            continue
        content = str(m.get("content") or "").strip().replace("\n", " ")
        if not content:
            continue
        return content[:40] + ("…" if len(content) > 40 else "")
    return fallback


async def _list_sessions(db: AsyncSession, project_id: str) -> list[AgentSession]:
    result = await db.execute(
        select(AgentSession)
        .where(AgentSession.project_id == project_id)
        .order_by(AgentSession.updated_at.desc())
    )
    return list(result.scalars().all())


async def _get_session(
    db: AsyncSession, project_id: str, conversation_id: str
) -> AgentSession:
    result = await db.execute(
        select(AgentSession).where(
            AgentSession.id == conversation_id,
            AgentSession.project_id == project_id,
        )
    )
    sess = result.scalar_one_or_none()
    if sess is None:
        raise HTTPException(status_code=404, detail="对话不存在")
    return sess


async def _create_session(
    db: AsyncSession, project_id: str, title: Optional[str] = None
) -> AgentSession:
    cleaned = (title or "新对话").strip() or "新对话"
    if len(cleaned) > 255:
        cleaned = cleaned[:255]
    sess = AgentSession(
        project_id=project_id,
        title=cleaned,
        messages=[],
        chat_memory="",
        undo_stack=[],
    )
    db.add(sess)
    await db.commit()
    await db.refresh(sess)
    return sess


async def _get_or_create_latest_session(
    db: AsyncSession, project_id: str
) -> AgentSession:
    rows = await _list_sessions(db, project_id)
    if rows:
        return rows[0]
    return await _create_session(db, project_id)


@router.get(
    "/{project_id}/agent/conversations",
    response_model=List[AgentConversationSummary],
)
async def list_agent_conversations(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_project_readable(db, user, project_id)
    rows = await _list_sessions(db, project_id)
    return [
        AgentConversationSummary(
            id=s.id,
            title=s.title or "新对话",
            message_count=len(s.messages or []),
            created_at=s.created_at,
            updated_at=s.updated_at,
        )
        for s in rows
    ]


@router.post(
    "/{project_id}/agent/conversations",
    response_model=AgentConversationOut,
)
async def create_agent_conversation(
    project_id: str,
    body: AgentConversationCreateIn = AgentConversationCreateIn(),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_owned_project(db, user, project_id)
    sess = await _create_session(db, project_id, body.title)
    return _conversation_out(sess)


@router.get(
    "/{project_id}/agent/conversations/{conversation_id}",
    response_model=AgentConversationOut,
)
async def get_agent_conversation(
    project_id: str,
    conversation_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_project_readable(db, user, project_id)
    sess = await _get_session(db, project_id, conversation_id)
    return _conversation_out(sess)


@router.put(
    "/{project_id}/agent/conversations/{conversation_id}",
    response_model=AgentConversationOut,
)
async def put_agent_conversation(
    project_id: str,
    conversation_id: str,
    body: AgentConversationPutIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_owned_project(db, user, project_id)
    sess = await _get_session(db, project_id, conversation_id)
    if body.title is not None:
        sess.title = body.title.strip() or sess.title or "新对话"
    if body.messages is not None:
        sess.messages = body.messages
        if (not sess.title or sess.title == "新对话") and body.messages:
            sess.title = _title_from_messages(body.messages)
    if body.chat_memory is not None:
        sess.chat_memory = body.chat_memory
    if body.undo_stack is not None:
        sess.undo_stack = body.undo_stack
    sess.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(sess)
    return _conversation_out(sess)


@router.patch(
    "/{project_id}/agent/conversations/{conversation_id}",
    response_model=AgentConversationOut,
)
async def rename_agent_conversation(
    project_id: str,
    conversation_id: str,
    body: AgentConversationRenameIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Rename a conversation (title only)."""
    await get_owned_project(db, user, project_id)
    sess = await _get_session(db, project_id, conversation_id)
    title = (body.title or "").strip()
    if not title:
        raise HTTPException(status_code=400, detail="对话名称不能为空")
    if len(title) > 255:
        title = title[:255]
    sess.title = title
    sess.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(sess)
    return _conversation_out(sess)


@router.delete("/{project_id}/agent/conversations/{conversation_id}")
async def delete_agent_conversation(
    project_id: str,
    conversation_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_owned_project(db, user, project_id)
    sess = await _get_session(db, project_id, conversation_id)
    await db.delete(sess)
    await db.commit()
    remaining = await _list_sessions(db, project_id)
    if not remaining:
        # Keep at least one empty conversation so UI always has a target
        await _create_session(db, project_id)
    return {"ok": True}


@router.get("/{project_id}/agent/session", response_model=AgentSessionOut)
async def get_agent_session(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Back-compat: returns the most recently updated conversation."""
    await get_project_readable(db, user, project_id)
    sess = await _get_or_create_latest_session(db, project_id)
    return _conversation_out(sess)


@router.put("/{project_id}/agent/session", response_model=AgentSessionOut)
async def put_agent_session(
    project_id: str,
    body: AgentSessionPutIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Back-compat: writes into the most recently updated conversation."""
    await get_owned_project(db, user, project_id)
    sess = await _get_or_create_latest_session(db, project_id)
    if body.title is not None:
        sess.title = body.title.strip() or sess.title or "新对话"
    if body.messages is not None:
        sess.messages = body.messages
        if (not sess.title or sess.title == "新对话") and body.messages:
            sess.title = _title_from_messages(body.messages)
    if body.chat_memory is not None:
        sess.chat_memory = body.chat_memory
    if body.undo_stack is not None:
        sess.undo_stack = body.undo_stack
    sess.updated_at = datetime.now(timezone.utc)
    await db.commit()
    await db.refresh(sess)
    return _conversation_out(sess)


@router.post("/{project_id}/agent/chapter-revise", response_model=dict)
async def agent_chapter_revise(
    project_id: str,
    body: ChapterReviseIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Two-pass chapter revise: diagnose → full rewrite preview (not written yet)."""
    from app.core.chapter_revise import run_chapter_revise

    row = await get_owned_project(db, user, project_id)
    vn = row_to_vn(row)
    creds = await resolve_llm_credentials(db, user.id, settings)
    if not creds["api_key"]:
        raise HTTPException(
            status_code=400,
            detail="服务端未配置 DEEPSEEK_API_KEY，请在 backend/.env 中设置",
        )
    from app.core.usage import quota_exceeded

    if await quota_exceeded(db, user.id, settings.llm_daily_token_cap):
        raise HTTPException(status_code=429, detail="今日 LLM 用量已达上限，请明日再试")
    cfg = DeepSeekConfig(
        apiKey=creds["api_key"],
        baseUrl=creds["base_url"],
        model=creds["model"],
    )
    critic = DeepSeekConfig(
        apiKey=settings.critic_api_key or creds["api_key"],
        baseUrl=settings.critic_api_base_url or creds["base_url"],
        model=settings.critic_api_model or creds["model"],
    )

    if body.async_mode:
        from types import SimpleNamespace

        from app.core.jobs import create_job
        from app.db import AsyncSessionLocal

        owner = SimpleNamespace(id=user.id)
        payload = {
            "chapter_id": body.chapter_id,
            "note": body.note or "",
            "attachments": list(body.attachments or []),
            "mode": body.mode,
            "preferences": dict(body.preferences or {}) if body.preferences else None,
            "conversation_id": body.conversation_id,
        }

        async def _runner(job):
            await job.touch(stage="revise", progress=0.1, message="章节回炉运行中…")
            async with AsyncSessionLocal() as session:
                row2 = await get_owned_project(session, owner, project_id)
                vn2 = row_to_vn(row2)
                result = await run_chapter_revise(
                    cfg,
                    vn2,
                    chapter_id=payload["chapter_id"],
                    note=payload["note"],
                    attachments=payload["attachments"],
                    mode=payload["mode"],
                    preferences=payload["preferences"],
                    critic_config=critic,
                )
                if payload.get("conversation_id"):
                    sess = await _get_session(
                        session, project_id, payload["conversation_id"]
                    )
                    sess.updated_at = datetime.now(timezone.utc)
                    await session.commit()
                await job.set_result({
                    "message": result.message,
                    "diagnosis": result.diagnosis,
                    "diagnosisMd": result.diagnosis_md,
                    "revisedText": result.revised_text,
                    "sourceText": result.source_text,
                    "chapterId": result.chapter_id,
                    "chapterTitle": result.chapter_title,
                    "sourceChars": result.source_chars,
                    "warnings": list(result.warnings),
                    "debugTrace": list(result.debug_trace),
                    "model": result.model,
                    "criticNote": result.critic_note,
                    "lintIssues": list(result.lint_issues),
                    "llmCalls": list(result.llm_calls),
                    "elapsedMs": result.elapsed_ms,
                    "wrote": False,
                })
                await job.touch(stage="done", progress=0.95, message="回炉预览已生成")

        job = await create_job(
            db,
            kind="chapter_revise",
            project_id=project_id,
            user_id=user.id,
            runner=_runner,
        )
        return {"jobId": job.id, "async": True, "status": job.status}

    try:
        result = await run_chapter_revise(
            cfg,
            vn,
            chapter_id=body.chapter_id,
            note=body.note or "",
            attachments=list(body.attachments or []),
            mode=body.mode,
            preferences=dict(body.preferences or {}) if body.preferences else None,
            critic_config=critic,
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if body.conversation_id:
        sess = await _get_session(db, project_id, body.conversation_id)
        sess.updated_at = datetime.now(timezone.utc)
        await db.commit()

    return {
        "message": result.message,
        "diagnosis": result.diagnosis,
        "diagnosisMd": result.diagnosis_md,
        "revisedText": result.revised_text,
        "sourceText": result.source_text,
        "chapterId": result.chapter_id,
        "chapterTitle": result.chapter_title,
        "sourceChars": result.source_chars,
        "warnings": list(result.warnings),
        "debugTrace": list(result.debug_trace),
        "model": result.model,
        "criticNote": result.critic_note,
        "lintIssues": list(result.lint_issues),
        "llmCalls": list(result.llm_calls),
        "elapsedMs": result.elapsed_ms,
        "wrote": False,
    }


@router.post("/{project_id}/agent/chapter-revise/apply", response_model=dict)
async def agent_chapter_revise_apply(
    project_id: str,
    body: ChapterReviseApplyIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Write a previously previewed chapter revise draft into the chapter."""
    row = await get_owned_project(db, user, project_id)
    vn = row_to_vn(row)
    text = (body.text or "").strip()
    if len(text) < 40:
        raise HTTPException(status_code=400, detail="改写正文过短，无法写入")

    if body.conversation_id:
        sess = await _get_session(db, project_id, body.conversation_id)
        undo = list(sess.undo_stack or [])
        undo.append(project_to_dict(vn))
        sess.undo_stack = undo[-30:]
        sess.updated_at = datetime.now(timezone.utc)

    apply_result = apply_agent_actions(
        vn,
        [{"op": "replace_script", "chapterRef": body.chapter_id, "text": text}],
        defaultChapterId=body.chapter_id,
    )
    if not apply_result.applied:
        detail = "；".join(apply_result.skipped) or "写入失败"
        raise HTTPException(status_code=400, detail=detail)

    sync_row_from_vn(row, apply_result.project)
    await db.commit()
    await db.refresh(row)
    return {
        "message": "已将回炉稿写入当前章。",
        "applied": list(apply_result.applied),
        "skipped": list(apply_result.skipped),
        "project": project_to_dict(row_to_vn(row)),
        "wrote": True,
    }


@router.post("/{project_id}/agent/ingest-settings", response_model=dict)
async def agent_ingest_settings(
    project_id: str,
    body: AgentIngestSettingsIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Force structured write of attachment text into bible / characters / meta."""
    from app.core.settings_ingest import ingest_attachments_to_settings

    row = await get_owned_project(db, user, project_id)
    vn = row_to_vn(row)
    creds = await resolve_llm_credentials(db, user.id, settings)
    if not creds["api_key"]:
        raise HTTPException(
            status_code=400,
            detail="服务端未配置 DEEPSEEK_API_KEY，请在 backend/.env 中设置",
        )
    if not body.attachments:
        raise HTTPException(status_code=400, detail="请先上传附件")

    cfg = DeepSeekConfig(
        apiKey=creds["api_key"],
        baseUrl=creds["base_url"],
        model=creds["model"],
    )
    try:
        result = await ingest_attachments_to_settings(
            cfg,
            vn,
            list(body.attachments),
            user_note=body.note or "",
        )
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    if result.project is not None:
        if body.conversation_id:
            sess = await _get_session(db, project_id, body.conversation_id)
            undo = list(sess.undo_stack or [])
            undo.append(project_to_dict(vn))
            sess.undo_stack = undo[-30:]
            sess.updated_at = datetime.now(timezone.utc)
        sync_row_from_vn(row, result.project)
        await db.commit()
        await db.refresh(row)
        out_project = project_to_dict(row_to_vn(row))
    else:
        out_project = project_to_dict(vn)

    return {
        "message": result.message,
        "actions": result.actions,
        "applied": list(result.applied),
        "skipped": list(result.skipped),
        "project": out_project,
        "wrote": result.project is not None and bool(result.applied),
    }


@router.post("/{project_id}/agent/attachments")
async def upload_agent_attachment(
    project_id: str,
    file: UploadFile = File(...),
    persist: str = Form("true"),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Extract plain text from an uploaded reference file for Agent context."""
    from app.core.file_text import extract_text_from_bytes
    from app.services import analysis_inbox as inbox_svc

    await get_owned_project(db, user, project_id)
    raw = await file.read()
    filename = file.filename or "upload.txt"
    try:
        text, warning = extract_text_from_bytes(raw, filename)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    snippet_id = None
    do_persist = str(persist).strip().lower() in ("1", "true", "yes", "on")
    if do_persist:
        row = await inbox_svc.insert_source_snippet(
            db, project_id, text, source="upload"
        )
        # stash filename on payload
        payload = dict(row.payload or {})
        payload["filename"] = filename
        row.payload = payload
        await db.commit()
        snippet_id = row.id

    return {
        "id": snippet_id,
        "filename": filename,
        "text": text,
        "chars": len(text),
        "warning": warning,
    }


async def _build_agent_request(
    db: AsyncSession,
    project_id: str,
    vn: VnProject,
    body: AgentRunIn,
    settings: Settings,
    creds: dict[str, str],
) -> tuple[AgentRequest, str]:
    """Assemble the AgentRequest (lore / ledger / continuity / attachments)."""
    last_user = ""
    for m in reversed(body.messages or []):
        content = getattr(m, "content", None)
        if content is None and isinstance(m, dict):
            content = m.get("content")
        role = getattr(m, "role", None)
        if role is None and isinstance(m, dict):
            role = m.get("role")
        if role == "user" and content:
            last_user = str(content)
            break

    from app.core.pipeline.ledger import format_ledger_for_agent, get_ledger
    from app.services.lore import resolve_lore_block

    lore = await resolve_lore_block(
        db, project_id, vn, user_message=last_user, limit=4
    )
    ledger_block = format_ledger_for_agent(get_ledger(vn))
    lore_parts = [p for p in [lore.get("agentBlock") or "", ledger_block] if p.strip()]
    lore_combined = "\n\n".join(lore_parts) or None

    from app.core.file_text import format_attachment_block

    reference_docs = format_attachment_block(list(body.attachments or [])) or None

    req = AgentRequest(
        project=vn,
        messages=body.messages,  # type: ignore[arg-type]
        chapterId=body.chapter_id,
        selection=body.selection,
        task=body.task,  # type: ignore[arg-type]
        chatMemory=body.chat_memory,
        longChapterMemory=(
            (await get_latest_continuity(db, project_id) or {}).get("agentBlock")
        ),
        loreCraft=lore_combined,
        referenceDocs=reference_docs,
        craftMode=settings.agent_craft_mode,
        selfReview=settings.agent_self_review,
        lensIds=body.lens_ids,
        criticApiKey=settings.critic_api_key or None,
        criticApiBaseUrl=settings.critic_api_base_url or None,
        criticApiModel=settings.critic_api_model or None,
        apiKey=creds["api_key"],
        apiBaseUrl=creds["base_url"],
        apiModel=creds["model"],
    )
    return req, last_user


async def _finalize_agent_run(
    db: AsyncSession,
    project_id: str,
    row: Project,
    vn: VnProject,
    body: AgentRunIn,
    result: Any,
    last_user: str,
) -> AgentRunOut:
    """Persist agent results: undo stack, actions, inbox proposals, fact scan, session."""
    message = result.message
    actions = result.actions or []
    model = result.model
    context_meta = result.contextMeta
    if context_meta is not None and hasattr(context_meta, "model_dump"):
        context_meta = context_meta.model_dump(mode="json", by_alias=True)
    trace = getattr(result, "trace", None) or []

    if body.conversation_id:
        sess = await _get_session(db, project_id, body.conversation_id)
    else:
        sess = await _get_or_create_latest_session(db, project_id)

    applied = False
    warnings: list[str] = []
    out_project = None
    inbox_added = 0
    if body.apply_actions and actions:
        from app.core.fact_extract import (
            build_scan_candidates,
            filter_new_candidates,
        )
        from app.services import analysis_inbox as inbox_svc

        undo = list(sess.undo_stack or [])
        undo.append(project_to_dict(vn))
        sess.undo_stack = undo[-30:]
        apply_result = apply_agent_actions(vn, actions, defaultChapterId=body.chapter_id)
        new_vn = apply_result.project
        warnings = list(apply_result.skipped or [])

        proposals = inbox_svc.proposals_from_agent(apply_result.inbox_proposals or [])
        if proposals:
            created = await inbox_svc.insert_candidates(db, project_id, proposals)
            inbox_added += len(created)

        if apply_result.scan_request:
            req = apply_result.scan_request
            paste_parts: list[str] = []
            if req.get("includePaste") and last_user:
                paste_parts.append(last_user)
            if body.attachments:
                from app.core.file_text import format_attachment_block

                att = format_attachment_block(list(body.attachments))
                if att:
                    paste_parts.append(att)
            paste = "\n\n".join(paste_parts) if paste_parts else None
            chapter_ref = req.get("chapterRef")
            force = None
            if chapter_ref:
                ch = next(
                    (
                        c
                        for c in new_vn.chapters
                        if c.id == chapter_ref or c.title == chapter_ref
                    ),
                    None,
                )
                force = [ch.id] if ch else None
            cands, _delta, fresh_meta = build_scan_candidates(
                new_vn,
                force_chapter_ids=force,
                paste_text=paste,
                full=False,
            )
            pending_keys = await inbox_svc.blocked_dedupe_keys(db, project_id)
            fresh = filter_new_candidates(new_vn, cands, pending_keys)
            created = await inbox_svc.insert_candidates(db, project_id, fresh)
            inbox_added += len(created)
            new_vn = new_vn.model_copy(update={"analysisMeta": fresh_meta})
            if created:
                warnings.append(f"事实扫描新增 {len(created)} 条待审候选")

        sync_row_from_vn(row, new_vn)
        applied = True
        out_project = None  # set after commit
    else:
        out_project = project_to_dict(vn)

    sess.updated_at = datetime.now(timezone.utc)
    if (not sess.title or sess.title == "新对话") and body.messages:
        sess.title = _title_from_messages(body.messages)
    await db.commit()
    await db.refresh(row)
    await db.refresh(sess)
    if applied:
        out_project = project_to_dict(row_to_vn(row))
        if inbox_added:
            message = f"{message}\n\n（已有 {inbox_added} 条事实候选进入分析待审托盘，请在「写作分析」中确认。）"

    return AgentRunOut(
        message=message,
        actions=actions if isinstance(actions, list) else [],
        model=model,
        context_meta=context_meta if isinstance(context_meta, dict) else None,
        project=out_project,
        applied=applied,
        warnings=warnings,
        conversation_id=sess.id,
        inbox_added=inbox_added,
        trace=trace if isinstance(trace, list) else [],
    )


@router.post("/{project_id}/agent", response_model=AgentRunOut)
async def run_project_agent(
    project_id: str,
    body: AgentRunIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    row = await get_owned_project(db, user, project_id)
    vn = row_to_vn(row)
    creds = await resolve_llm_credentials(db, user.id, settings)
    if not creds["api_key"]:
        raise HTTPException(
            status_code=400,
            detail="服务端未配置 DEEPSEEK_API_KEY，请在 backend/.env 中设置",
        )
    from app.core.usage import quota_exceeded

    if await quota_exceeded(db, user.id, settings.llm_daily_token_cap):
        raise HTTPException(status_code=429, detail="今日 LLM 用量已达上限，请明日再试")

    req, last_user = await _build_agent_request(db, project_id, vn, body, settings, creds)

    cfg = DeepSeekConfig(
        apiKey=creds["api_key"],
        baseUrl=creds["base_url"],
        model=creds["model"],
    )
    try:
        result = await run_agent(cfg, req)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    return await _finalize_agent_run(db, project_id, row, vn, body, result, last_user)


@router.post("/{project_id}/agent/stream")
async def run_project_agent_stream(
    project_id: str,
    body: AgentRunIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """SSE streaming agent run: task/thought/tool/actions events, then final result.

    Event data is JSON: {"type":"task"|"thought"|"tool_call"|"tool_result"|
    "actions"|"review"|"done"|"error", ...}. The final `done` event carries the
    full AgentRunOut payload (same shape as POST /agent).
    """
    row = await get_owned_project(db, user, project_id)
    vn = row_to_vn(row)
    creds = await resolve_llm_credentials(db, user.id, settings)
    if not creds["api_key"]:
        raise HTTPException(
            status_code=400,
            detail="服务端未配置 DEEPSEEK_API_KEY，请在 backend/.env 中设置",
        )
    from app.core.usage import quota_exceeded

    if await quota_exceeded(db, user.id, settings.llm_daily_token_cap):
        raise HTTPException(status_code=429, detail="今日 LLM 用量已达上限，请明日再试")

    req, last_user = await _build_agent_request(db, project_id, vn, body, settings, creds)
    cfg = DeepSeekConfig(
        apiKey=creds["api_key"],
        baseUrl=creds["base_url"],
        model=creds["model"],
    )

    async def event_stream() -> AsyncIterator[str]:
        q: asyncio.Queue[dict] = asyncio.Queue()

        async def sink(evt: dict) -> None:
            await q.put(evt)

        async def _sse(data: dict) -> str:
            return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

        runner = asyncio.create_task(
            run_agent(cfg, req, on_event=sink),
            name=f"agent-stream-{project_id}",
        )
        try:
            while True:
                try:
                    evt = await asyncio.wait_for(q.get(), timeout=20)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                yield await _sse(evt)
                if evt.get("type") == "done":
                    break
            result = await runner
        except asyncio.CancelledError:
            runner.cancel()
            raise
        except Exception as exc:  # noqa: BLE001 - stream errors as SSE events
            if not runner.done():
                runner.cancel()
            yield await _sse({"type": "error", "message": str(exc)[:500]})
            return
        else:
            # Persist + finalize AFTER the loop finished (same as non-streaming).
            final = await _finalize_agent_run(
                db, project_id, row, vn, body, result, last_user
            )
            yield await _sse(
                {"type": "final", "result": final.model_dump(mode="json", by_alias=True)}
            )

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.post("/{project_id}/voice-check")
async def voice_check(
    project_id: str,
    body: VoiceCheckIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    row = await get_owned_project(db, user, project_id)
    vn = row_to_vn(row)
    creds = await resolve_llm_credentials(db, user.id, settings)
    if not creds["api_key"]:
        raise HTTPException(
            status_code=400,
            detail="服务端未配置 DEEPSEEK_API_KEY，请在 backend/.env 中设置",
        )
    cfg = DeepSeekConfig(
        apiKey=creds["api_key"],
        baseUrl=creds["base_url"],
        model=creds["model"],
    )
    try:
        report = await run_voice_check(cfg, vn, chapterId=body.chapter_id)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    issues_out = [
        {
            "character": i.character,
            "severity": i.severity,
            "quote": i.quote,
            "note": i.note,
            "suggestion": i.suggestion,
        }
        for i in report.issues
    ]
    vn = persist_voice_report(
        vn,
        chapter_id=body.chapter_id,
        summary=report.summary,
        issues=issues_out,
        model=report.model,
    )
    sync_row_from_vn(row, vn)
    await db.commit()
    await db.refresh(row)
    fresh = row_to_vn(row)
    # Find the report we just wrote (last matching chapter)
    key = body.chapter_id or None
    persisted = None
    for r in reversed(fresh.voiceReports or []):
        if not isinstance(r, dict):
            continue
        if (r.get("chapterId") or None) == key:
            persisted = r
            break

    return {
        "summary": report.summary,
        "model": report.model,
        "issues": issues_out,
        "persisted": True,
        "stale": bool(persisted.get("stale")) if persisted else False,
        "fingerprint": (persisted or {}).get("fingerprint"),
        "project": project_to_dict(fresh),
    }


@router.post("/{project_id}/ai")
async def run_project_ai(
    project_id: str,
    body: AiRunIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    row = await get_owned_project(db, user, project_id)
    vn = row_to_vn(row)
    creds = await resolve_llm_credentials(db, user.id, settings)
    if not creds["api_key"]:
        raise HTTPException(
            status_code=400,
            detail="服务端未配置 DEEPSEEK_API_KEY，请在 backend/.env 中设置",
        )
    cfg = DeepSeekConfig(
        apiKey=creds["api_key"],
        baseUrl=creds["base_url"],
        model=creds["model"],
    )
    req = AiRequest(
        action=body.action,  # type: ignore[arg-type]
        project=vn,
        selection=body.selection,
        instruction=body.instruction,
        format=body.format,
    )
    try:
        result = await run_ai(cfg, req)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"content": result.content, "model": result.model}


@router.post("/{project_id}/shares", response_model=ShareCreateOut)
async def create_share(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await get_owned_project(db, user, project_id)
    vn = row_to_vn(row)
    token = uid("share").replace("share-", "")
    share = Share(
        project_id=project_id,
        token=token,
        title_snapshot=vn.title,
        data_snapshot=project_to_dict(vn),
    )
    db.add(share)
    vn.shareId = token
    sync_row_from_vn(row, vn)
    await db.commit()
    return ShareCreateOut(token=token, url=f"/share/{token}")


@router.delete("/{project_id}/shares/{token}")
async def revoke_share(
    project_id: str,
    token: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_owned_project(db, user, project_id)
    result = await db.execute(
        select(Share).where(Share.project_id == project_id, Share.token == token)
    )
    share = result.scalar_one_or_none()
    if share is None:
        raise HTTPException(status_code=404, detail="分享不存在")
    await db.delete(share)
    await db.commit()
    return {"ok": True}
