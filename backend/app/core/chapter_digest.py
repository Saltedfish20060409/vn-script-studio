"""Ported from packages/core/src/chapterDigest.ts"""
from __future__ import annotations

import json
from dataclasses import dataclass, field
from typing import Dict, List, Optional

from app.domain.types import Character, SceneChapter, ScriptBlock, VnProject

_BASE36 = "0123456789abcdefghijklmnopqrstuvwxyz"


def _to_base36(n: int) -> str:
    if n == 0:
        return "0"
    digits: List[str] = []
    while n:
        n, r = divmod(n, 36)
        digits.append(_BASE36[r])
    return "".join(reversed(digits))


@dataclass
class ChapterDigest:
    chapterId: str
    title: str
    hash: str
    synopsis: str
    speakers: List[str]
    # Extractive beat summary for long-form index
    beatSummary: str
    openHook: str
    closeHook: str


def _line_from_block(b: ScriptBlock, char_map: Dict[str, Character]) -> Optional[str]:
    btype = b.get("type")
    if btype == "narration":
        return f"旁白: {b['text']}"
    if btype == "dialogue":
        ch = char_map.get(b.get("characterId"))
        name = ch.displayName if ch else b.get("characterId")
        return f"{name}: {b['text']}"
    if btype == "menu":
        return f"选项: {' / '.join(c['text'] for c in b.get('choices', []))}"
    if btype == "raw":
        code = b.get("code", "")
        return code if code.strip() else None
    if btype == "scene":
        return f"[scene {b['image']}]"
    if btype == "label":
        return f"[label {b['name']}]"
    return None


def _collect_lines(chapter: SceneChapter, characters: List[Character]):
    char_map = {c.id: c for c in characters}
    lines: List[str] = []
    speakers: List[str] = []
    seen_speakers: set = set()
    for b in chapter.blocks:
        if b.get("type") == "dialogue":
            ch = char_map.get(b.get("characterId"))
            name = ch.displayName if ch else b.get("characterId")
            if name not in seen_speakers:
                seen_speakers.add(name)
                speakers.append(name)
        line = _line_from_block(b, char_map)
        if line:
            lines.append(line)
    return lines, speakers


def _hash_str(s: str) -> str:
    h = 2166136261
    for ch in s:
        h = (h ^ ord(ch)) & 0xFFFFFFFF
        h = (h * 16777619) & 0xFFFFFFFF
    return _to_base36(h)


def chapter_content_hash(chapter: SceneChapter) -> str:
    """Cheap content fingerprint for cache invalidation"""
    n = len(chapter.blocks)
    tail = "|".join(
        json.dumps(b, ensure_ascii=False, separators=(",", ":")) for b in chapter.blocks[-3:]
    )
    syn = chapter.synopsis or ""
    return f"{chapter.id}:{n}:{len(syn)}:{_hash_str(tail + syn + chapter.title)}"


def _clip(s: str, n: int) -> str:
    t = " ".join(s.split())
    if len(t) <= n:
        return t
    return f"{t[: n - 1]}…"


def make_chapter_digest(chapter: SceneChapter, characters: List[Character]) -> ChapterDigest:
    """Local extractive chapter digest — no server / no LLM.

    Uses synopsis + open/close hooks + speaker list.
    """
    lines, speakers = _collect_lines(chapter, characters)
    open_ = " / ".join(lines[:3])
    close = " / ".join(lines[-4:]) if lines else ""
    beat_parts = [
        p
        for p in [
            (chapter.synopsis or "").strip(),
            f"出场: {'、'.join(speakers)}" if speakers else "",
            f"起: {_clip(open_, 160)}" if open_ else "",
            f"迄: {_clip(close, 200)}" if close and close != open_ else "",
        ]
        if p
    ]

    return ChapterDigest(
        chapterId=chapter.id,
        title=chapter.title,
        hash=chapter_content_hash(chapter),
        synopsis=(chapter.synopsis or "").strip(),
        speakers=speakers,
        beatSummary=" · ".join(beat_parts) or "（空章）",
        openHook=_clip(open_, 120),
        closeHook=_clip(close, 160),
    )


def digest_all_chapters(project: VnProject) -> List[ChapterDigest]:
    return [make_chapter_digest(ch, project.characters) for ch in project.chapters]


def _score_text(hay: str, tokens: List[str]) -> int:
    if not tokens or not hay:
        return 0
    h = hay.lower()
    s = 0
    for tok in tokens:
        if tok.lower() in h:
            s += 3 if len(tok) >= 3 else 2
    return s


@dataclass
class ChapterDigestIndex:
    indexLines: List[str]
    relatedBlocks: List[str]
    included: List[str]


def format_chapter_digest_index(
    digests: List[ChapterDigest],
    focus_id: Optional[str] = None,
    tokens: Optional[List[str]] = None,
    max_related_excerpts: Optional[int] = None,
) -> ChapterDigestIndex:
    """Format other-chapter digests for Agent context (prefer digest over raw dump)."""
    tokens = tokens or []
    included = [f"章摘要×{len(digests)}"]
    index_lines = [
        f"{i + 1}. {d.title}{'◀当前' if d.chapterId == focus_id else ''} — {_clip(d.beatSummary, 100)}"
        for i, d in enumerate(digests)
    ]

    ranked = sorted(
        (
            (d, _score_text(f"{d.title} {d.synopsis} {d.beatSummary} {' '.join(d.speakers)}", tokens))
            for d in digests
            if d.chapterId != focus_id
        ),
        key=lambda pair: pair[1],
        reverse=True,
    )

    related_blocks: List[str] = []
    max_ex = max_related_excerpts if max_related_excerpts is not None else 3
    excerpted = 0
    for d, score in ranked:
        if score >= 4 and excerpted < max_ex:
            related_blocks.append(
                f"### {d.title}（摘要 score={score}）\n{d.beatSummary}\n迄钩子: {d.closeHook or '（无）'}"
            )
            included.append(f"摘要章:{d.title}")
            excerpted += 1
        else:
            related_blocks.append(f"### {d.title}\n{_clip(d.beatSummary, 140)}")

    return ChapterDigestIndex(indexLines=index_lines, relatedBlocks=related_blocks, included=included)
