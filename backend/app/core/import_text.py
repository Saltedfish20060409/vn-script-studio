"""From plain text / Word / .rpy content to a project.

## 为什么要分章

原来把整份文本塞进**一个**「导入稿」章节、并且**每行一个 block**。对小说文件（网文/轻小说
动辄几十上百章）来说三件事全崩：一章装几十万字 → 编辑器打不开；没有章节结构 → 没法定位、
没法按章处理；块数爆炸 → 保存与渲染都很重。现在按「第X章/第X节/卷/序章/Chapter N」切章，
并且把连续正文按**段落**成块（同一段的多行合成一个 narration block）。

顺带：文件里若有「第一卷」这样的**卷标题**，就建出卷并把后续章节归进去（与分卷功能对齐）。
"""

from __future__ import annotations

import re
import time
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from app.domain.types import ScriptBlock, VnProject

from .project import normalize_project

_RENPY_MARKER = re.compile(r"^(label\s+\w+\s*:|scene\s+|define\s+\w+|menu\b)", re.IGNORECASE)
_DIALOGUE_LINE = re.compile(r"^(.{1,12})[：:]\s*(.+)$")

# 章节标题：第X章/回/节/篇（标题必须用分隔符或空格隔开），或 Chapter N
_NUM = r"[0-9０-９一二三四五六七八九十百千万零两]+"
_TITLE_TAIL = r"(?:\s*[：:、.．\-—·]\s*\S{1,24}|\s+\S{1,24})?"
_CHAPTER_HEADING = re.compile(rf"^\s*第\s*{_NUM}\s*[章回节篇]{_TITLE_TAIL}$")
_CHAPTER_HEADING_EN = re.compile(
    rf"^\s*(?:chapter|ch\.?)\s*[0-9ivxlc]+{_TITLE_TAIL}$", re.IGNORECASE
)
# 卷标题：第X卷；以及序章/楔子/尾声这类无编号标题
_VOLUME_HEADING = re.compile(rf"^\s*第\s*{_NUM}\s*卷{_TITLE_TAIL}$")
_SPECIAL_HEADING = re.compile(
    r"^\s*(?:序章|序|楔子|引子|前言|尾声|终章|后记|番外|间章)"
    r"(?:\s*[：:、.．\-—·]\s*\S{1,20}|\s+\S{1,20})?$"
)
# 标题行不该太长（避免把"第一章里他写道……"这种正文误判成标题）
_HEADING_MAX_LEN = 24


def _is_heading(line: str) -> bool:
    text = line.strip()
    if not text or len(text) > _HEADING_MAX_LEN:
        return False
    return bool(
        _CHAPTER_HEADING.match(text)
        or _CHAPTER_HEADING_EN.match(text)
        or _VOLUME_HEADING.match(text)
        or _SPECIAL_HEADING.match(text)
    )


def _is_volume_heading(line: str) -> bool:
    text = line.strip()
    return bool(text) and len(text) <= _HEADING_MAX_LEN and bool(_VOLUME_HEADING.match(text))


def _looks_renpy(text: str) -> bool:
    return any(_RENPY_MARKER.match(line.strip()) for line in text.split("\n"))


def _blocks_from_lines(lines: List[str]) -> List[ScriptBlock]:
    """把一段文本变成块：对话行各自成块，连续正文按**段落**合并成一个旁白块。

    段落 = 空行分隔；一段里的多行合成一个 block（用 \\n 连接），这样小说不会是"一行一块"。
    """
    blocks: List[ScriptBlock] = []
    paragraph: List[str] = []

    def flush() -> None:
        if paragraph:
            blocks.append({"type": "narration", "text": "\n".join(paragraph)})
            paragraph.clear()

    for raw in lines:
        line = raw.rstrip()
        if not line.strip():
            flush()
            continue
        match = _DIALOGUE_LINE.match(line.strip())
        if match:
            flush()
            blocks.append(
                {"type": "narration", "text": f"{match.group(1)}：{match.group(2)}"}
            )
            continue
        paragraph.append(line.strip())
    flush()
    return blocks


def _split_sections(lines: List[str]) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """按标题切分，返回 (卷列表, 章节列表)。

    章节是 [{title, lines, volumeIndex}]；卷只在文件里真的出现卷标题时才建。
    """
    volumes: List[Dict[str, Any]] = []
    chapters: List[Dict[str, Any]] = []
    current_volume: Optional[int] = None
    buckets: List[Dict[str, Any]] = []
    preamble: List[str] = []

    for line in lines:
        if _is_volume_heading(line):
            title = line.strip()
            volumes.append({"id": f"vol-{len(volumes) + 1}", "title": title})
            current_volume = len(volumes) - 1
            continue
        if _is_heading(line):
            buckets.append(
                {"title": line.strip(), "lines": [], "volumeIndex": current_volume}
            )
            continue
        if buckets:
            buckets[-1]["lines"].append(line)
        else:
            preamble.append(line)

    # 标题之前的内容（很多小说开头是"书名/作者"或直接进正文）并入第一章
    if buckets:
        buckets[0]["lines"] = preamble + buckets[0]["lines"]
    elif preamble:
        buckets.append({"title": "", "lines": preamble, "volumeIndex": current_volume})

    for bucket in buckets:
        if not any(l.strip() for l in bucket["lines"]) and bucket["title"] == "":
            continue
        chapters.append(bucket)
    return volumes, chapters


def project_from_plain_text(title: str, text: str) -> VnProject:
    """Create a project from imported Word/text/.rpy content."""
    cleaned = text.replace("\r\n", "\n").strip()
    lines = [l.rstrip() for l in cleaned.split("\n")]

    blocks: List[ScriptBlock] = []
    volumes_out: List[Dict[str, Any]] = []
    chapters_out: List[Dict[str, Any]] = []

    if _looks_renpy(cleaned):
        # 脚本文件：原样进 raw 块（保持原有行为）
        blocks = [
            {"type": "comment", "text": "从脚本文件导入"},
            {"type": "raw", "code": cleaned},
        ]
        chapters_out = [
            {
                "id": "ch1",
                "title": "导入稿",
                "synopsis": "从文件导入，待整理",
                "blocks": blocks,
            }
        ]
    else:
        raw_volumes, raw_chapters = _split_sections(lines)
        volumes_out = list(raw_volumes)
        # 文件里一个标题都没有 → 整篇作为「导入稿」（与旧行为一致，读起来也更像话）
        untitled = len(raw_chapters) == 1 and not raw_chapters[0]["title"]
        for index, bucket in enumerate(raw_chapters, start=1):
            chapter_blocks: List[ScriptBlock] = [
                {"type": "label", "id": "start", "name": "start"}
            ]
            if index == 1:
                chapter_blocks.append(
                    {"type": "comment", "text": "以下内容由文档导入，可改写成 Ren'Py 对白"}
                )
            chapter_blocks.extend(_blocks_from_lines(bucket["lines"]))
            chapter: Dict[str, Any] = {
                "id": f"ch{index}",
                "title": bucket["title"] or ("导入稿" if untitled else f"第{index}章"),
                "blocks": chapter_blocks,
            }
            volume_index = bucket.get("volumeIndex")
            if volume_index is not None and 0 <= volume_index < len(volumes_out):
                chapter["volumeId"] = volumes_out[volume_index]["id"]
            chapters_out.append(chapter)
        if not chapters_out:
            blocks = [
                {"type": "label", "id": "start", "name": "start"},
                {"type": "comment", "text": "以下内容由文档导入，可改写成 Ren'Py 对白"},
                {"type": "narration", "text": cleaned},
            ]
            chapters_out = [
                {
                    "id": "ch1",
                    "title": "导入稿",
                    "synopsis": "从文件导入，待整理",
                    "blocks": blocks,
                }
            ]

    payload: Dict[str, Any] = {
        "id": f"proj-{int(time.time() * 1000)}",
        "title": title,
        "chapters": chapters_out,
        "characters": [],
        "bible": {
            "notes": f"导入于 {datetime.now().astimezone().strftime('%Y/%m/%d %H:%M:%S')}",
        },
    }
    if volumes_out:
        payload["volumes"] = volumes_out
    return normalize_project(payload)


def count_import_blocks(chapters: List[Dict[str, Any]]) -> int:
    return sum(len(ch.get("blocks") or []) for ch in chapters)
