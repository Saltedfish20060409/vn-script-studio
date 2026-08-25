from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core import (
    create_demo_project,
    empty_project,
    normalize_project,
    touch_project,
    uid,
)
from app.core.chapter_digest import refresh_chapter_index
from app.core.voice_reports import mark_voice_reports_stale
from app.domain.types import VnProject
from app.llm_models import DEFAULT_LLM_MODEL
from app.models import Project, User


def project_to_dict(p: VnProject | dict[str, Any]) -> dict[str, Any]:
    if isinstance(p, VnProject):
        return p.model_dump(mode="json", by_alias=True)
    return dict(p)


def row_to_vn(row: Project) -> VnProject:
    data = dict(row.data or {})
    data["id"] = row.id
    data["title"] = row.title
    data["logline"] = row.logline
    data["genre"] = row.genre
    data["updatedAt"] = row.updated_at.isoformat()
    return normalize_project(data)


def sync_row_from_vn(row: Project, vn: VnProject) -> None:
    touched = touch_project(vn)
    touched = refresh_chapter_index(touched)
    touched = mark_voice_reports_stale(touched)
    payload = project_to_dict(touched)
    row.title = touched.title
    row.logline = touched.logline
    row.genre = touched.genre
    row.data = payload
    row.updated_at = datetime.now(timezone.utc)
    # 乐观锁版本号：任何写路径都自增（见 Project.row_version 注释）
    row.row_version = int(row.row_version or 0) + 1
    payload["updatedAt"] = row.updated_at.isoformat()
    payload["rowVersion"] = row.row_version
    row.data = payload


# Top-level fields that can be declared as "sections" in a chapter-scoped save.
MERGE_SECTIONS = [
    "title",
    "logline",
    "genre",
    "characters",
    "lore",
    "bible",
    "locations",
    "locationLinks",
    "mapStyle",
    "customMapElements",
    "mapStrokes",
    "characterLinks",
    "timeline",
    "variables",
    "sprites",
    "writingLedger",
    "writingMentors",
    "authorLenses",
    "voiceReports",
]


def merge_project_changes(
    server: VnProject,
    client: VnProject,
    chapter_ids: list[str],
    sections: list[str],
) -> VnProject:
    """Merge client changes into the server version, chapter-scoped.

    ``chapter_ids`` lists the chapters this save actually touched (create /
    update / delete). Unlisted chapters keep the server version untouched, so
    concurrent edits to different chapters do not clobber each other. ``sections``
    lists non-chapter top-level fields the client modified; anything unlisted is
    kept from the server. The result keeps the server's updatedAt and id.
    """
    server_data = project_to_dict(server)
    client_data = project_to_dict(client)

    if chapter_ids:
        wanted = set(chapter_ids)
        client_by_id = {c.get("id"): c for c in client_data.get("chapters", [])}
        merged_chapters: list[Any] = []
        for ch in server_data.get("chapters", []):
            cid = ch.get("id")
            if cid in wanted:
                replacement = client_by_id.get(cid)
                if replacement is not None:
                    merged_chapters.append(replacement)
                # cid in wanted but absent from client → chapter was deleted
            else:
                merged_chapters.append(ch)
        # Client-created chapters not present on the server are appended.
        server_ids = {c.get("id") for c in server_data.get("chapters", [])}
        for ch in client_data.get("chapters", []):
            cid = ch.get("id")
            if cid in wanted and cid not in server_ids:
                merged_chapters.append(ch)
        server_data["chapters"] = merged_chapters

    allowed = set(sections) & set(MERGE_SECTIONS)
    for key in allowed:
        server_data[key] = client_data.get(key)

    server_data["updatedAt"] = server_data.get("updatedAt") or client_data.get("updatedAt")
    return normalize_project(server_data)


async def get_owned_project(db: AsyncSession, user: User, project_id: str) -> Project:
    """Access control: project owner or a project member with write rights.

    Backward compatible — owner behaviour unchanged; editors are now allowed.
    Non-members get 404 (project existence is not leaked); viewers get 403.
    """
    row = await get_project_row(db, project_id)
    if row is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    if row.owner_id == user.id:
        return row
    role = await member_role(db, project_id, user.id)
    if role in ("owner", "editor"):
        return row
    if role == "viewer":
        raise HTTPException(status_code=403, detail="无编辑权限（只读成员）")
    raise HTTPException(status_code=404, detail="项目不存在")


async def get_project_readable(db: AsyncSession, user: User, project_id: str) -> Project:
    """Read access: project owner or any member (editor / viewer)."""
    row = await get_project_row(db, project_id)
    if row is None:
        raise HTTPException(status_code=404, detail="项目不存在")
    if row.owner_id == user.id:
        return row
    role = await member_role(db, project_id, user.id)
    if role in ("owner", "editor", "viewer"):
        return row
    raise HTTPException(status_code=404, detail="项目不存在")


async def get_project_row(db: AsyncSession, project_id: str) -> Optional[Project]:
    result = await db.execute(select(Project).where(Project.id == project_id))
    return result.scalar_one_or_none()


# --------------------------------------------------------------------------
# Chapter rows (JSONB split stage 1)
#
# Chapters are the hot write path (every edit bumps the project blob). We
# persist each chapter into project_chapter_rows so a chapter-scoped save only
# rewrites that one row + the blob mirror, instead of the whole project. The
# blob keeps a mirror for sync read paths (row_to_vn); the table is the
# durable write path.
# --------------------------------------------------------------------------


def _chapter_row_id(project_id: str, chapter_id: str) -> str:
    return f"{project_id}:{chapter_id}"


async def upsert_chapter_rows(
    db: AsyncSession,
    project_id: str,
    chapters: list[dict],
) -> None:
    """Write chapters into project_chapter_rows (upsert by id).

    ``chapters`` are dicts (project_to_dict shape) with id/title/synopsis/blocks.
    Rows for chapters no longer present are deleted (reorder/delete handled by
    the caller updating the blob first, then calling this).
    """
    from app.models import ProjectChapterRow

    keep_ids = set()
    for idx, ch in enumerate(chapters):
        ch_id = ch.get("id")
        if not ch_id:
            continue
        row_id = _chapter_row_id(project_id, ch_id)
        keep_ids.add(row_id)
        existing = await db.get(ProjectChapterRow, row_id)
        if existing is None:
            db.add(
                ProjectChapterRow(
                    id=row_id,
                    project_id=project_id,
                    chapter_id=ch_id,
                    title=ch.get("title") or "",
                    synopsis=ch.get("synopsis") or "",
                    blocks=ch.get("blocks") or [],
                    sort_order=idx,
                    updated_at=datetime.now(timezone.utc),
                )
            )
        else:
            existing.title = ch.get("title") or ""
            existing.synopsis = ch.get("synopsis") or ""
            existing.blocks = ch.get("blocks") or []
            existing.sort_order = idx
            existing.updated_at = datetime.now(timezone.utc)

    # Remove rows whose chapter vanished from the blob (deleted chapters).
    res = await db.execute(
        select(ProjectChapterRow).where(ProjectChapterRow.project_id == project_id)
    )
    for row in res.scalars().all():
        if row.id not in keep_ids:
            await db.delete(row)


async def sync_chapter_rows_from_vn(
    db: AsyncSession,
    row: Project,
    vn: VnProject,
) -> None:
    """Persist a project row AND mirror its chapters into project_chapter_rows.

    Every chapter-writing path should go through this so the blob and the
    shadow table stay consistent (stage-1 JSONB split). Also records the
    word-count delta into writing_activity for the stats dashboard.
    """
    from app.services.writing_stats import count_blocks_words, record_activity

    prev_vn = row_to_vn(row)
    prev_words = sum(
        count_blocks_words(list(c.blocks or [])) for c in (prev_vn.chapters or [])
    )
    sync_row_from_vn(row, vn)
    chapters = [c.model_dump(mode="json") for c in (vn.chapters or [])]
    await upsert_chapter_rows(db, row.id, chapters)
    current_words = sum(
        count_blocks_words(list(c.get("blocks") or [])) for c in chapters
    )
    await record_activity(db, row.id, previous_words=prev_words, current_words=current_words)


async def load_chapter_rows(
    db: AsyncSession,
    project_id: str,
) -> list[dict]:
    """Read chapters from project_chapter_rows (ordered), None-safe.

    NOTE: the blob remains the authoritative chapter source until stage 2
    migrates every read path to this table — callers must keep the two in
    sync via upsert_chapter_rows on every chapter write.
    """
    from app.models import ProjectChapterRow

    res = await db.execute(
        select(ProjectChapterRow)
        .where(ProjectChapterRow.project_id == project_id)
        .order_by(ProjectChapterRow.sort_order.asc())
    )
    return [
        {
            "id": row.chapter_id,
            "title": row.title,
            "synopsis": row.synopsis or None,
            "blocks": row.blocks or [],
        }
        for row in res.scalars().all()
    ]


async def member_role(db: AsyncSession, project_id: str, user_id: str) -> Optional[str]:
    """Return the member role for (project, user) or None."""
    from app.models import ProjectMember

    result = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
    )
    row = result.scalar_one_or_none()
    return row.role if row else None


async def create_project_row(
    db: AsyncSession,
    user: User,
    *,
    title: Optional[str] = None,
    from_demo: bool = False,
    template_id: Optional[str] = None,
    vn: Optional[VnProject] = None,
) -> Project:
    if vn is not None:
        project = normalize_project(vn)
    elif template_id:
        from app.core.templates import build_from_template

        project = build_from_template(template_id, title=title)
        project = normalize_project(
            {**project_to_dict(project), "id": uid("proj")}
        )
    elif from_demo:
        project = create_demo_project()
        project = normalize_project(
            {**project_to_dict(project), "id": uid("proj")}
        )
    else:
        project = empty_project(title or "未命名剧本")

    cap = int(getattr(get_settings(), "max_projects_per_user", 0) or 0)
    if cap > 0:
        owned = await db.scalar(
            select(func.count()).select_from(Project).where(Project.owner_id == user.id)
        )
        if int(owned or 0) >= cap:
            raise HTTPException(
                status_code=403,
                detail=f"项目数已达上限（{cap}）。删除不用的剧本后再建。",
            )

    if title:
        project.title = title

    project = refresh_chapter_index(normalize_project(project))
    project = mark_voice_reports_stale(project)

    now = datetime.now(timezone.utc)
    payload = project_to_dict(project)
    payload["updatedAt"] = now.isoformat()
    row = Project(
        id=project.id,
        owner_id=user.id,
        title=project.title,
        genre=project.genre,
        logline=project.logline,
        data=payload,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    # Mirror initial chapters into project_chapter_rows so the shadow table is
    # populated for brand-new / imported / duplicated projects too.
    await upsert_chapter_rows(
        db, row.id, [c.model_dump(mode="json") for c in (project.chapters or [])]
    )
    await db.commit()
    return row


def server_llm_credentials(settings: Settings) -> dict[str, str]:
    """Server-env LLM credentials (lowest priority after client headers / user DB)."""
    return {
        "api_key": settings.deepseek_api_key,
        "base_url": settings.deepseek_base_url or "https://api.deepseek.com",
        "model": settings.deepseek_model or DEFAULT_LLM_MODEL,
        "provider": settings.llm_provider or "openai",
        "source": "server",
        "critic_api_key": settings.critic_api_key,
        "critic_base_url": settings.critic_api_base_url,
        "critic_model": settings.critic_api_model,
    }


async def resolve_llm_credentials(
    db: AsyncSession,
    user_id: str,
    settings: Settings,
) -> dict[str, str]:
    """Resolve LLM credentials: browser headers > user DB key > server env.

    The frontend stores the user's key/URL locally and sends them as X-LLM-*
    headers. Encrypted per-account keys remain a fallback for older clients.
    """
    from app.core.llm_client_override import (
        get_client_llm_override,
        merge_llm_credentials,
    )
    from app.services.settings import user_llm_credentials

    user_creds = await user_llm_credentials(db, user_id, settings)
    return merge_llm_credentials(
        override=get_client_llm_override(),
        user_creds=user_creds,
        server=server_llm_credentials(settings),
    )
