"""Deterministic snapshot diff — chapter/character/setting level, no LLM.

Compares two project payloads (a stored snapshot vs another snapshot or the
current state) and reports what changed: which chapters were added/removed/
edited (with word & dialogue-line deltas), which characters appeared or
disappeared, and how many locations/timeline events changed.
"""

from __future__ import annotations

from typing import Any, Dict, List

from app.core.snapshots import decode_snapshot_payload
from app.domain.types import Character, SceneChapter, VnProject


def _as_project(payload: Dict[str, Any]) -> VnProject:
    # model_validate tolerates extra/missing optional fields.
    return VnProject.model_validate(payload)


def _chapter_words(ch: SceneChapter) -> int:
    from app.services.writing_stats import count_words

    parts: List[str] = []
    for b in ch.blocks:
        if b.get("type") == "narration":
            parts.append(str(b.get("text") or ""))
        elif b.get("type") == "dialogue":
            parts.append(str(b.get("text") or ""))
        elif b.get("type") == "raw":
            parts.append(str(b.get("code") or ""))
    return count_words("\n".join(parts))


def _chapter_lines(ch: SceneChapter) -> int:
    """Dialogue lines (top-level + menu inline blocks)."""
    count = 0

    def walk(blocks: List[Dict[str, Any]]) -> None:
        nonlocal count
        for b in blocks:
            if b.get("type") == "dialogue":
                count += 1
            elif b.get("type") == "menu":
                for c in b.get("choices") or []:
                    walk(c.get("blocks") or [])

    walk(ch.blocks)
    return count


def _chapter_meta(ch: SceneChapter) -> Dict[str, Any]:
    return {
        "chapterId": ch.id,
        "title": ch.title or "",
        "words": _chapter_words(ch),
        "lines": _chapter_lines(ch),
    }


def compare_snapshots(
    from_payload: Dict[str, Any],
    to_payload: Dict[str, Any],
) -> Dict[str, Any]:
    """Diff two snapshot payloads (already decoded dicts)."""
    a = _as_project(decode_snapshot_payload(from_payload))
    b = _as_project(decode_snapshot_payload(to_payload))

    a_ch = {c.id: c for c in a.chapters}
    b_ch = {c.id: c for c in b.chapters}

    chapters: List[Dict[str, Any]] = []
    for cid in sorted(set(a_ch) | set(b_ch)):
        if cid not in b_ch:
            m = _chapter_meta(a_ch[cid])
            chapters.append(
                {**m, "status": "removed", "wordsFrom": m["words"], "wordsTo": 0,
                 "linesFrom": m["lines"], "linesTo": 0}
            )
        elif cid not in a_ch:
            m = _chapter_meta(b_ch[cid])
            chapters.append(
                {**m, "status": "added", "wordsFrom": 0, "wordsTo": m["words"],
                 "linesFrom": 0, "linesTo": m["lines"]}
            )
        else:
            ma = _chapter_meta(a_ch[cid])
            mb = _chapter_meta(b_ch[cid])
            changed = ma["words"] != mb["words"] or ma["lines"] != mb["lines"]
            chapters.append(
                {
                    **mb,
                    "status": "changed" if changed else "same",
                    "wordsFrom": ma["words"],
                    "wordsTo": mb["words"],
                    "linesFrom": ma["lines"],
                    "linesTo": mb["lines"],
                }
            )

    def char_key(c: Character) -> str:
        return c.id or c.defineName

    a_chars = {char_key(c): c.displayName for c in a.characters}
    b_chars = {char_key(c): c.displayName for c in b.characters}
    characters: List[Dict[str, Any]] = []
    for cid in sorted(set(a_chars) | set(b_chars)):
        if cid not in b_chars:
            characters.append({"id": cid, "name": a_chars[cid], "status": "removed"})
        elif cid not in a_chars:
            characters.append({"id": cid, "name": b_chars[cid], "status": "added"})
        else:
            characters.append({"id": cid, "name": b_chars[cid], "status": "same"})

    a_locs = {l.id for l in a.locations or []}
    b_locs = {l.id for l in b.locations or []}
    a_tl = {t.id for t in a.timeline or []}
    b_tl = {t.id for t in b.timeline or []}

    changed = [c for c in chapters if c["status"] != "same"]
    added_chars = [c for c in characters if c["status"] == "added"]
    removed_chars = [c for c in characters if c["status"] == "removed"]
    loc_delta = len(a_locs ^ b_locs)
    tl_delta = len(a_tl ^ b_tl)

    summary_parts: List[str] = []
    if not changed and not added_chars and not removed_chars and not loc_delta and not tl_delta:
        summary_parts.append("两个版本内容一致")
    else:
        if changed:
            summary_parts.append(f"{len(changed)} 章有变化")
        if added_chars:
            summary_parts.append(f"新增角色 {len(added_chars)} 名")
        if removed_chars:
            summary_parts.append(f"移除角色 {len(removed_chars)} 名")
        if loc_delta:
            summary_parts.append(f"地点变化 {loc_delta} 处")
        if tl_delta:
            summary_parts.append(f"时间线变化 {tl_delta} 条")

    return {
        "summary": "；".join(summary_parts) + "。",
        "chapters": chapters,
        "characters": characters,
        "locations": {
            "added": len(b_locs - a_locs),
            "removed": len(a_locs - b_locs),
            "changed": len(a_locs & b_locs),
        },
        "timeline": {
            "added": len(b_tl - a_tl),
            "removed": len(a_tl - b_tl),
            "changed": len(a_tl & b_tl),
        },
        "changedChapters": len(changed),
    }
