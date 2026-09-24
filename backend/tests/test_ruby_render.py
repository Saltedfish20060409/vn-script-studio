"""注音渲染：源标记 → W3C 形态 / rp 回退 / Ren'Py 安全文本。

依据：W3C《Ruby Markup Extensions》（`<ruby>` + `<rt>` + `<rp>` 回退）。
为什么必须有这层：作者在正文里写的是 `｜漢字《かんじ》`，那是**源标记**——
不渲染的话，它会被原样带进 Markdown、Word 投稿稿和 .rpy 脚本里，读者看到的是一串符号。
Ren'Py 更糟：`{汉字|注音}` 里的花括号会被当成文本标签，脚本运行时直接报"未知文本标签"。
"""

from __future__ import annotations

from app.core.ruby_render import (
    ruby_marks,
    to_html,
    to_plain,
    to_renpy_text,
    to_rp_text,
)

# ---- W3C HTML 形态 ------------------------------------------------------------


def test_html_follows_w3c_ruby_with_rp_fallback():
    out = to_html("前面｜漢字《かんじ》后面")
    assert out == (
        "前面<ruby>漢字<rp>（</rp><rt>かんじ</rt><rp>）</rp></ruby>后面"
    )


def test_html_handles_brace_form_and_ascii_bar():
    assert "<ruby>漢字<rp>（</rp><rt>かんじ</rt>" in to_html("{漢字|かんじ}")
    assert "<ruby>漢字<rp>（</rp><rt>かんじ</rt>" in to_html("|漢字《かんじ》")


def test_html_renders_multiple_marks_in_order():
    out = to_html("｜甲《こう》と｜乙《おつ》")
    assert out.count("<ruby>") == 2
    assert out.index("甲") < out.index("乙")


def test_marker_inner_spaces_are_trimmed():
    """`{ 笑顔|えがお }` 里的空格不该进 `<rt>`（那不是作者的本意）。"""
    out = to_html("{ 笑顔 | えがお }")
    assert "<rt>えがお</rt>" in out
    assert "<ruby>笑顔<rp>" in out


# ---- rp 回退与纯文本 -----------------------------------------------------------


def test_rp_text_is_readable_fallback():
    assert to_rp_text("｜漢字《かんじ》") == "漢字（かんじ）"
    assert to_rp_text("{漢字|かんじ}") == "漢字（かんじ）"


def test_plain_strips_reading():
    assert to_plain("｜漢字《かんじ》を読む") == "漢字を読む"


# ---- 不完整的标记要原样保留（交给体检报，不在这里吞掉） -------------------------


def test_incomplete_markers_are_left_untouched():
    # 注音为空 / 基准为空：渲染层不能悄悄吞掉，否则作者找不到问题
    assert to_rp_text("｜漢字《》") == "｜漢字《》"
    assert to_rp_text("{漢字|}") == "{漢字|}"
    assert to_rp_text("《ただの書名》") == "《ただの書名》"


def test_plain_book_title_is_not_treated_as_ruby():
    assert to_html("我读了《钟声与失物招领处》。") == "我读了《钟声与失物招领处》。"


# ---- Ren'Py：注音转 rp + 花括号转义（真实缺陷的回归守卫） -----------------------


def test_renpy_escapes_braces_so_scripts_do_not_break():
    """回归：过去只转义 \\ 与 "，正文里的花括号会让 Ren'Py 报"未知文本标签"。"""
    assert to_renpy_text("x { y } z") == "x {{ y }} z"


def test_renpy_renders_ruby_as_rp_not_as_tags():
    out = to_renpy_text("｜漢字《かんじ》")
    assert out == "漢字（かんじ）"
    assert "{" not in out


def test_renpy_keeps_other_text_intact():
    assert to_renpy_text("雨停了。") == "雨停了。"


# ---- ruby_marks 列举 ----------------------------------------------------------


def test_ruby_marks_lists_renderable_marks_only():
    marks = ruby_marks("｜漢字《かんじ》と{笑顔|えがお}と｜壊《》")
    assert [(m["base"], m["reading"], m["form"]) for m in marks] == [
        ("漢字", "かんじ", "bar"),
        ("笑顔", "えがお", "brace"),
    ]


def test_ruby_marks_on_empty_text():
    assert ruby_marks("") == []


# ---- 集成：注音真的进了三种导出 -------------------------------------------------
#
# 这一节才是这条工作的价值所在：渲染函数写得再对，没接进导出链路也等于没有。
# 三种导出形态不同，所以逐条断言"该出现的出现、不该泄漏的不泄漏"。


def _ruby_project():
    from app.core.project import normalize_project

    return normalize_project(
        {
            "id": "p-ruby",
            "title": "｜鐘《かね》の物語",
            "logline": "关于｜鐘《かね》的故事。",
            "chapters": [
                {
                    "id": "c1",
                    "title": "｜第一話《だいいちわ》",
                    "prose": "他在校門前站住了：｜鐘《かね》が鳴った。\n{笑顔|えがお}を見せた。",
                }
            ],
        }
    )


def test_markdown_export_emits_w3c_ruby():
    from app.core.export_text import project_to_markdown

    md = project_to_markdown(_ruby_project())
    assert "<ruby>鐘<rp>（</rp><rt>かね</rt><rp>）</rp></ruby>" in md
    assert "<ruby>笑顔<rp>（</rp><rt>えがお</rt><rp>）</rp></ruby>" in md
    # 源标记不能泄漏出去
    assert "｜鐘《かね》" not in md
    assert "{笑顔|えがお}" not in md


def test_docx_export_renders_ruby_as_rp_fallback():
    import io

    from docx import Document

    from app.core.export_text import project_to_docx

    doc = Document(io.BytesIO(project_to_docx(_ruby_project())))
    text = "\n".join(p.text for p in doc.paragraphs)
    assert "鐘（かね）" in text
    assert "笑顔（えがお）" in text
    # 源标记绝不进 Word 稿
    assert "｜鐘《かね》" not in text
    assert "{笑顔|えがお}" not in text


def test_submission_docx_renders_ruby_too():
    """投稿稿走的是 **Word 原生注音**（更详细的结构验证见 `test_docx_ruby.py`）。

    这里只钉两件事：注音真的进了文件，源标记没有泄漏。
    （`paragraph.text` 看不到原生注音——基准词在 `w:rubyBase` 里——所以断言看 XML。）
    """
    import io
    import zipfile

    from app.core.export_submission import submission_docx

    data = submission_docx(_ruby_project())
    with zipfile.ZipFile(io.BytesIO(data)) as zf:
        xml = zf.read("word/document.xml").decode("utf-8")
    assert "<w:ruby>" in xml
    assert "鐘" in xml and "かね" in xml
    assert "｜鐘《かね》" not in xml
    assert "{笑顔|えがお}" not in xml


def test_rpy_export_has_no_ruby_markers_left():
    """RPY 导出走的是 blocks（prose 要先"生成脚本"），所以这里用块工程验。"""
    from app.core.project import normalize_project
    from app.core.renpy import export_script_rpy

    vn = normalize_project(
        {
            "id": "p-rpy-ruby",
            "title": "钟声",
            "chapters": [
                {
                    "id": "c1",
                    "title": "第一章",
                    "blocks": [
                        {"type": "label", "id": "start", "name": "start"},
                        {"type": "narration", "text": "他站住了：｜鐘《かね》が鳴った。"},
                        {"type": "dialogue", "characterId": "a", "text": "{笑顔|えがお}を見せた。"},
                    ],
                }
            ],
        }
    )
    rpy = export_script_rpy(vn)
    # 注音渲染成 rp 形态，而不是留下会破坏脚本的花括号标签
    assert "鐘（かね）" in rpy
    assert "笑顔（えがお）" in rpy
    assert "{笑顔|えがお}" not in rpy
    assert "｜鐘《かね》" not in rpy


def test_rpy_export_escapes_author_braces():
    """作者正文里本来就有花括号时，导出必须转义成 {{ }}（真实缺陷的回归守卫）。"""
    from app.core.project import normalize_project
    from app.core.renpy import export_script_rpy

    vn = normalize_project(
        {
            "id": "p-brace",
            "title": "花括号",
            "chapters": [
                {
                    "id": "c1",
                    "title": "第一章",
                    "blocks": [
                        {"type": "label", "id": "start", "name": "start"},
                        {"type": "narration", "text": "他打了个字：{ 就是这么打的 }。"},
                    ],
                }
            ],
        }
    )
    rpy = export_script_rpy(vn)
    assert "{{ 就是这么打的 }}" in rpy
