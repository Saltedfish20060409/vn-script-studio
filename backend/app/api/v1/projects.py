from __future__ import annotations

import io
import json
from datetime import datetime, timezone
from typing import Any, List, Optional

from docx import Document
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile
from fastapi.responses import PlainTextResponse, Response
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core import (
    apply_agent_actions,
    build_branch_tree,
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
from app.db import get_db
from app.domain.types import AgentRequest, AiRequest, ProjectSnapshot, VnProject
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
    project_to_dict,
    row_to_vn,
    server_llm_credentials,
    sync_row_from_vn,
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
    row = await get_owned_project(db, user, project_id)
    return project_to_dict(row_to_vn(row))


@router.put("/{project_id}", response_model=dict)
async def put_project(
    project_id: str,
    body: ProjectPutIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await get_owned_project(db, user, project_id)
    if body.updated_at:
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
                    detail="项目已被更新，请刷新后重试",
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
    row = await get_owned_project(db, user, project_id)
    text = export_to_renpy(row_to_vn(row))
    return PlainTextResponse(text, media_type="text/plain; charset=utf-8")


@router.get("/{project_id}/export/json")
async def export_json(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await get_owned_project(db, user, project_id)
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
    """Extract map locations.

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
        creds = server_llm_credentials(settings)
        cfg = DeepSeekConfig(
            apiKey=creds["api_key"],
            baseUrl=creds["base_url"],
            model=creds["model"],
        )
        result = await extract_map_smart(vn, cfg, use_llm=True)

    vn.locations = result["locations"]
    vn.locationLinks = result["locationLinks"]
    sync_row_from_vn(row, vn)
    await db.commit()
    await db.refresh(row)
    return {
        "project": project_to_dict(row_to_vn(row)),
        "addedCount": result.get("addedCount", 0),
        "linkCount": result.get("linkCount", 0),
        "llmAddedCount": result.get("llmAddedCount", 0),
        "llmLinkCount": result.get("llmLinkCount", 0),
        "mode": result.get("mode", mode),
        "llmUsed": bool(result.get("llmUsed")),
        "warnings": result.get("warnings") or [],
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
    row = await get_owned_project(db, user, project_id)
    vn = row_to_vn(row)
    snaps = vn.snapshots or []
    return [
        {"id": s.id, "label": s.label, "createdAt": s.createdAt}
        for s in snaps
    ]


@router.post("/{project_id}/snapshots")
async def create_snapshot(
    project_id: str,
    body: SnapshotCreateIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await get_owned_project(db, user, project_id)
    vn = row_to_vn(row)
    snaps = list(vn.snapshots or [])
    payload = project_to_dict(vn)
    payload.pop("snapshots", None)
    snap = {
        "id": uid("snap"),
        "label": body.label,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "payload": json.dumps(payload, ensure_ascii=False),
    }
    snaps.append(ProjectSnapshot(**snap))
    # keep last 20
    snaps = snaps[-20:]
    vn.snapshots = snaps
    sync_row_from_vn(row, vn)
    await db.commit()
    return {"id": snap["id"], "label": snap["label"], "createdAt": snap["createdAt"]}


@router.post("/{project_id}/snapshots/{snap_id}/restore", response_model=dict)
async def restore_snapshot(
    project_id: str,
    snap_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await get_owned_project(db, user, project_id)
    vn = row_to_vn(row)
    snaps = vn.snapshots or []
    target = next((s for s in snaps if s.id == snap_id), None)
    if target is None:
        raise HTTPException(status_code=404, detail="快照不存在")
    restored = normalize_project(json.loads(target.payload))
    restored.id = project_id
    restored.snapshots = snaps
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
    row = await get_owned_project(db, user, project_id)
    vn = row_to_vn(row)
    vn.snapshots = [s for s in (vn.snapshots or []) if s.id != snap_id]
    sync_row_from_vn(row, vn)
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
    await get_owned_project(db, user, project_id)
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
    await get_owned_project(db, user, project_id)
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
    await get_owned_project(db, user, project_id)
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
    creds = server_llm_credentials(settings)
    if not creds["api_key"]:
        raise HTTPException(
            status_code=400,
            detail="服务端未配置 DEEPSEEK_API_KEY，请在 backend/.env 中设置",
        )

    critic_key = settings.critic_api_key or None
    critic_base = settings.critic_api_base_url or None
    critic_model = settings.critic_api_model or None

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

    from app.services.lore import resolve_lore_block
    from app.core.pipeline.ledger import format_ledger_for_agent, get_ledger

    lore = await resolve_lore_block(
        db, project_id, vn, user_message=last_user, limit=4
    )
    ledger_block = format_ledger_for_agent(get_ledger(vn))
    lore_parts = [p for p in [lore.get("agentBlock") or "", ledger_block] if p.strip()]
    lore_combined = "\n\n".join(lore_parts) or None

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
        craftMode=settings.agent_craft_mode,
        selfReview=settings.agent_self_review,
        lensIds=body.lens_ids,
        criticApiKey=critic_key,
        criticApiBaseUrl=critic_base,
        criticApiModel=critic_model,
        apiKey=creds["api_key"],
        apiBaseUrl=creds["base_url"],
        apiModel=creds["model"],
    )

    cfg = DeepSeekConfig(
        apiKey=creds["api_key"],
        baseUrl=creds["base_url"],
        model=creds["model"],
    )
    try:
        result = await run_agent(cfg, req)
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    message = result.message
    actions = result.actions or []
    model = result.model
    context_meta = result.contextMeta
    if context_meta is not None and hasattr(context_meta, "model_dump"):
        context_meta = context_meta.model_dump(mode="json", by_alias=True)

    if body.conversation_id:
        sess = await _get_session(db, project_id, body.conversation_id)
    else:
        sess = await _get_or_create_latest_session(db, project_id)

    applied = False
    warnings: list[str] = []
    out_project = None
    if body.apply_actions and actions:
        undo = list(sess.undo_stack or [])
        undo.append(project_to_dict(vn))
        sess.undo_stack = undo[-30:]
        apply_result = apply_agent_actions(vn, actions)
        new_vn = apply_result.project
        warnings = list(apply_result.skipped or [])
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

    return AgentRunOut(
        message=message,
        actions=actions if isinstance(actions, list) else [],
        model=model,
        context_meta=context_meta if isinstance(context_meta, dict) else None,
        project=out_project,
        applied=applied,
        warnings=warnings,
        conversation_id=sess.id,
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
    creds = server_llm_credentials(settings)
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

    return {
        "summary": report.summary,
        "model": report.model,
        "issues": [
            {
                "character": i.character,
                "severity": i.severity,
                "quote": i.quote,
                "note": i.note,
                "suggestion": i.suggestion,
            }
            for i in report.issues
        ],
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
    creds = server_llm_credentials(settings)
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
