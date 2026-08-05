"""Persist NovelMaster-style chapter memory archives into PostgreSQL."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from sqlalchemy import delete, select, update
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm import selectinload

from app.core.novel_memory import (
    DEFAULT_SPAN,
    build_all_archive_drafts,
    format_memory_for_agent,
    join_slices,
    utc_now,
)
from app.domain.types import VnProject
from app.models.tables import ChapterMemoryArchive, ChapterMemorySlice


async def archive_project_memory(
    db: AsyncSession,
    project_id: str,
    project: VnProject,
    *,
    span: int = DEFAULT_SPAN,
    include_incomplete: bool = False,
) -> Dict[str, Any]:
    """Rebuild span archives for a project (upsert by label)."""
    drafts = build_all_archive_drafts(
        project, span=span, include_incomplete=include_incomplete
    )
    if not drafts:
        return {
            "archives": [],
            "count": 0,
            "span": span,
            "latestLabel": None,
        }

    # Clear is_latest flags
    await db.execute(
        update(ChapterMemoryArchive)
        .where(ChapterMemoryArchive.project_id == project_id)
        .values(is_latest=False)
    )

    saved: List[ChapterMemoryArchive] = []
    for i, draft in enumerate(drafts):
        is_latest = i == len(drafts) - 1
        result = await db.execute(
            select(ChapterMemoryArchive).where(
                ChapterMemoryArchive.project_id == project_id,
                ChapterMemoryArchive.label == draft.label,
            )
        )
        row = result.scalar_one_or_none()
        now = utc_now()
        if row is None:
            row = ChapterMemoryArchive(
                project_id=project_id,
                label=draft.label,
            )
            db.add(row)

        row.span = draft.span
        row.range_from = draft.range_from
        row.range_to = draft.range_to
        row.word_count = draft.word_count
        row.chapter_ids = list(draft.chapter_ids)
        row.spine = list(draft.spine)
        row.summaries = list(draft.summaries)
        row.deltas = dict(draft.deltas)
        row.is_latest = is_latest
        row.updated_at = now
        await db.flush()

        # Replace slices for this archive
        await db.execute(
            delete(ChapterMemorySlice).where(
                ChapterMemorySlice.archive_id == row.id
            )
        )
        for kind, idx, content in draft.slices:
            db.add(
                ChapterMemorySlice(
                    archive_id=row.id,
                    kind=kind,
                    slice_index=idx,
                    content=content,
                    char_count=len(content),
                )
            )
        saved.append(row)

    await db.commit()
    for row in saved:
        await db.refresh(row)

    return {
        "archives": [_archive_summary(r) for r in saved],
        "count": len(saved),
        "span": span,
        "latestLabel": saved[-1].label if saved else None,
    }


async def list_memory_archives(
    db: AsyncSession, project_id: str
) -> List[Dict[str, Any]]:
    result = await db.execute(
        select(ChapterMemoryArchive)
        .where(ChapterMemoryArchive.project_id == project_id)
        .order_by(ChapterMemoryArchive.range_from.asc())
    )
    rows = result.scalars().all()
    return [_archive_summary(r) for r in rows]


async def get_archive_detail(
    db: AsyncSession, project_id: str, archive_id: str
) -> Optional[Dict[str, Any]]:
    result = await db.execute(
        select(ChapterMemoryArchive)
        .options(selectinload(ChapterMemoryArchive.slices))
        .where(
            ChapterMemoryArchive.id == archive_id,
            ChapterMemoryArchive.project_id == project_id,
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        return None
    slices = sorted(row.slices, key=lambda s: (s.kind, s.slice_index))
    continuity = join_slices(
        s.content for s in slices if s.kind == "continuity"
    )
    return {
        **_archive_summary(row),
        "spine": row.spine or [],
        "summaries": row.summaries or [],
        "deltas": row.deltas or {},
        "chapterIds": row.chapter_ids or [],
        "continuityText": continuity,
        "slices": [
            {
                "id": s.id,
                "kind": s.kind,
                "sliceIndex": s.slice_index,
                "charCount": s.char_count,
                "content": s.content,
            }
            for s in slices
        ],
    }


async def get_latest_continuity(
    db: AsyncSession, project_id: str
) -> Optional[Dict[str, Any]]:
    result = await db.execute(
        select(ChapterMemoryArchive)
        .options(selectinload(ChapterMemoryArchive.slices))
        .where(
            ChapterMemoryArchive.project_id == project_id,
            ChapterMemoryArchive.is_latest.is_(True),
        )
        .limit(1)
    )
    row = result.scalar_one_or_none()
    if row is None:
        # Fallback: highest range_to
        result = await db.execute(
            select(ChapterMemoryArchive)
            .options(selectinload(ChapterMemoryArchive.slices))
            .where(ChapterMemoryArchive.project_id == project_id)
            .order_by(ChapterMemoryArchive.range_to.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
    if not row:
        return None
    continuity = join_slices(
        s.content
        for s in sorted(row.slices, key=lambda x: x.slice_index)
        if s.kind == "continuity"
    )
    return {
        "archiveId": row.id,
        "label": row.label,
        "rangeFrom": row.range_from,
        "rangeTo": row.range_to,
        "spine": row.spine or [],
        "continuityText": continuity,
        "agentBlock": format_memory_for_agent(continuity, row.spine or []),
    }


def _archive_summary(row: ChapterMemoryArchive) -> Dict[str, Any]:
    return {
        "id": row.id,
        "label": row.label,
        "span": row.span,
        "rangeFrom": row.range_from,
        "rangeTo": row.range_to,
        "wordCount": row.word_count,
        "isLatest": row.is_latest,
        "updatedAt": row.updated_at.isoformat() if row.updated_at else None,
    }
