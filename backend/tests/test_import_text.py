"""导入解析：分章、分卷、按段落成块（纯函数，不碰数据库）。

这三件事都是"打开小说文件"能不能用的前提：原来整本书进一个章节、每行一个块。
"""

from __future__ import annotations

from app.core.import_text import (
    _blocks_from_lines,
    _is_heading,
    _is_volume_heading,
    project_from_plain_text,
)


def _text(*lines: str) -> str:
    return "\n".join(lines)


# ---------------------------------------------------------------------------
# 标题识别
# ---------------------------------------------------------------------------


def test_headings_are_recognized():
    for line in ["第一章", "第一章 雨", "第 12 章", "第十二回", "第三节", "Chapter 3", "第2卷", "序章", "楔子", "尾声"]:
        assert _is_heading(line), line


def test_prose_lines_are_not_headings():
    # 正文里出现"第一章"三个字，但整行很长 → 不能当标题（否则一章被切碎）
    assert not _is_heading("第一章里他写道，那天雨很大，他站在站台上一句话也没有说，只是看着列车远去。")
    assert not _is_heading("他合上第一章。")
    assert not _is_heading("")


def test_volume_heading_detected_separately():
    assert _is_volume_heading("第一卷 春")
    assert _is_volume_heading("第 2 卷")
    assert not _is_volume_heading("第一章 春")
    assert not _is_volume_heading("")


# ---------------------------------------------------------------------------
# 分章
# ---------------------------------------------------------------------------


def test_split_into_chapters():
    project = project_from_plain_text(
        "雨城",
        _text(
            "第一章 站台",
            "雨落在站台上。",
            "",
            "他慢慢抬起手。",
            "第二章 归途",
            "末班车开走了。",
        ),
    )
    assert [c.title for c in project.chapters] == ["第一章 站台", "第二章 归途"]
    assert len(project.volumes or []) == 0


def test_text_before_the_first_heading_goes_into_chapter_one():
    """很多小说开头是书名/作者/引子，不该被丢掉。"""
    project = project_from_plain_text(
        "雨城",
        _text("雨城", "作者：某人", "第一章 站台", "雨落在站台上。"),
    )
    assert len(project.chapters) == 1
    texts = [b.get("text", "") for b in project.chapters[0].blocks]
    assert any("作者：某人" in t for t in texts)
    assert any("雨落在站台上。" in t for t in texts)


def test_no_headings_becomes_a_single_chapter():
    project = project_from_plain_text("一段稿", _text("就一段话。", "", "又一段。"))
    assert len(project.chapters) == 1
    assert project.chapters[0].title == "导入稿"


# ---------------------------------------------------------------------------
# 分卷（文件里有「第一卷」就建卷）
# ---------------------------------------------------------------------------


def test_volume_headings_create_volumes_and_assign_chapters():
    project = project_from_plain_text(
        "长篇",
        _text(
            "第一卷 春",
            "第一章",
            "春天的雨。",
            "第二章",
            "春天的风。",
            "第二卷 夏",
            "第一章",
            "夏天很热。",
        ),
    )
    assert [v.title for v in project.volumes or []] == ["第一卷 春", "第二卷 夏"]
    vol1, vol2 = project.volumes or []
    assert [c.volumeId for c in project.chapters] == [vol1.id, vol1.id, vol2.id]
    # 章标题在同一卷里可以重复（小说常见），所以直接看标题
    assert [c.title for c in project.chapters] == ["第一章", "第二章", "第一章"]


# ---------------------------------------------------------------------------
# 成块：段落合并 + 对话行
# ---------------------------------------------------------------------------


def test_paragraph_lines_merge_into_one_block():
    blocks = _blocks_from_lines(["第一行", "第二行", "", "另起一段"])
    assert [b["type"] for b in blocks] == ["narration", "narration"]
    assert blocks[0]["text"] == "第一行\n第二行"
    assert blocks[1]["text"] == "另起一段"


def test_dialogue_lines_keep_their_own_block():
    blocks = _blocks_from_lines(["雨落在站台上。", "林夏：伞借你。", "他接过来。"])
    assert [b["type"] for b in blocks] == ["narration", "narration", "narration"]
    assert blocks[1]["text"] == "林夏：伞借你。"
    # 前后两段正文各自成块（对话把段落切开了）
    assert blocks[0]["text"] == "雨落在站台上。"
    assert blocks[2]["text"] == "他接过来。"


def test_imported_chapter_has_a_start_label_and_comment():
    project = project_from_plain_text("雨城", _text("第一章", "雨落在站台上。"))
    types = [b["type"] for b in project.chapters[0].blocks]
    assert types[0] == "label"
    assert "comment" in types
    assert types[-1] == "narration"


def test_renpy_script_import_still_goes_to_a_raw_block():
    project = project_from_plain_text("脚本", _text('label start:', '    "你好"', "    return"))
    assert len(project.chapters) == 1
    assert project.chapters[0].title == "导入稿"
    types = [b["type"] for b in project.chapters[0].blocks]
    assert "raw" in types
