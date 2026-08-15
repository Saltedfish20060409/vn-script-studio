"""NovelMaster-inspired chapter batch memory for VN projects.

Adapted from necolo007/NovelMaster `chapter_memory.py` (filesystem markdown archives)
into structured PostgreSQL rows + TEXT slices.

License note: NovelMaster is MIT; this is a port of the archival idea / grouping
algorithm for in-app VnProject chapters (not a wholesale copy of the skill pack).
"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.domain.types import SceneChapter, ScriptBlock, VnProject

from .chapter_digest import digest_all_chapters

DEFAULT_SPAN = 10
# Soft cap per PG TEXT slice — keeps Agent injection / transfer chunked
SLICE_CHARS = 6000


@dataclass
class NumberedChapter:
    index: int  # 1-based order in project.chapters
    chapter: SceneChapter
    plain_text: str
    word_count: int
    speakers: List[str] = field(default_factory=list)


@dataclass
class MemoryArchiveDraft:
    label: str
    span: int
    range_from: int
    range_to: int
    word_count: int
    chapter_ids: List[str]
    spine: List[Dict[str, Any]]
    summaries: List[Dict[str, Any]]
    deltas: Dict[str, Any]
    continuity_text: str
    slices: List[Tuple[str, int, str]]  # (kind, index, content)


def slice_text(text: str, size: int = SLICE_CHARS) -> List[str]:
    """Split long markdown into PostgreSQL-friendly TEXT slices."""
    if not text:
        return [""]
    if len(text) <= size:
        return [text]
    chunks: List[str] = []
    start = 0
    n = len(text)
    while start < n:
        end = min(start + size, n)
        if end < n:
            # Prefer breaking on paragraph / line
            window = text[start:end]
            br = max(window.rfind("\n\n"), window.rfind("\n"))
            if br >= size // 3:
                end = start + br + 1
        chunks.append(text[start:end])
        start = end
    return chunks or [""]


def join_slices(parts: Sequence[str]) -> str:
    return "".join(parts)


def _blocks_to_plain(blocks: List[ScriptBlock], char_names: Dict[str, str]) -> str:
    lines: List[str] = []
    for b in blocks:
        t = b.get("type")
        if t == "narration":
            lines.append(str(b.get("text") or ""))
        elif t == "dialogue":
            who = char_names.get(str(b.get("characterId") or ""), "角色")
            lines.append(f'{who}：{b.get("text") or ""}')
        elif t == "scene":
            lines.append(f"[scene {b.get('image') or ''}]")
        elif t == "menu":
            opts = " / ".join(
                str(c.get("text") or "")
                for c in (b.get("choices") or [])
                if isinstance(c, dict)
            )
            if opts:
                lines.append(f"[选项] {opts}")
        elif t == "raw":
            code = str(b.get("code") or "").strip()
            if code:
                lines.append(code[:400])
    return "\n".join(lines)


def _word_count(text: str) -> int:
    # CJK-ish: count non-space chars; also latin words
    cjk = len(re.findall(r"[\u4e00-\u9fff]", text))
    latin = len(re.findall(r"[A-Za-z0-9]+", text))
    return cjk + latin


def _one_line_recall(text: str, max_chars: int = 140) -> str:
    clean = " ".join(text.split())
    if len(clean) <= max_chars:
        return clean
    return clean[: max_chars - 1].rstrip() + "…"


def _summarize_plain(text: str, max_chars: int = 520) -> str:
    if len(text) <= max_chars:
        return text
    head = text[: max_chars // 2].strip()
    tail = text[-max_chars // 2 :].strip()
    return f"{head}\n\n…\n\n{tail}"


def number_chapters(project: VnProject) -> List[NumberedChapter]:
    char_names = {c.id: c.displayName for c in project.characters}
    out: List[NumberedChapter] = []
    digests = {d.chapterId: d for d in digest_all_chapters(project)}
    for i, ch in enumerate(project.chapters, start=1):
        plain = _blocks_to_plain(ch.blocks, char_names)
        dig = digests.get(ch.id)
        speakers = list(dig.speakers) if dig else []
        out.append(
            NumberedChapter(
                index=i,
                chapter=ch,
                plain_text=plain,
                word_count=_word_count(plain),
                speakers=speakers,
            )
        )
    return out


def group_chapters(
    chapters: List[NumberedChapter],
    span: int,
    include_incomplete: bool = False,
) -> List[List[NumberedChapter]]:
    """Port of NovelMaster group_chapters — batch by index span."""
    if span <= 0:
        raise ValueError("span must be > 0")
    if not chapters:
        return []
    by_number = {c.index: c for c in chapters}
    first = min(by_number)
    last = max(by_number)
    start = first - ((first - 1) % span)
    groups: List[List[NumberedChapter]] = []
    while start <= last:
        end = start + span - 1
        group = [
            by_number[n] for n in range(start, end + 1) if n in by_number
        ]
        complete = len(group) == span
        if group and (complete or include_incomplete):
            groups.append(group)
        start += span
    return groups


def group_label(group: List[NumberedChapter]) -> str:
    return f"chapters_{group[0].index:03d}_{group[-1].index:03d}"


def _bullet_or_none(items: List[str]) -> List[str]:
    cleaned = [str(x).strip() for x in items if str(x).strip()]
    return cleaned if cleaned else ["（无自动检出）"]


def _build_range_deltas(
    project: VnProject,
    group: List[NumberedChapter],
) -> Dict[str, List[str]]:
    digests = {d.chapterId: d for d in digest_all_chapters(project)}
    speakers: List[str] = []
    seen_sp: set = set()
    open_hooks: List[str] = []
    for c in group:
        dig = digests.get(c.chapter.id)
        for name in c.speakers or (list(dig.speakers) if dig else []):
            if name and name not in seen_sp:
                seen_sp.add(name)
                speakers.append(name)
        if dig and dig.closeHook:
            open_hooks.append(f"{c.chapter.title}: {dig.closeHook}")
        elif dig and dig.openHook:
            open_hooks.append(f"{c.chapter.title}: {dig.openHook}")

    char_deltas = [f"出场/活跃：{'、'.join(speakers)}"] if speakers else []
    name_by_id = {ch.id: ch.displayName or ch.defineName for ch in project.characters}
    rels: List[str] = []
    for link in project.characterLinks or []:
        a = name_by_id.get(link.fromId) or link.fromId
        b = name_by_id.get(link.toId) or link.toId
        if speakers and a not in seen_sp and b not in seen_sp:
            continue
        label = (link.label or "关系").strip()
        rels.append(f"{a} → {b}（{label}）")

    power: List[str] = []
    # Heuristic: timeline events in this chapter range
    ch_ids = {c.chapter.id for c in group}
    for ev in project.timeline or []:
        if ev.chapterRef and ev.chapterRef in ch_ids:
            title = (ev.title or "").strip()
            if title:
                power.append(title + (f"：{ev.summary}" if ev.summary else ""))

    return {
        "character": char_deltas,
        "relationship": rels,
        "power_item_secret": power,
        "open_hooks": open_hooks,
    }


def build_continuity_text(
    project: VnProject,
    group: List[NumberedChapter],
) -> str:
    """Markdown continuity memory (logical doc); stored as TEXT slices in PG."""
    bible = project.bible
    deltas = _build_range_deltas(project, group)
    lines = [
        f"# Continuity Memory {group[0].index:03d}-{group[-1].index:03d}",
        "",
        f"Novel: {project.title}",
        f"Chapter range: {group[0].index:03d}-{group[-1].index:03d}",
        f"Total words in range: {sum(c.word_count for c in group)}",
        "",
        "## Read Before Writing Later Chapters",
        "",
        "- Compact historical layer for long-form continuation (NovelMaster-style).",
        "- Prefer newer chapter digests / bible if this conflicts.",
        "",
        "## Range Spine",
        "",
    ]
    for c in group:
        dig_note = ""
        lines.append(
            f"- Chapter {c.index:03d} `{c.chapter.title}`: "
            f"{_one_line_recall(c.plain_text)}{dig_note}"
        )

    def _section(title: str, items: List[str]) -> None:
        lines.append("")
        lines.append(f"### {title}")
        lines.append("")
        for bullet in _bullet_or_none(items):
            lines.append(f"- {bullet}")

    lines.extend(["", "## Character And Plot Memory To Preserve", ""])
    _section("Character deltas", deltas["character"])
    _section("Relationship deltas", deltas["relationship"])
    _section("Power / item / secret deltas", deltas["power_item_secret"])
    _section("Open hooks after this range", deltas["open_hooks"])

    if bible:
        snap_parts = []
        if bible.world:
            snap_parts.append(f"世界观: {bible.world[:800]}")
        if bible.background:
            snap_parts.append(f"背景: {bible.background[:600]}")
        if bible.outline:
            snap_parts.append(f"大纲: {bible.outline[:1000]}")
        if bible.themes:
            snap_parts.append(f"主题: {bible.themes[:400]}")
        if snap_parts:
            lines.extend(
                [
                    "",
                    "## Current Rolling Context Snapshot",
                    "",
                    "```markdown",
                    "\n".join(snap_parts),
                    "```",
                    "",
                ]
            )

    return "\n".join(lines)


def build_archive_draft(
    project: VnProject,
    group: List[NumberedChapter],
    span: int,
) -> MemoryArchiveDraft:
    digests = {d.chapterId: d for d in digest_all_chapters(project)}
    spine = []
    summaries = []
    for c in group:
        dig = digests.get(c.chapter.id)
        spine.append(
            {
                "chapterId": c.chapter.id,
                "index": c.index,
                "title": c.chapter.title,
                "recall": _one_line_recall(
                    dig.beatSummary if dig and dig.beatSummary else c.plain_text
                ),
            }
        )
        summaries.append(
            {
                "chapterId": c.chapter.id,
                "index": c.index,
                "title": c.chapter.title,
                "wordCount": c.word_count,
                "speakers": c.speakers
                or (list(dig.speakers) if dig else []),
                "quickRecall": _summarize_plain(
                    dig.beatSummary if dig and dig.beatSummary else c.plain_text
                ),
                "openHook": dig.openHook if dig else "",
                "closeHook": dig.closeHook if dig else "",
            }
        )

    continuity = build_continuity_text(project, group)
    cont_slices = slice_text(continuity, SLICE_CHARS)
    slices: List[Tuple[str, int, str]] = [
        ("continuity", i, chunk) for i, chunk in enumerate(cont_slices)
    ]
    deltas = _build_range_deltas(project, group)

    return MemoryArchiveDraft(
        label=group_label(group),
        span=span,
        range_from=group[0].index,
        range_to=group[-1].index,
        word_count=sum(c.word_count for c in group),
        chapter_ids=[c.chapter.id for c in group],
        spine=spine,
        summaries=summaries,
        deltas=deltas,
        continuity_text=continuity,
        slices=slices,
    )


def build_all_archive_drafts(
    project: VnProject,
    span: int = DEFAULT_SPAN,
    include_incomplete: bool = False,
) -> List[MemoryArchiveDraft]:
    chapters = number_chapters(project)
    groups = group_chapters(
        chapters, span, include_incomplete=include_incomplete
    )
    return [build_archive_draft(project, g, span) for g in groups]


def format_memory_for_agent(
    continuity_text: str,
    spine: Optional[List[Dict[str, Any]]] = None,
    max_chars: int = 3200,
) -> str:
    """Compact injection block for Agent context."""
    parts: List[str] = ["## 长程章节记忆（NovelMaster 风格归档）", ""]
    if spine:
        parts.append("### 本段脊骨")
        for item in spine[-12:]:
            parts.append(
                f"- Ch{item.get('index')} `{item.get('title')}`: {item.get('recall')}"
            )
        parts.append("")
    body = continuity_text.strip()
    if len(body) > max_chars:
        # Prefer spine + head/tail of continuity
        half = max_chars // 2 - 20
        body = f"{body[:half]}\n…(记忆切片中间省略)…\n{body[-half:]}"
    parts.append(body)
    return "\n".join(parts)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
