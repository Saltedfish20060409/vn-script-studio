"""Submission export — Markdown and Word (.docx) rendering of a project.

Target: light-novel / VN writers submitting drafts to an editor or publisher.
Format is readable plain text (Markdown) and a styled Word document with the
same content: dialogue lines with speaker names, narration as quotes, scene
tags in brackets, menu choices as bullet lists.
"""

from __future__ import annotations

import re
from typing import Dict, List, Optional

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
    """Render the whole project as Markdown (title + chapters).

    注音按 **W3C Ruby** 的规范形态渲染成 `<ruby>…<rt>…</rt></ruby>`（含 `<rp>` 回退）：
    Markdown 里嵌 HTML 是通行做法，而不转换的话读者会看到 `｜汉字《注音》` 这种源标记。
    """
    from app.core.ruby_render import to_html

    chars = _char_map(list(project.characters or []))
    md: List[str] = []
    md.append(f"# {to_html(project.title or '未命名剧本')}")
    if project.logline:
        md.append("")
        md.append(f"> {to_html(project.logline)}")
    md.append("")
    for idx, ch in enumerate(project.chapters or [], start=1):
        md.append("")
        md.append(f"## {to_html(ch.title or f'第{idx}章')}")
        md.append("")
        if ch.synopsis:
            md.append(f"*{to_html(ch.synopsis)}*")
            md.append("")
        prose = (getattr(ch, "prose", None) or "").strip()
        if prose:
            md.append(to_html(prose))
            md.append("")
        else:
            _walk_blocks(list(ch.blocks or []), chars, md, 0)
    return "\n".join(md).strip() + "\n"


def project_to_docx(project: VnProject) -> bytes:
    """Render the project as a .docx file (returns file bytes).

    注音在**这一条导出**里走 **`<rp>` 回退**的纯文本形态（`漢字（かんじ）`），
    而不是 Word 原生注音（`w:ruby`）：原生注音的基准词只存在于 `<w:rubyBase>` 里，
    **简单取文本的工具会漏掉它**，而这条导出的用途恰恰是"把作品读出来 / 再导回工作台"
    （导入侧认得 `w:ruby`，见 `core/file_text.py`，但别的工具不一定），保文本完整性更重要。

    投稿稿（`export_submission`）默认写原生注音——编辑用 Word 打开时是真的注音，
    而不是括号文本。两者的取舍与"能验证到什么程度"写在 `core/docx_ruby.py` 的模块文档里。
    """
    from docx import Document

    from app.core.ruby_render import to_rp_text

    chars = _char_map(list(project.characters or []))
    doc = Document()

    title = to_rp_text(project.title or "未命名剧本")
    doc.add_heading(title, level=0)
    if project.logline:
        doc.add_paragraph(to_rp_text(project.logline)).italic = True

    # 分卷时：卷标题做一级标题、章节降为二级，导出稿自带层级；未分卷时与原来完全一致。
    volume_titles = {
        str(v.id): (v.title or "") for v in list(project.volumes or [])
    }
    current_volume: Optional[str] = None
    for idx, ch in enumerate(project.chapters or [], start=1):
        volume_title = volume_titles.get(str(getattr(ch, "volumeId", None) or ""))
        if volume_title and volume_title != current_volume:
            doc.add_heading(to_rp_text(volume_title), level=1)
            current_volume = volume_title
        doc.add_heading(
            to_rp_text(ch.title or f"第{idx}章"), level=2 if current_volume else 1
        )
        if ch.synopsis:
            p = doc.add_paragraph(to_rp_text(ch.synopsis))
            p.italic = True
        prose = (getattr(ch, "prose", None) or "").strip()
        if prose:
            for para in prose.split("\n"):
                doc.add_paragraph(to_rp_text(para))
        else:
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

    from app.core.ruby_render import to_rp_text

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
                p = doc.add_paragraph(to_rp_text(text))
                p.paragraph_format.left_indent = Pt(24)
        elif btype == "dialogue":
            text = str(b.get("text") or "").strip()
            if text:
                who = chars.get(str(b.get("characterId") or "")) or "——"
                p = doc.add_paragraph()
                run = p.add_run(f"{who}：")
                run.bold = True
                p.add_run(to_rp_text(text))
        elif btype == "menu":
            prompt = str(b.get("prompt") or "").strip()
            if prompt:
                doc.add_paragraph(f"【选项】{to_rp_text(prompt)}")
            for choice in b.get("choices") or []:
                if not isinstance(choice, dict):
                    continue
                ct = str(choice.get("text") or "").strip()
                if ct:
                    doc.add_paragraph(f"・{to_rp_text(ct)}", style="List Bullet")
                for child in choice.get("blocks") or []:
                    _blocks_to_docx([child], chars, doc)


def safe_filename(title: str, suffix: str) -> str:
    safe = re.sub(r"[^\w\u4e00-\u9fff]+", "_", title or "vn")[:40] or "vn"
    return f"{safe}{suffix}"


def attachment_disposition(filename: str) -> str:
    """Content-Disposition 值：ASCII 回退 + RFC 5987 UTF-8 扩展。

    Starlette 以 latin-1 编码响应头，直接内嵌中文文件名会抛
    UnicodeEncodeError（=500）。现代浏览器优先读 ``filename*``，
    老客户端回退到纯 ASCII 近似名。
    """
    from urllib.parse import quote

    ascii_fallback = (
        filename.encode("ascii", "ignore").decode("ascii").strip("_ ").strip()
        or "export"
    )
    return (
        f"attachment; filename=\"{ascii_fallback}\"; "
        f"filename*=UTF-8''{quote(filename)}"
    )
