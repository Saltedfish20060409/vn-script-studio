from __future__ import annotations

import asyncio
import io
import json
import re
from datetime import datetime, timezone
from typing import Any, AsyncIterator, Dict, List, Optional

from docx import Document
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse, Response, StreamingResponse
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core import (
    accept_map_extract_proposal,
    apply_agent_actions,
    build_branch_tree,
    build_map_extract_proposal,
    export_to_renpy,
    extract_map_from_script,
    extract_map_smart,
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
from app.core.rate_limit import check_rate
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
    AgentIngestSettingsIn,
    AgentRunIn,
    AgentRunOut,
    AgentSessionOut,
    AgentSessionPutIn,
    AiRunIn,
    ChapterReviseApplyIn,
    ChapterReviseIn,
    FactsAcceptIn,
    FactsAckStaleIn,
    FactsRejectIn,
    FactsScanIn,
    GenerateRpyIn,
    LintIn,
    MapExtractAcceptIn,
    MapExtractIn,
    ProjectCreateIn,
    ProjectPatchIn,
    ProjectPutIn,
    ProjectSummary,
    ShareCreateOut,
    SnapshotCompareIn,
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
    sync_chapter_rows_from_vn,
)
from app.services.snapshots import (
    create_snapshot as create_snapshot_row,
)
from app.services.snapshots import (
    delete_snapshot as delete_snapshot_row,
)
from app.services.snapshots import (
    get_snapshot_payload,
)
from app.services.snapshots import (
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


@router.get("/templates", response_model=dict)
async def list_templates(user: User = Depends(get_current_user)):
    """Starter templates metadata (title / genre / logline / characters)."""
    from app.core.templates import list_template_meta

    return {"templates": list_template_meta()}


@router.post("", response_model=dict)
async def create_project(
    body: ProjectCreateIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    if not check_rate(
        user.id,
        "create_project",
        limit=40,
        enabled=settings.rate_limit_enabled,
        window=3600,
    ):
        raise HTTPException(status_code=429, detail="新建过于频繁，请稍后再试")
    if body.template_id:
        from app.core.templates import TEMPLATES

        if body.template_id not in TEMPLATES:
            raise HTTPException(status_code=400, detail="未知模板")
    try:
        row = await create_project_row(
            db,
            user,
            title=body.title,
            from_demo=body.from_demo,
            template_id=body.template_id,
        )
    except KeyError as exc:
        raise HTTPException(status_code=400, detail="未知模板") from exc
    return project_to_dict(row_to_vn(row))


@router.post("/import", response_model=dict)
async def import_project(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    file: Optional[UploadFile] = File(None),
    text: Optional[str] = Form(None),
    title: Optional[str] = Form(None),
    json_body: Optional[str] = Form(None),
):
    if not check_rate(
        user.id,
        "create_project",
        limit=40,
        enabled=settings.rate_limit_enabled,
        window=3600,
    ):
        raise HTTPException(status_code=429, detail="导入过于频繁，请稍后再试")
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
        if len(content) > 2 * 1024 * 1024:
            raise HTTPException(status_code=413, detail="文件过大（限 2MB）")
        name = (file.filename or "").lower()
        if name.endswith(".json") or name.endswith(".vnss-share.json"):
            try:
                raw = json.loads(content.decode("utf-8-sig"))
            except (json.JSONDecodeError, UnicodeDecodeError) as exc:
                raise HTTPException(status_code=400, detail="无效的 JSON 文件") from exc
            if isinstance(raw, dict) and "project" in raw:
                raw = raw["project"]
            vn = normalize_project(raw)
            vn = normalize_project({**project_to_dict(vn), "id": uid("proj")})
        elif name.endswith(".docx"):
            doc = await asyncio.to_thread(Document, io.BytesIO(content))
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
    # 并发写保护：在当前事务内锁定项目行直到 commit，使
    # 「锁断言 → 合并 → 保存」成为临界区（此前锁只断言不持有，存在 TOCTOU）。
    await db.refresh(row, with_for_update=True)

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
        # JSONB split stage 1: persist blob + chapter rows together.
        await sync_chapter_rows_from_vn(db, row, merged)
        from app.services.snapshots import maybe_auto_snapshot

        await maybe_auto_snapshot(db, project_id, row_to_vn(row))
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
    await sync_chapter_rows_from_vn(db, row, vn)
    from app.services.snapshots import maybe_auto_snapshot

    await maybe_auto_snapshot(db, project_id, row_to_vn(row))
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
    # 与 put_project 相同：事务内行锁，防并发 patch 丢更新
    await db.refresh(row, with_for_update=True)
    vn = row_to_vn(row)
    if body.title is not None:
        vn.title = body.title
    if body.logline is not None:
        vn.logline = body.logline
    if body.genre is not None:
        vn.genre = body.genre
    await sync_chapter_rows_from_vn(db, row, vn)
    from app.services.snapshots import maybe_auto_snapshot

    await maybe_auto_snapshot(db, project_id, row_to_vn(row))
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
    # All child tables (chapter rows, members, comments, locks, snapshots,
    # invites, inbox, memory archives, jobs, usage, lore cards, shares,
    # agent sessions) reference projects.id with ON DELETE CASCADE — removing
    # the project row cleans everything up.
    await db.delete(row)
    await db.commit()
    return {"ok": True}


@router.post("/{project_id}/duplicate", response_model=dict)
async def duplicate_project(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    if not check_rate(
        user.id,
        "create_project",
        limit=40,
        enabled=settings.rate_limit_enabled,
        window=3600,
    ):
        raise HTTPException(status_code=429, detail="复制过于频繁，请稍后再试")
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
    from app.core.export_text import attachment_disposition

    return Response(
        content=buf.getvalue(),
        media_type="application/zip",
        headers={"Content-Disposition": attachment_disposition(f"{safe}-renpy.zip")},
    )


@router.get("/{project_id}/export/markdown")
async def export_markdown(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Submission export: whole project as readable Markdown."""
    from app.core.export_text import (
        attachment_disposition,
        project_to_markdown,
        safe_filename,
    )

    row = await get_project_readable(db, user, project_id)
    vn = row_to_vn(row)
    text = project_to_markdown(vn)
    return Response(
        content=text.encode("utf-8"),
        media_type="text/markdown; charset=utf-8",
        headers={
            "Content-Disposition": attachment_disposition(safe_filename(vn.title, ".md"))
        },
    )


@router.get("/{project_id}/export/docx")
async def export_docx(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Submission export: whole project as a styled Word document."""
    from app.core.export_text import (
        attachment_disposition,
        project_to_docx,
        safe_filename,
    )

    row = await get_project_readable(db, user, project_id)
    vn = row_to_vn(row)
    content = project_to_docx(vn)
    return Response(
        content=content,
        media_type="application/vnd.openxmlformats-officedocument.wordprocessingml.document",
        headers={
            "Content-Disposition": attachment_disposition(
                safe_filename(vn.title, ".docx")
            )
        },
    )


@router.post("/{project_id}/generate-rpy")
async def generate_rpy_from_prose_api(
    project_id: str,
    body: GenerateRpyIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Turn a chapter's natural-language manuscript into Ren'Py blocks."""
    from app.core.prose_rpy import generate_rpy_from_prose, prose_fingerprint
    from app.core.rate_limit import require_rate
    from app.core.usage import ensure_under_quota

    require_rate(
        user.id,
        "llm_write",
        240,
        enabled=settings.rate_limit_enabled,
        window=3600,
        detail="生成过于频繁，请稍后再试",
    )
    row = await get_owned_project(db, user, project_id)
    vn = row_to_vn(row)
    ch = next((c for c in vn.chapters if c.id == body.chapter_id), None)
    if ch is None:
        raise HTTPException(status_code=404, detail="章节不存在")

    creds = await resolve_llm_credentials(db, user.id, settings)
    cfg = None
    use_llm = body.use_llm and bool(creds.get("api_key"))
    if use_llm:
        await ensure_under_quota(db, user.id, settings, creds)
        cfg = DeepSeekConfig(
            apiKey=creds["api_key"],
            baseUrl=creds["base_url"],
            model=creds["model"],
        )
    try:
        rpy, blocks = await generate_rpy_from_prose(
            vn, body.prose, cfg, use_llm=use_llm
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except RuntimeError as exc:
        raise HTTPException(status_code=502, detail=str(exc)) from exc

    return {
        "rpy": rpy,
        "blocks": blocks,
        "usedLlm": use_llm,
        "proseHash": prose_fingerprint(body.prose),
    }


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
        from app.core.usage import ensure_under_quota

        await ensure_under_quota(db, user.id, settings, creds)
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
    await sync_chapter_rows_from_vn(db, row, vn)
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
        await sync_chapter_rows_from_vn(db, row, new_vn)
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
        from app.core.usage import ensure_under_quota

        await ensure_under_quota(db, user.id, settings, creds)
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
    await sync_chapter_rows_from_vn(db, row, vn)
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
    await sync_chapter_rows_from_vn(db, row, touch_project(vn))
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
    await sync_chapter_rows_from_vn(db, row, touch_project(vn))
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


class SemanticSearchIn(BaseModel):
    query: str = Field(default="", min_length=1, max_length=300)
    limit: int = Field(default=8, ge=1, le=30)
    # When true, also (re)index the project's text chunks before searching.
    reindex: bool = False


@router.post("/{project_id}/analysis/semantic-search")
async def analysis_semantic_search(
    project_id: str,
    body: SemanticSearchIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Semantic search over project text (chapters + bible).

    Uses pgvector similarity when the vector extension and an embedding
    endpoint are configured; otherwise falls back to the heuristic keyword
    ranker (always available). The response reports which engine served it.
    """
    from app.core.retrieval import rank_texts
    from app.core.semantic_search import (
        index_project_chunks,
        is_vector_available,
        semantic_search,
    )

    row = await get_project_readable(db, user, project_id)
    vn = row_to_vn(row)
    q = body.query.strip()

    # Build chapter + bible chunks for fallback ranking / indexing.
    from app.core.agent_context import _blocks_to_plain

    chapters = list(vn.chapters or [])
    chunks: list[dict] = []
    for ch in chapters:
        plain = _blocks_to_plain(ch.blocks or [], vn.characters or [])
        if plain.strip():
            chunks.append({"id": f"ch:{ch.id}", "kind": "chapter", "text": plain})
    bible_blob = {}
    b = vn.bible
    if b is not None:
        data = b.model_dump(mode="json") if hasattr(b, "model_dump") else dict(b)
        for k in ("world", "background", "outline", "themes", "notes"):
            v = data.get(k)
            if isinstance(v, str) and v.strip():
                bible_blob[k] = v.strip()
                chunks.append({"id": f"bible:{k}", "kind": "bible", "text": v})

    # Try vector search first.
    vector = await is_vector_available(db)
    if vector and body.reindex and chunks:
        await index_project_chunks(db, project_id, chunks)
    hits = await semantic_search(db, project_id, q, limit=body.limit) if vector else None

    if hits:
        # Strip the "{project_id}:" prefix from stored ids for the client.
        prefix = f"{project_id}:"
        return {
            "query": q,
            "engine": "pgvector",
            "hits": [
                {
                    "id": h["id"].removeprefix(prefix) if h["id"].startswith(prefix) else h["id"],
                    "kind": h["kind"],
                    "text": h["text"],
                    "score": h["score"],
                }
                for h in hits
            ],
        }

    # Fallback: heuristic ranking over current project text. Build candidates
    # straight from the non-empty chunks so ids and texts never misalign (an
    # empty chapter would previously shift every subsequent zip pairing).
    candidates: list[tuple[str, str]] = [
        (c["id"], c["text"]) for c in chunks if c["kind"] == "chapter"
    ]
    candidates += [(f"bible:{k}", v) for k, v in bible_blob.items()]
    ranked = rank_texts(q, candidates, limit=body.limit, min_score=0.4)
    return {
        "query": q,
        "engine": "heuristic",
        "hits": [
            {"id": cid, "kind": "chapter" if cid.startswith("chapter:") else "bible",
             "text": snippet, "score": score}
            for cid, snippet, score in ranked
        ],
    }


@router.get("/{project_id}/stats")
async def project_stats(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Writing stats: per-chapter metrics + recent daily activity (heatmap)."""
    from app.services.writing_stats import chapter_metrics, recent_activity

    row = await get_project_readable(db, user, project_id)
    vn = row_to_vn(row)
    chapters = chapter_metrics(vn)
    total_words = sum(c["words"] for c in chapters)
    total_lines = sum(c["lines"] for c in chapters)
    activity = await recent_activity(db, project_id, days=30)
    return {
        "projectId": project_id,
        "totals": {
            "chapters": len(chapters),
            "words": total_words,
            "lines": total_lines,
            "avgChapterWords": round(total_words / len(chapters), 1) if chapters else 0,
        },
        "chapters": chapters,
        "activity": activity,
    }


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
    settings: Settings = Depends(get_settings),
):
    from app.core.rate_limit import require_rate

    require_rate(
        user.id,
        "create_snapshot",
        200,
        enabled=settings.rate_limit_enabled,
        window=3600,
        detail="快照创建过于频繁，请稍后再试",
    )
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
    await sync_chapter_rows_from_vn(db, row, restored)
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


@router.post("/{project_id}/snapshots/compare")
async def compare_snapshots_endpoint(
    project_id: str,
    body: SnapshotCompareIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Deterministic diff: snapshot vs snapshot, or snapshot vs live project.

    Lets the user preview what a restore would change before committing.
    """
    from app.core.snapshot_diff import compare_snapshots
    from app.core.snapshots import content_hash_for_payload, snapshot_payload_dict

    row = await get_owned_project(db, user, project_id)
    from_payload = await get_snapshot_payload(db, project_id, body.from_snap_id)
    if from_payload is None:
        raise HTTPException(status_code=404, detail="源快照不存在")
    if body.to_snap_id:
        to_payload = await get_snapshot_payload(db, project_id, body.to_snap_id)
        if to_payload is None:
            raise HTTPException(status_code=404, detail="目标快照不存在")
    else:
        to_payload = snapshot_payload_dict(row_to_vn(row))

    diff = compare_snapshots(from_payload, to_payload)
    diff["fromHash"] = content_hash_for_payload(
        decode_snapshot_payload(from_payload)
    )
    diff["toHash"] = content_hash_for_payload(
        decode_snapshot_payload(to_payload)
    )
    return diff


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
    from app.core.rate_limit import require_rate
    from app.core.usage import ensure_under_quota

    require_rate(
        user.id,
        "llm_write",
        240,
        enabled=settings.rate_limit_enabled,
        window=3600,
        detail="改稿过于频繁，请稍后再试",
    )
    row = await get_owned_project(db, user, project_id)
    vn = row_to_vn(row)
    creds = await resolve_llm_credentials(db, user.id, settings)
    if not creds["api_key"]:
        raise HTTPException(
            status_code=400,
            detail="服务端未配置 DEEPSEEK_API_KEY，请在 backend/.env 中设置",
        )
    await ensure_under_quota(db, user.id, settings, creds)
    cfg = DeepSeekConfig(
        apiKey=creds["api_key"],
        baseUrl=creds["base_url"],
        model=creds["model"],
    )
    critic = DeepSeekConfig(
        apiKey=creds.get("critic_api_key") or creds["api_key"],
        baseUrl=creds.get("critic_base_url") or creds["base_url"],
        model=creds.get("critic_model") or creds["model"],
    )

    if body.async_mode:
        from types import SimpleNamespace

        from app.core.chapter_revise import run_chapter_revise
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

    await sync_chapter_rows_from_vn(db, row, apply_result.project)
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

    from app.core.usage import ensure_under_quota

    await ensure_under_quota(db, user.id, settings, creds)
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
        await sync_chapter_rows_from_vn(db, row, result.project)
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

    # 对话记忆：优先用会话表已归档的 LLM 摘要（前端通常传空），
    # 长对话据此累积早期决定/设定共识，不丢上下文。
    prior_memory = (body.chat_memory or "").strip()
    if not prior_memory and body.conversation_id:
        try:
            sess = await _get_session(db, project_id, body.conversation_id)
            prior_memory = (sess.chat_memory or "").strip()
        except Exception:  # noqa: BLE001
            prior_memory = ""

    req = AgentRequest(
        project=vn,
        messages=body.messages,  # type: ignore[arg-type]
        chapterId=body.chapter_id,
        selection=body.selection,
        task=body.task,  # type: ignore[arg-type]
        chatMemory=prior_memory or None,
        longChapterMemory=(
            (await get_latest_continuity(db, project_id) or {}).get("agentBlock")
        ),
        loreCraft=lore_combined,
        referenceDocs=reference_docs,
        craftMode=settings.agent_craft_mode,
        selfReview=settings.agent_self_review,
        lensIds=body.lens_ids,
        criticApiKey=creds.get("critic_api_key") or None,
        criticApiBaseUrl=creds.get("critic_base_url") or None,
        criticApiModel=creds.get("critic_model") or None,
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

        await sync_chapter_rows_from_vn(db, row, new_vn)
        applied = True
        out_project = None  # set after commit
    else:
        out_project = project_to_dict(vn)

    sess.updated_at = datetime.now(timezone.utc)
    if (not sess.title or sess.title == "新对话") and body.messages:
        sess.title = _title_from_messages(body.messages)
    # 持久化 LLM 对话记忆归档：下次请求作为 prior_memory 累积，
    # 长对话不丢早期决定/设定共识。
    if isinstance(context_meta, dict) and context_meta.get("chatMemorySummary"):
        sess.chat_memory = context_meta["chatMemorySummary"]
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
    from app.core.rate_limit import require_rate
    from app.core.usage import ensure_under_quota

    require_rate(
        user.id,
        "llm_write",
        240,
        enabled=settings.rate_limit_enabled,
        window=3600,
        detail="Agent 调用过于频繁，请稍后再试",
    )
    row = await get_owned_project(db, user, project_id)
    vn = row_to_vn(row)
    creds = await resolve_llm_credentials(db, user.id, settings)
    if not creds["api_key"]:
        raise HTTPException(
            status_code=400,
            detail="服务端未配置 DEEPSEEK_API_KEY，请在 backend/.env 中设置",
        )
    await ensure_under_quota(db, user.id, settings, creds)

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
    from app.core.rate_limit import require_rate
    from app.core.usage import ensure_under_quota

    require_rate(
        user.id,
        "llm_write",
        240,
        enabled=settings.rate_limit_enabled,
        window=3600,
        detail="Agent 调用过于频繁，请稍后再试",
    )
    row = await get_owned_project(db, user, project_id)
    vn = row_to_vn(row)
    creds = await resolve_llm_credentials(db, user.id, settings)
    if not creds["api_key"]:
        raise HTTPException(
            status_code=400,
            detail="服务端未配置 DEEPSEEK_API_KEY，请在 backend/.env 中设置",
        )
    await ensure_under_quota(db, user.id, settings, creds)

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
                # runner 已结束且队列排空（没有 done 事件）→ 把异常/空结果转成
                # error 事件，否则循环会永远 keepalive（此前中途失败=前端无限
                # "正在检索设定"）。注意必须等队列排空再判：runner 可能刚把
                # 最后几个事件放进队列就结束了，不能跳过它们。
                if runner.done() and q.empty():
                    try:
                        exc = runner.exception()
                    except asyncio.CancelledError:
                        raise
                    if exc is not None:
                        yield await _sse(
                            {"type": "error", "message": str(exc)[:500]}
                        )
                    else:
                        yield await _sse(
                            {"type": "error", "message": "Agent 未产出结果，请重试"}
                        )
                    return
                try:
                    evt = await asyncio.wait_for(q.get(), timeout=20)
                except asyncio.TimeoutError:
                    if runner.done():
                        try:
                            exc = runner.exception()
                        except asyncio.CancelledError:
                            raise
                        if exc is not None:
                            yield await _sse(
                                {"type": "error", "message": str(exc)[:500]}
                            )
                        else:
                            yield await _sse(
                                {"type": "error", "message": "Agent 未产出结果，请重试"}
                            )
                        return
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
    from app.core.usage import ensure_under_quota

    await ensure_under_quota(db, user.id, settings, creds)
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
    await sync_chapter_rows_from_vn(db, row, vn)
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
    from app.core.usage import ensure_under_quota

    await ensure_under_quota(db, user.id, settings, creds)
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
    # Cryptographically random, unguessable share token (uid()'s timestamp+5
    # random chars is far too low-entropy for an unauthenticated public link).
    import secrets as _secrets

    token = _secrets.token_urlsafe(24)
    share = Share(
        project_id=project_id,
        token=token,
        title_snapshot=vn.title,
        data_snapshot=project_to_dict(vn),
    )
    db.add(share)
    vn.shareId = token
    await sync_chapter_rows_from_vn(db, row, vn)
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
