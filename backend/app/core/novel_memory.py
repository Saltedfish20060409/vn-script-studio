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
    # 记忆存档喂给模型的"这一章正文"必须走唯一口径（正文优先、空才回落脚本块）：
    # 只读 blocks 会把整本正文档写作的作品记成空的 —— 那正是"长篇失忆"的源头。
    # 导入放在函数里：novel_memory ← longform_memory ← agent_context 这条链在模块级会成环。
    from app.core.agent_context import chapter_plain

    out: List[NumberedChapter] = []
    digests = {d.chapterId: d for d in digest_all_chapters(project)}
    for i, ch in enumerate(project.chapters, start=1):
        plain = chapter_plain(ch, project.characters)
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


def format_archive_world_projection(
    project: VnProject,
    group: List[NumberedChapter],
    *,
    limit: int = 1800,
) -> str:
    """WorldState hard anchors as of this archive span's last chapter."""
    if not group:
        return ""
    from app.core.pipeline.ledger import get_ledger
    from app.core.world_state import format_world_constraints, get_world_state

    world = get_world_state(get_ledger(project))
    if not (world.get("facts") or world.get("eventFrames")):
        return ""
    return format_world_constraints(
        world,
        chapters=project.chapters,
        focus_chapter_id=group[-1].chapter.id,
        foreshadows=None,
        limit=limit,
    )


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
        "- WorldState hard anchors below outrank soft NLP digests / bible snapshots.",
        "- Prefer newer chapter digests / bible only when they do not contradict hard anchors.",
        "",
    ]
    ws_block = format_archive_world_projection(project, group)
    if ws_block:
        lines.extend(
            [
                "## WorldState Hard Anchors（本段结束时）",
                "",
                ws_block,
                "",
            ]
        )
    lines.extend(
        [
            "## Range Spine",
            "",
        ]
    )
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


def _section_rank(title: str) -> int:
    """越小越该留下。硬锚点与增量承重且难复原；设定快照上下文里已有 bible。"""
    low = (title or "").lower()
    if "worldstate" in low or "硬锚" in title:
        return 0
    if any(
        k in low
        for k in (
            "character and plot",
            "character deltas",
            "relationship deltas",
            "power / item",
            "open hooks",
            "to preserve",
        )
    ):
        return 1
    if "spine" in low or "脊骨" in (title or ""):
        return 2
    if "snapshot" in low or "rolling context" in low:
        return 4
    if "read before" in low:
        return 5
    return 3


def _split_markdown_sections(text: str) -> List[Tuple[str, str]]:
    """按二级标题切开。没有标题时整段当作一块，避免再从中间对切。"""
    raw = (text or "").strip()
    if not raw:
        return []
    lines = raw.splitlines()
    chunks: List[Tuple[str, List[str]]] = []
    title = ""
    buf: List[str] = []
    saw_heading = False
    for line in lines:
        if line.startswith("## "):
            saw_heading = True
            if title or buf:
                chunks.append((title, buf))
            title = line[3:].strip()
            buf = [line]
        else:
            buf.append(line)
    if title or buf:
        chunks.append((title, buf))
    if not saw_heading:
        return [("", raw)]
    out: List[Tuple[str, str]] = []
    for heading, body_lines in chunks:
        body = "\n".join(body_lines).strip()
        if body:
            out.append((heading, body))
    return out


def _fit_priority_blocks(
    blocks: Sequence[Tuple[str, str, int]],
    *,
    max_chars: int,
) -> str:
    """按优先级整段装入。装不下时丢掉低优先级整段，并写明省了哪一段。

    承重段（rank ≤ 1）仍放不下时，只从该段末尾截断，不从整篇文档中段对切。
    """
    budget = max(200, int(max_chars))
    reserve = 96
    kept: List[str] = []
    omitted: List[str] = []
    used = 0
    for title, body, rank in blocks:
        piece = (body or "").strip()
        if not piece:
            continue
        sep = 2 if kept else 0
        if used + sep + len(piece) <= budget - reserve:
            kept.append(piece)
            used += sep + len(piece)
            continue
        room = budget - reserve - used - sep
        if rank <= 1 and room > 140:
            note = "\n…（本节后部未展开）"
            cut = piece[: room - len(note)].rstrip() + note
            kept.append(cut)
            used += sep + len(cut)
            continue
        label = title.strip() or "未命名段落"
        if label not in omitted:
            omitted.append(label)
    text = "\n\n".join(kept)
    if omitted:
        shown = "、".join(omitted[:8])
        extra = f"，另有 {len(omitted) - 8} 段" if len(omitted) > 8 else ""
        text = f"{text}\n\n…（因篇幅未展开：{shown}{extra}）".strip()
    if len(text) > budget:
        text = text[: budget - 12].rstrip() + "\n…（未展开）"
    return text


def format_memory_for_agent(
    continuity_text: str,
    spine: Optional[List[Dict[str, Any]]] = None,
    max_chars: int = 3200,
) -> str:
    """给 Agent 的长程记忆块。超预算时按段落优先级保留，不对整篇做首尾对切。

    保留顺序：WorldState 硬锚点 → 角色/关系/物品/未回收钩子增量 → 最近脊骨
    → 其余说明 → 设定快照（上下文里已有 bible，最后才丢）。
    """
    header = "## 长程章节记忆（NovelMaster 风格归档）"
    blocks: List[Tuple[str, str, int]] = [(header, header, -1)]
    if spine:
        lines = ["### 本段脊骨"]
        for item in spine[-12:]:
            lines.append(
                f"- Ch{item.get('index')} `{item.get('title')}`: {item.get('recall')}"
            )
        blocks.append(("本段脊骨", "\n".join(lines), 2))
    for title, body in _split_markdown_sections(continuity_text):
        # 结构化脊骨已经单列最近 12 条，正文里的 Range Spine 整段可让位。
        if spine and _section_rank(title) == 2:
            continue
        blocks.append((title or "连续性正文", body, _section_rank(title)))
    blocks.sort(key=lambda row: row[2])
    return _fit_priority_blocks(blocks, max_chars=max_chars)


def utc_now() -> datetime:
    return datetime.now(timezone.utc)
