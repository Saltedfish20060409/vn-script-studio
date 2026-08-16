from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Optional

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
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
    payload["updatedAt"] = row.updated_at.isoformat()
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
    chapter_ids: List[str],
    sections: List[str],
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
        merged_chapters: List[Any] = []
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
    vn: Optional[VnProject] = None,
) -> Project:
    if vn is not None:
        project = normalize_project(vn)
    elif from_demo:
        project = create_demo_project()
        project = normalize_project(
            {**project_to_dict(project), "id": uid("proj")}
        )
    else:
        project = empty_project(title or "未命名剧本")

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
    return row


def server_llm_credentials(settings: Settings) -> dict[str, str]:
    """LLM credentials come only from server env — never from the client."""
    return {
        "api_key": settings.deepseek_api_key,
        "base_url": settings.deepseek_base_url or "https://api.deepseek.com",
        "model": settings.deepseek_model or "deepseek-chat",
        "provider": settings.llm_provider or "openai",
    }
