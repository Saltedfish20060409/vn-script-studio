"""Ported from packages/core/src/importText.ts"""
from __future__ import annotations

import re
import time
from datetime import datetime

from app.domain.types import ScriptBlock, VnProject

from .project import normalize_project

_RENPY_MARKER = re.compile(r"^(label\s+\w+\s*:|scene\s+|define\s+\w+|menu\b)", re.IGNORECASE)
_DIALOGUE_LINE = re.compile(r"^(.{1,12})[：:]\s*(.+)$")


def project_from_plain_text(title: str, text: str) -> VnProject:
    """Create a project from imported Word/text/.rpy content."""
    cleaned = text.replace("\r\n", "\n").strip()
    lines = [l.rstrip() for l in cleaned.split("\n")]

    looks_renpy = any(_RENPY_MARKER.match(l.strip()) for l in lines)

    blocks: list[ScriptBlock]
    if looks_renpy:
        blocks = [
            {"type": "comment", "text": "从脚本文件导入"},
            {"type": "raw", "code": cleaned},
        ]
    else:
        blocks = [
            {"type": "label", "id": "start", "name": "start"},
            {"type": "comment", "text": "以下内容由文档导入，可改写成 Ren'Py 对白"},
        ]
        for raw_line in lines:
            line = raw_line.strip()
            if not line:
                continue
            m = _DIALOGUE_LINE.match(line)
            if m:
                blocks.append({"type": "narration", "text": f"{m.group(1)}：{m.group(2)}"})
            else:
                blocks.append({"type": "narration", "text": line})

    return normalize_project(
        {
            "id": f"proj-{int(time.time() * 1000)}",
            "title": title,
            "chapters": [
                {
                    "id": "ch1",
                    "title": "导入稿",
                    "synopsis": "从文件导入，待整理",
                    "blocks": blocks,
                }
            ],
            "characters": [],
            "bible": {
                "notes": f"导入于 {datetime.now().astimezone().strftime('%Y/%m/%d %H:%M:%S')}",
            },
        }
    )
