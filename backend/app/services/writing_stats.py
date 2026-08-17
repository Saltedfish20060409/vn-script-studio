"""Writing stats — per-chapter metrics + per-day activity tracking.

Word counting follows the same heuristic as novel_memory (CJK chars count
individually, latin words count as one): stable across the project so the
dashboard totals match memory-archive numbers.
"""

from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.domain.types import VnProject

_WORD_RE_CJK = re.compile(r"[\u4e00-\u9fff]")
_WORD_RE_LATIN = re.compile(r"[A-Za-z0-9]+")


def count_words(text: str) -> int:
    """Count words in script text (CJK chars + latin words)."""
    return len(_WORD_RE_CJK.findall(text)) + len(_WORD_RE_LATIN.findall(text))


def count_blocks_words(blocks: list[dict]) -> int:
    """Count words across script blocks (dialogue/narration text + raw code).

    Character names are not included — the count focuses on prose/dialogue
    content, matching how a writer thinks about "words written".
    """
    total = 0
    for b in blocks:
        btype = b.get("type")
        if btype in ("narration", "dialogue"):
            total += count_words(str(b.get("text") or ""))
        elif btype == "raw":
            total += count_words(str(b.get("code") or ""))
        elif btype == "menu":
            for c in b.get("choices") or []:
                if isinstance(c, dict):
                    total += count_words(str(c.get("text") or ""))
    return total


def chapter_metrics(vn: VnProject) -> List[Dict[str, Any]]:
    """Per-chapter word/line/speaker metrics for the stats panel."""
    characters = list(vn.characters or [])
    char_names = {c.id: c.displayName for c in characters}
    out: List[Dict[str, Any]] = []
    for idx, ch in enumerate(vn.chapters or [], start=1):
        blocks = list(ch.blocks or [])
        words = count_blocks_words(blocks)
        dialogue_words = 0
        line_count = 0
        speakers: set = set()
        for b in blocks:
            btype = b.get("type")
            if btype == "dialogue":
                dialogue_words += count_words(str(b.get("text") or ""))
                cid = b.get("characterId")
                name = char_names.get(cid, cid)
                if name:
                    speakers.add(name)
            if btype in ("narration", "dialogue"):
                line_count += 1
        out.append(
            {
                "index": idx,
                "id": ch.id,
                "title": ch.title or f"第{idx}章",
                "words": words,
                "lines": line_count,
                "dialogueWords": dialogue_words,
                "dialogueRatio": round(dialogue_words / words, 3) if words else 0,
                "speakers": sorted(s for s in speakers if s),
            }
        )
    return out


async def record_activity(
    db: AsyncSession,
    project_id: str,
    *,
    previous_words: int,
    current_words: int,
    when: Optional[datetime] = None,
) -> None:
    """Add today's word delta to writing_activity (upsert per project+date)."""
    when = when or datetime.now(timezone.utc)
    date_key = when.date().isoformat()
    delta = current_words - previous_words
    if delta == 0:
        return
    from sqlalchemy.dialects.postgresql import insert as pg_insert

    from app.models import WritingActivity

    stmt = pg_insert(WritingActivity).values(
        id=f"{project_id}:{date_key}",
        project_id=project_id,
        activity_date=date_key,
        words_added=delta if delta > 0 else 0,
        words_removed=-delta if delta < 0 else 0,
        edits=1,
        updated_at=when,
    )
    stmt = stmt.on_conflict_do_update(
        index_elements=[WritingActivity.project_id, WritingActivity.activity_date],
        set_={
            "words_added": WritingActivity.words_added
            + (delta if delta > 0 else 0),
            "words_removed": WritingActivity.words_removed
            + (-delta if delta < 0 else 0),
            "edits": WritingActivity.edits + 1,
            "updated_at": when,
        },
    )
    await db.execute(stmt)


async def recent_activity(
    db: AsyncSession,
    project_id: str,
    days: int = 30,
) -> List[Dict[str, Any]]:
    """Daily deltas for the heatmap, oldest → newest."""
    from app.models import WritingActivity

    start = (datetime.now(timezone.utc) - timedelta(days=days - 1)).date().isoformat()
    res = await db.execute(
        select(WritingActivity)
        .where(
            WritingActivity.project_id == project_id,
            WritingActivity.activity_date >= start,
        )
        .order_by(WritingActivity.activity_date.asc())
    )
    return [
        {
            "date": row.activity_date,
            "added": row.words_added,
            "removed": row.words_removed,
            "net": row.words_added - row.words_removed,
            "edits": row.edits,
        }
        for row in res.scalars().all()
    ]
