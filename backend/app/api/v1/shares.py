from datetime import datetime, timezone
from typing import Any, Dict, List

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.agent_context import _blocks_to_plain
from app.db import get_db
from app.domain.types import VnProject
from app.models import Share
from app.schemas import ShareOut

router = APIRouter(prefix="/shares", tags=["shares"])

# Public preview budget: a taste of the prose, not the whole novel.
_PREVIEW_CHARS = 700
_MAX_PREVIEW_CHAPTERS = 8


def _build_preview(project: VnProject) -> Dict[str, Any]:
    """Chapter text previews for the public landing page (read-only taste)."""
    chapter_previews: List[Dict[str, Any]] = []
    for ch in project.chapters:
        plain = (ch.blocks and _blocks_to_plain(ch.blocks, project.characters) or "").strip()
        if not plain:
            continue
        text = plain[:_PREVIEW_CHARS]
        if len(plain) > _PREVIEW_CHARS:
            text += "…"
        chapter_previews.append(
            {"chapterId": ch.id, "title": ch.title or "", "text": text}
        )
        if len(chapter_previews) >= _MAX_PREVIEW_CHAPTERS:
            break
    return {
        "chapterPreviews": chapter_previews,
        "characters": [
            {"name": c.displayName, "bio": (c.bio or "")[:120]}
            for c in project.characters
        ][:20],
        "stats": {
            "chapters": len(project.chapters),
            "words": sum(
                len(_blocks_to_plain(c.blocks, project.characters) or "") // 2
                for c in project.chapters
            ),
        },
    }


@router.get("/{token}", response_model=ShareOut)
async def get_share(token: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Share).where(Share.token == token))
    share = result.scalar_one_or_none()
    if share is None:
        raise HTTPException(status_code=404, detail="分享不存在或已失效")
    if share.expires_at is not None:
        exp = share.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp < datetime.now(timezone.utc):
            raise HTTPException(status_code=410, detail="分享已过期")
    try:
        project = VnProject.model_validate(share.data_snapshot or {})
    except Exception:  # noqa: BLE001 — a corrupt snapshot still renders the title
        project = VnProject(
            id=share.project_id,
            title=share.title_snapshot or "未命名作品",
            characters=[],
            chapters=[],
            updatedAt="",
        )
    return ShareOut(
        token=share.token,
        title=share.title_snapshot or project.title,
        project=share.data_snapshot or {},
        preview=_build_preview(project),
        created_at=share.created_at,
    )
