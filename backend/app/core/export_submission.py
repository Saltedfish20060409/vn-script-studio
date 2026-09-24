"""投稿包导出：投稿排版单篇（.docx）与分章打包（.zip）。

为什么单独一份而不是改 `export_text.project_to_docx`：那个函数是"把作品读出来"
的通用导出（作者自己看、存档都用它），排版中性。投稿是另一件事——投稿方对稿子有
**格式要求**，而这些要求在阅读场景下全是多余的（首行缩进、每章另起一页、文末标字数）。
两件事混在一个函数里，早晚会为了投稿改坏阅读导出。

所以：`project_to_docx` 保持原样（默认行为一字不改），这里另开一条，
选项全部显式、默认值取"投稿常用"。

口径一致：字数一律用 `services.writing_stats.count_chapter_words`
（正文优先；正文为空才算脚本块），与写作统计、连载页显示的是同一个数。
"""

from __future__ import annotations

import io
import zipfile
from dataclasses import dataclass
from datetime import date

from app.domain.types import VnProject
from app.services.writing_stats import count_chapter_words

#: 中文投稿惯例：正文小四（12pt）、1.5 倍行距、首行缩进 2 字符（= 2 × 12pt）
BODY_FONT_PT = 12
FIRST_LINE_INDENT_PT = BODY_FONT_PT * 2
LINE_SPACING = 1.5


@dataclass(frozen=True)
class SubmissionOptions:
    """投稿排版选项。默认值 = 最常被投稿方要求的那一套。"""

    #: 正文首行缩进 2 字符
    indent_first_line: bool = True
    #: 是否把章节梗概（synopsis）带上。默认**不带**：那是写给自己的备注，
    #: 混在投稿稿里会被编辑当成正文。
    include_synopsis: bool = False
    #: 每章另起一页
    page_break_per_chapter: bool = True
    #: 每章末尾标注字数（编辑常问"这一章多少字"）
    word_count_footer: bool = True
    #: 是否带上卷标题（分卷作品才有）
    include_volume_headings: bool = True
    #: 注音用 **Word 原生注音**（`w:ruby`，编辑用 Word 打开时注音是真的注音）。
    #: 关掉则回退成 `漢字（かんじ）` 这样的纯文本形态（见 core/docx_ruby.py 的取舍说明：
    #: 原生注音的基准词只存在于 `w:rubyBase` 里，简单取文本的工具会漏掉它）。
    native_ruby: bool = True
    #: 投稿信息页上的作者名 / 联系方式（留空就不写这一行）
    author: str = ""
    contact: str = ""


def _setup_document():
    from docx import Document
    from docx.shared import Pt

    doc = Document()
    style = doc.styles["Normal"]
    style.font.size = Pt(BODY_FONT_PT)
    # 中文稿子用中文字体名，Word 打开才不会变成等线/Calibri 混排
    style.font.name = "宋体"
    return doc


def _add_body_paragraph(doc, text: str, *, indent: bool, native_ruby: bool = True):
    from docx.shared import Pt

    from app.core.docx_ruby import add_text

    # 注音**不能**以 `｜汉字《注音》` 的源标记进投稿稿：
    # 默认写 Word 原生注音（`w:ruby`），关掉时回退成 `漢字（かんじ）`（见 core/docx_ruby.py）。
    p = doc.add_paragraph()
    add_text(
        p,
        text,
        native=native_ruby,
        # 正文小四（12pt）→ 基准 24 半磅、注音 12 半磅、抬升 22
        base_hps=BODY_FONT_PT * 2,
        ruby_hps=BODY_FONT_PT,
        raise_hps=BODY_FONT_PT * 2 - 2,
    )
    p.paragraph_format.line_spacing = LINE_SPACING
    if indent:
        p.paragraph_format.first_line_indent = Pt(FIRST_LINE_INDENT_PT)
    return p


def _chapter_heading(doc, title: str, *, has_volume: bool):
    # 卷标题一级、章节二级；没有卷时章节就是一级——与阅读导出同一个层级规则
    return doc.add_heading(title, level=2 if has_volume else 1)


def _add_cover(doc, project: VnProject, opts: SubmissionOptions, *, scope_note: str):
    """投稿信息页：作品名 + 规模 + 生成日期（可选作者名/联系方式）。

    这一页不是"好看"，是投稿的实际需要：编辑拿到一个 docx，第一眼要知道这是什么、
    多长、谁写的。信息全部来自作品本身，不编造（作者名留空就不写）。
    """
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt

    from app.core.ruby_render import to_rp_text

    title = doc.add_heading(to_rp_text(project.title or "未命名作品"), level=0)
    title.alignment = WD_ALIGN_PARAGRAPH.CENTER
    if project.logline:
        p = doc.add_paragraph(to_rp_text(project.logline))
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        p.runs[0].italic = True
    chapters = list(project.chapters or [])
    total = sum(count_chapter_words(ch) for ch in chapters)
    meta = [
        f"体裁：{project.genre or '未填'}",
        f"篇幅：{len(chapters)} 章 / 约 {total} 字",
        f"导出日期：{date.today().isoformat()}",
    ]
    if scope_note:
        meta.append(scope_note)
    if opts.author.strip():
        meta.insert(0, f"作者：{opts.author.strip()}")
    if opts.contact.strip():
        meta.append(f"联系方式：{opts.contact.strip()}")
    for line in meta:
        p = doc.add_paragraph(line)
        p.alignment = WD_ALIGN_PARAGRAPH.CENTER
        for run in p.runs:
            run.font.size = Pt(10.5)
    doc.add_page_break()


def _add_chapter(doc, project: VnProject, chapter, opts: SubmissionOptions, *, has_volume: bool):
    from docx.enum.text import WD_ALIGN_PARAGRAPH
    from docx.shared import Pt

    _chapter_heading(doc, chapter.title or "（无标题）", has_volume=has_volume)
    if opts.include_synopsis and chapter.synopsis:
        p = doc.add_paragraph(chapter.synopsis)
        p.italic = True

    prose = (getattr(chapter, "prose", None) or "").strip()
    if prose:
        for para in prose.split("\n"):
            text = para.strip()
            if text:
                _add_body_paragraph(
                    doc, text, indent=opts.indent_first_line, native_ruby=opts.native_ruby
                )
    else:
        _blocks_to_submission_docx(list(chapter.blocks or []), doc, opts)

    if opts.word_count_footer:
        p = doc.add_paragraph(f"（本章 {count_chapter_words(chapter)} 字）")
        p.alignment = WD_ALIGN_PARAGRAPH.RIGHT
        for run in p.runs:
            run.italic = True
            run.font.size = Pt(9)


def _blocks_to_submission_docx(blocks, doc, opts: SubmissionOptions):
    """脚本块工程的投稿排版：旁白 = 正文段，对白 = 「名字：台词」整段。

    刻意不保留 `[场景：xxx]`、`[选项]` 这类舞台指示——投稿稿是给编辑读故事的，
    这些是给引擎看的。想看完整结构请用「项目 → 导出 → 工程包」。
    """
    from app.core.agent_context import _blocks_to_plain  # noqa: PLC0415

    plain = _blocks_to_plain(blocks, [])
    for line in plain.split("\n"):
        text = line.strip()
        if text:
            _add_body_paragraph(
                doc, text, indent=opts.indent_first_line, native_ruby=opts.native_ruby
            )


def submission_docx(project: VnProject, opts: SubmissionOptions | None = None) -> bytes:
    """整部作品一个 .docx（投稿排版）。"""
    opts = opts or SubmissionOptions()
    doc = _setup_document()
    _add_cover(doc, project, opts, scope_note="")
    volume_titles = {str(v.id): (v.title or "") for v in list(project.volumes or [])}
    current_volume: str | None = None
    chapters = list(project.chapters or [])
    for i, chapter in enumerate(chapters):
        volume_title = volume_titles.get(str(getattr(chapter, "volumeId", None) or ""))
        has_volume = False
        if opts.include_volume_headings and volume_title and volume_title != current_volume:
            doc.add_heading(volume_title, level=1)
            current_volume = volume_title
        has_volume = bool(current_volume)
        _add_chapter(doc, project, chapter, opts, has_volume=has_volume)
        if opts.page_break_per_chapter and i < len(chapters) - 1:
            doc.add_page_break()
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def chapter_docx(project: VnProject, chapter, opts: SubmissionOptions | None = None) -> bytes:
    """单章一个 .docx（分章投稿/连载上传用）。"""
    opts = opts or SubmissionOptions()
    doc = _setup_document()
    _add_cover(doc, project, opts, scope_note=f"本次投稿：{chapter.title or ''}")
    _add_chapter(doc, project, chapter, opts, has_volume=False)
    buf = io.BytesIO()
    doc.save(buf)
    return buf.getvalue()


def word_count_report(project: VnProject) -> str:
    """投稿信息 / 字数统计页（纯文本，随分章包一起给出去）。"""
    chapters = list(project.chapters or [])
    lines = [
        f"作品：{project.title or '未命名作品'}",
        f"体裁：{project.genre or '未填'}",
        "",
        f"章节数：{len(chapters)}",
    ]
    total = 0
    for i, chapter in enumerate(chapters, start=1):
        words = count_chapter_words(chapter)
        total += words
        state = "已发布" if getattr(chapter, "publishedAt", None) else "存稿"
        lines.append(f"  {i:02d}  {chapter.title or '（无标题）'}  {words} 字  [{state}]")
    lines += [
        "",
        f"总字数：{total}",
        "",
        "字数口径：汉字逐字计数、拉丁字母/数字按词计数；一章优先数正文，正文为空才数脚本块。",
    ]
    return "\n".join(lines) + "\n"


def safe_chapter_filename(index: int, title: str) -> str:
    """分章包里的文件名：`第01章_标题.docx`（章序号补零，按文件名排序就是阅读顺序）。

    `..`/前导点也要清掉：文件名最终会落到别人的解压目录里，`../x.docx`
    这类名字在不同解压工具下行为不一致（有的会真的往上跳一层）。
    """
    import re

    safe = re.sub(r"[\\/:*?\"<>|\s]+", "_", (title or "").strip())
    safe = safe.strip("._")[:30] or "无标题"
    return f"第{index:02d}章_{safe}.docx"


def submission_zip(project: VnProject, opts: SubmissionOptions | None = None) -> bytes:
    """分章包：每章一个 .docx + 投稿信息.txt。

    为什么是 zip 而不是"一个 docx 里分页"：不少投稿渠道要求**一章一个文件**
    （编辑分批读、平台按章上传），打包是唯一能一次给完的形态。
    """
    opts = opts or SubmissionOptions()
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w", zipfile.ZIP_DEFLATED) as zf:
        zf.writestr("投稿信息.txt", word_count_report(project))
        for i, chapter in enumerate(list(project.chapters or []), start=1):
            zf.writestr(safe_chapter_filename(i, chapter.title or ""), chapter_docx(project, chapter, opts))
    return buf.getvalue()
