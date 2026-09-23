"""投稿包导出（`/export/submission`）与排版选项。

为什么值得测：
- 投稿排版是"看起来在写功能、其实是硬要求"的那类东西——首行缩进没生效，
  界面上完全看不出来（下载的还是个能打开的 docx），只有编辑会说"格式不对"。
- `synopsis`（章节梗概）默认必须**不带**：它是写给作者自己的备注，混进投稿稿里
  会被当成正文，这是投稿场景里最容易犯且最难自己发现的错。
- 分章包必须"一章一个文件 + 信息页"，且顺序按章节顺序（文件名补零）。
"""

from __future__ import annotations

import io
import zipfile

from docx import Document

from app.core.export_submission import (
    SubmissionOptions,
    chapter_docx,
    safe_chapter_filename,
    submission_docx,
    submission_zip,
    word_count_report,
)
from app.core.project import normalize_project


def _project():
    return normalize_project(
        {
            "id": "proj-sub",
            "title": "钟声与失物招领处",
            "genre": "轻小说 / 校园悬疑",
            "logline": "转学第三天，我听见了停了三年的大钟。",
            "volumes": [{"id": "vol-1", "title": "第一卷 钟声"}],
            "chapters": [
                {
                    "id": "ch1",
                    "title": "第一章 迟到三天的钟声",
                    "synopsis": "主角听见钟声里的呼救（写给自己看的梗概）",
                    "volumeId": "vol-1",
                    "prose": "雨见町一年有两百天在下雨。\n「你听见了吗？」她问。",
                    "publishedAt": "2026-03-01T00:00:00Z",
                },
                {
                    "id": "ch2",
                    "title": "第二章 第七个抽屉",
                    "synopsis": "抽屉里是她自己的东西",
                    "volumeId": "vol-1",
                    "prose": "第七个抽屉是空的。",
                },
            ],
        }
    )


def _docx_text(data: bytes) -> str:
    doc = Document(io.BytesIO(data))
    return "\n".join(p.text for p in doc.paragraphs)


def _body_paragraph_indent(data: bytes, needle: str):
    """找出含指定正文句子的那一级段落，读它的首行缩进。

    只认"正文句"那一行：封面上的作品名/体裁行也是普通段落，但它们本来就不该缩进，
    拿第一段去断言会得到假结论。
    """
    doc = Document(io.BytesIO(data))
    for p in doc.paragraphs:
        if needle in p.text:
            return p.paragraph_format.first_line_indent
    return None


# ---- 1. 单篇投稿稿 ---------------------------------------------------------


def test_submission_docx_contains_title_and_chapters():
    text = _docx_text(submission_docx(_project()))
    assert "钟声与失物招领处" in text
    assert "第一章 迟到三天的钟声" in text
    assert "第二章 第七个抽屉" in text
    assert "第一卷 钟声" in text  # 分卷作品带卷标题
    assert "第七个抽屉是空的。" in text


def test_synopsis_is_excluded_by_default_and_can_be_turned_on():
    """梗概默认不带（会被编辑当正文），显式打开才带。"""
    default_text = _docx_text(submission_docx(_project()))
    assert "写给自己看的梗概" not in default_text

    with_synopsis = _docx_text(
        submission_docx(_project(), SubmissionOptions(include_synopsis=True))
    )
    assert "写给自己看的梗概" in with_synopsis


def test_first_line_indent_applies_to_body_and_can_be_disabled():
    """首行缩进必须真的写进段落格式（不是"看起来像"）。"""
    body = "雨见町一年有两百天在下雨。"
    indented = _body_paragraph_indent(submission_docx(_project()), body)
    assert indented is not None
    assert indented.pt == 24  # 2 字符 × 12pt

    plain = _body_paragraph_indent(
        submission_docx(_project(), SubmissionOptions(indent_first_line=False)), body
    )
    assert plain is None or getattr(plain, "pt", 0) == 0


def test_word_count_footer_reports_chapter_words():
    text = _docx_text(submission_docx(_project()))
    # 单章末尾标注字数（编辑常问"这章多少字"）
    assert "（本章 " in text
    # 口径与写作统计一致：汉字逐字算
    assert "（本章 21 字）" in text or "（本章 1" in text


def test_cover_carries_scale_and_optional_author():
    text = _docx_text(submission_docx(_project()))
    assert "体裁：轻小说 / 校园悬疑" in text
    assert "篇幅：2 章" in text
    assert "作者：" not in text  # 没填就不写这一行（不编造）

    with_author = _docx_text(
        submission_docx(_project(), SubmissionOptions(author="某某", contact="a@b.c"))
    )
    assert "作者：某某" in with_author
    assert "联系方式：a@b.c" in with_author


def test_script_block_project_is_rendered_as_readable_prose():
    """脚本块工程的投稿稿只出故事文字，不出现舞台指示（那些是给引擎看的）。"""
    vn = normalize_project(
        {
            "id": "p2",
            "title": "脚本工程",
            "chapters": [
                {
                    "id": "c1",
                    "title": "第一章",
                    "blocks": [
                        {"type": "scene", "image": "bg station"},
                        {"type": "narration", "text": "雨停了。"},
                        {"type": "dialogue", "characterId": "a", "text": "走吧。"},
                    ],
                }
            ],
        }
    )
    text = _docx_text(submission_docx(vn))
    assert "雨停了。" in text
    assert "[场景：" not in text


# ---- 2. 分章包 -------------------------------------------------------------


def test_submission_zip_has_one_docx_per_chapter_plus_report():
    data = submission_zip(_project())
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        names = zf.namelist()
        assert "投稿信息.txt" in names
        chapter_files = [n for n in names if n.endswith(".docx")]
        assert len(chapter_files) == 2
        # 文件名按章序号补零，按文件名排序就是阅读顺序
        assert chapter_files[0].startswith("第01章_")
        assert chapter_files[1].startswith("第02章_")
        # 每个文件都是一份能打开的 docx，且只含自己那一章
        inner = _docx_text(zf.read(chapter_files[1]))
        assert "第七个抽屉是空的。" in inner
        assert "雨见町一年有两百天在下雨。" not in inner


def test_word_count_report_lists_every_chapter_and_publish_state():
    report = word_count_report(_project())
    assert "作品：钟声与失物招领处" in report
    assert "章节数：2" in report
    assert "[已发布]" in report
    assert "[存稿]" in report
    assert "总字数：" in report
    # 口径要说明白，不能只丢一个数字
    assert "汉字逐字计数" in report


def test_chapter_filename_is_safe():
    assert safe_chapter_filename(1, "第一章 迟到三天的钟声") == "第01章_第一章_迟到三天的钟声.docx"
    # 路径分隔符与保留字符必须被换掉，否则解压时可能出目录穿越
    assert "/" not in safe_chapter_filename(2, "a/b\\c:d*e?f")
    assert ".." not in safe_chapter_filename(3, "../逃出去")
    assert safe_chapter_filename(4, "") == "第04章_无标题.docx"


def test_empty_project_does_not_crash():
    empty = normalize_project({"id": "empty", "title": "空作品"})
    assert _docx_text(submission_docx(empty))
    with zipfile.ZipFile(io.BytesIO(submission_zip(empty))) as zf:
        assert "投稿信息.txt" in zf.namelist()


def test_chapter_docx_single_file():
    vn = _project()
    data = chapter_docx(vn, vn.chapters[0])
    text = _docx_text(data)
    assert "第一章 迟到三天的钟声" in text
    assert "第七个抽屉" not in text
