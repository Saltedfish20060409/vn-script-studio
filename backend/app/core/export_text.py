"""Submission export — Markdown and Word (.docx) rendering of a project.

Target: light-novel / VN writers submitting drafts to an editor or publisher.
Format is readable plain text (Markdown) and a styled Word document with the
same content: dialogue lines with speaker names, narration as quotes, scene
tags in brackets, menu choices as bullet lists.
"""

from __future__ import annotations

import re
from typing import Dict, List

from app.domain.types import Character, ScriptBlock, VnProject


def _char_map(characters: List[Character]) -> Dict[str, str]:
    out: Dict[str, str] = {}
    for c in characters:
        out[c.id] = c.displayName or c.defineName or c.id
        if c.defineName:
            out.setdefault(c.defineName, c.displayName or c.defineName)
    return out


def _walk_blocks(
    blocks: List[ScriptBlock],
    chars: Dict[str, str],
    md: List[str],
    level: int,
) -> None:
    for b in blocks:
        btype = b.get("type")
        if btype == "scene":
            img = b.get("image") or ""
            trans = b.get("transition")
            md.append(f"[场景：{img}]" + (f"（{trans}）" if trans else ""))
        elif btype in ("show", "hide"):
            img = b.get("image") or ""
            md.append(f"[{'出现' if btype == 'show' else '消失'}：{img}]")
        elif btype == "narration":
            text = str(b.get("text") or "").strip()
            if text:
                md.append(f"> {text}")
        elif btype == "dialogue":
            text = str(b.get("text") or "").strip()
            if text:
                who = chars.get(str(b.get("characterId") or "")) or "——"
                md.append(f"**{who}**：{text}")
        elif btype == "menu":
            prompt = str(b.get("prompt") or "").strip()
            if prompt:
                md.append(f"- 选项提示：{prompt}")
            for choice in b.get("choices") or []:
                if not isinstance(choice, dict):
                    continue
                ct = str(choice.get("text") or "").strip()
                if ct:
                    md.append(f"  - {ct}")
                for child in choice.get("blocks") or []:
                    _walk_blocks([child], chars, md, level)
        elif btype == "raw":
            code = str(b.get("code") or "").strip()
            if code:
                md.append(code)
        # label / jump / return / comment → skipped for submission readability


def project_to_markdown(project: VnProject) -> str:
    """Render the whole project as Markdown (title + chapters)."""
    chars = _char_map(list(project.characters or []))
    md: List[str] = []
    md.append(f"# {project.title or '未命名剧本'}")
    if project.logline:
        md.append("")
        md.append(f"> {project.logline}")
    md.append("")
    for idx, ch in enumerate(project.chapters or [], start=1):
        md.append("")
        md.append(f"## {ch.title or f'第{idx}章'}")
        md.append("")
        if ch.synopsis:
            md.append(f"*{ch.synopsis}*")
            md.append("")
        _walk_blocks(list(ch.blocks or []), chars, md, 0)
    return "\n".join(md).strip() + "\n"


def project_to_docx(project: VnProject) -> bytes:
    """Render the project as a .docx file (returns file bytes)."""
    from docx import Document

    chars = _char_map(list(project.characters or []))
    doc = Document()

    title = project.title or "未命名剧本"
    doc.add_heading(title, level=0)
    if project.logline:
        doc.add_paragraph(project.logline).italic = True

    for idx, ch in enumerate(project.chapters or [], start=1):
        doc.add_heading(ch.title or f"第{idx}章", level=1)
        if ch.synopsis:
            p = doc.add_paragraph(ch.synopsis)
            p.italic = True
        _blocks_to_docx(list(ch.blocks or []), chars, doc)
    import io

    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def _blocks_to_docx(
    blocks: List[ScriptBlock],
    chars: Dict[str, str],
    doc,
) -> None:
    from docx.shared import Pt

    for b in blocks:
        btype = b.get("type")
        if btype == "scene":
            img = b.get("image") or ""
            doc.add_paragraph(f"[场景：{img}]").runs[0].bold = True
        elif btype in ("show", "hide"):
            img = b.get("image") or ""
            doc.add_paragraph(f"[{'出现' if btype == 'show' else '消失'}：{img}]").runs[
                0
            ].italic = True
        elif btype == "narration":
            text = str(b.get("text") or "").strip()
            if text:
                p = doc.add_paragraph(text)
                p.paragraph_format.left_indent = Pt(24)
        elif btype == "dialogue":
            text = str(b.get("text") or "").strip()
            if text:
                who = chars.get(str(b.get("characterId") or "")) or "——"
                p = doc.add_paragraph()
                run = p.add_run(f"{who}：")
                run.bold = True
                p.add_run(text)
        elif btype == "menu":
            prompt = str(b.get("prompt") or "").strip()
            if prompt:
                doc.add_paragraph(f"【选项】{prompt}")
            for choice in b.get("choices") or []:
                if not isinstance(choice, dict):
                    continue
                ct = str(choice.get("text") or "").strip()
                if ct:
                    doc.add_paragraph(f"・{ct}", style="List Bullet")
                for child in choice.get("blocks") or []:
                    _blocks_to_docx([child], chars, doc)


def safe_filename(title: str, suffix: str) -> str:
    safe = re.sub(r"[^\w\u4e00-\u9fff]+", "_", title or "vn")[:40] or "vn"
    return f"{safe}{suffix}"
