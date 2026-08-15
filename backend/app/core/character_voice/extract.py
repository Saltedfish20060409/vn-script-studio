"""Extract dialogue candidates for a character from project chapters."""

from __future__ import annotations

from typing import Any, Dict, List

from app.core.character_voice.corpus import find_character
from app.domain.types import VnProject


def extract_dialogue_candidates(
    project: VnProject,
    *,
    character_id: str,
    limit: int = 40,
) -> Dict[str, Any]:
    char = find_character(project, character_id)
    name_by_id = {c.id: c.displayName for c in (project.characters or [])}
    candidates: List[Dict[str, Any]] = []

    for ch in project.chapters or []:
        blocks = ch.blocks or []
        for i, b in enumerate(blocks):
            if not isinstance(b, dict):
                continue
            if b.get("type") != "dialogue":
                continue
            if str(b.get("characterId") or "") != character_id:
                continue
            text = str(b.get("text") or "").strip()
            if not text:
                continue
            # Context: previous other dialogue or narration (short)
            ctx_lines: List[Dict[str, str]] = []
            for j in range(max(0, i - 3), i):
                prev = blocks[j]
                if not isinstance(prev, dict):
                    continue
                if prev.get("type") == "dialogue":
                    pid = str(prev.get("characterId") or "")
                    ptext = str(prev.get("text") or "").strip()
                    if not ptext:
                        continue
                    speaker = "self" if pid == character_id else "other"
                    if speaker == "other":
                        ctx_lines.append(
                            {
                                "speaker": "other",
                                "text": ptext,
                                "name": name_by_id.get(pid, "对方"),
                            }
                        )
                elif prev.get("type") == "narration":
                    ntext = str(prev.get("text") or "").strip()
                    if ntext and len(ntext) < 80:
                        ctx_lines.append({"speaker": "other", "text": f"（旁白）{ntext}"})
            lines = ctx_lines[-2:] + [{"speaker": "self", "text": text}]
            candidates.append(
                {
                    "chapterId": ch.id,
                    "chapterTitle": ch.title,
                    "blockIndex": i,
                    "scenario": f"script:{ch.id}",
                    "scenarioLabel": f"剧本·{ch.title or ch.id}",
                    "lines": lines,
                    "preview": text[:80],
                }
            )
            if len(candidates) >= limit:
                break
        if len(candidates) >= limit:
            break

    return {
        "characterId": character_id,
        "displayName": char.displayName,
        "candidates": candidates,
        "count": len(candidates),
    }


def format_script_anchors_for_prompt(
    project: VnProject,
    character_id: str,
    *,
    limit: int = 4,
    max_chars: int = 700,
) -> str:
    """Read-only chapter dialogue anchors for generation (do not copy verbatim)."""
    try:
        data = extract_dialogue_candidates(project, character_id=character_id, limit=80)
    except KeyError:
        return ""
    cands = list(data.get("candidates") or [])
    if not cands:
        return ""
    picked = cands[-limit:] if len(cands) > limit else cands
    parts: List[str] = [
        "  【剧本锚点】（已写对白，对齐用词与人设习惯；禁止照抄原文）"
    ]
    used = len(parts[0])
    for row in picked:
        preview = str(row.get("preview") or "").strip()
        if not preview:
            lines = row.get("lines") or []
            self_lines = [
                str(ln.get("text") or "").strip()
                for ln in lines
                if isinstance(ln, dict) and str(ln.get("speaker") or "") == "self"
            ]
            preview = next((t for t in self_lines if t), "")
        if not preview:
            continue
        title = str(row.get("chapterTitle") or row.get("chapterId") or "章")
        bit = f"  · 〔{title}〕{preview}"
        if used + len(bit) > max_chars:
            break
        parts.append(bit)
        used += len(bit)
    return "\n".join(parts) if len(parts) > 1 else ""
