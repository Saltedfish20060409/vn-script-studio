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


def count_chapter_words(ch: Any) -> int:
    """一章的"写了多少字"。

    **优先数 `prose`（大白话正文），没有正文才数 script blocks。**
    为什么不是两者相加：blocks 通常是由 prose 生成出来的脚本，加一起会把同一段内容
    数两遍。而反过来只数 blocks 的话，纯用正文写作的作者（网文/轻小说的主流用法）
    会被算成 0 字——日更热力图、字数统计、章节回炉的对比全都跟着失真（实测确认过）。
    """
    prose = str(getattr(ch, "prose", None) or "")
    if prose.strip():
        return count_words(prose)
    blocks = list(getattr(ch, "blocks", None) or [])
    return count_blocks_words(blocks)


def chapter_metrics(vn: VnProject) -> List[Dict[str, Any]]:
    """Per-chapter word/line/speaker metrics for the stats panel."""
    characters = list(vn.characters or [])
    char_names = {c.id: c.displayName for c in characters}
    out: List[Dict[str, Any]] = []
    for idx, ch in enumerate(vn.chapters or [], start=1):
        blocks = list(ch.blocks or [])
        words = count_chapter_words(ch)
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
                "volumeId": getattr(ch, "volumeId", None) or "",
            }
        )
    return out


def volume_metrics(vn: VnProject) -> List[Dict[str, Any]]:
    """每卷的进度汇总（轻小说/网文按卷连载时最常看的一组数）。

    只汇总、不重复实现计数：数据源就是 `chapter_metrics`，所以面板与卷头数字永远一致。
    """
    volumes = list(vn.volumes or [])
    if not volumes:
        return []
    metrics = {m["id"]: m for m in chapter_metrics(vn)}
    out: List[Dict[str, Any]] = []
    for idx, vol in enumerate(volumes, start=1):
        ids = [ch.id for ch in (vn.chapters or []) if (getattr(ch, "volumeId", None) or "") == vol.id]
        words = sum(int(metrics.get(cid, {}).get("words") or 0) for cid in ids)
        out.append(
            {
                "id": vol.id,
                "title": vol.title or f"第{idx}卷",
                "index": idx,
                "note": vol.note or "",
                "chapters": len(ids),
                "words": words,
                "avgChapterWords": round(words / len(ids)) if ids else 0,
                "chapterIds": ids,
            }
        )
    # 未归卷的章节单列一档，界面上显示为「未分卷」
    loose = [ch.id for ch in (vn.chapters or []) if not (getattr(ch, "volumeId", None) or "")]
    loose_words = sum(int(metrics.get(cid, {}).get("words") or 0) for cid in loose)
    out.append(
        {
            "id": "",
            "title": "未分卷",
            "index": len(volumes) + 1,
            "note": "",
            "chapters": len(loose),
            "words": loose_words,
            "avgChapterWords": round(loose_words / len(loose)) if loose else 0,
            "chapterIds": loose,
        }
    )
    return out


#: 偏移量的现实范围（UTC-12..UTC+14 之外没有真实时区）；越界一律夹住，
#: 免得一个乱填的请求头把某一章的字记到明年去。
MIN_TZ_OFFSET_MINUTES = -12 * 60
MAX_TZ_OFFSET_MINUTES = 14 * 60


def activity_date_key(when: datetime, tz_offset_minutes: int = 0) -> str:
    """把一个时刻换算成"作者当地的哪一天"（YYYY-MM-DD）。

    单独抽出来是为了能被直接单测：日期口径错一天，界面上表现为"今天写的字不见了"，
    而那种 bug 在集成测试里只能靠构造时间点才能发现。
    """
    try:
        offset = int(tz_offset_minutes or 0)
    except (TypeError, ValueError):
        offset = 0
    offset = max(MIN_TZ_OFFSET_MINUTES, min(MAX_TZ_OFFSET_MINUTES, offset))
    if when.tzinfo is None:
        when = when.replace(tzinfo=timezone.utc)
    return (when.astimezone(timezone.utc) + timedelta(minutes=offset)).date().isoformat()


async def record_activity(
    db: AsyncSession,
    project_id: str,
    *,
    previous_words: int,
    current_words: int,
    when: Optional[datetime] = None,
    tz_offset_minutes: int = 0,
) -> None:
    """Add today's word delta to writing_activity (upsert per project+date).

    ``tz_offset_minutes`` = 作者所在地相对 UTC 的分钟偏移（东八区 = +480）。
    记录用的是**作者当地日期**：否则东八区用户在本地 00:00–08:00 写的字会落到
    前一天，「今日净增」在早上永远是 0。取不到偏移时退回 UTC（老客户端行为不变）。
    """
    when = when or datetime.now(timezone.utc)
    date_key = activity_date_key(when, tz_offset_minutes)
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
