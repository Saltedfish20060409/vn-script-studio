"""前情提要：范围解析与提示词拼装（纯函数，不碰数据库、不调模型）。"""

from __future__ import annotations

from app.core.project import normalize_project
from app.core.recap import (
    build_recap_messages,
    clean_recap_text,
    resolve_recap_targets,
)


def _project(chapters, volumes=None):
    return normalize_project(
        {
            "id": "p1",
            "title": "测试",
            "chapters": chapters,
            "volumes": volumes or [],
        }
    )


def _ch(ch_id: str, title: str, volume_id: str | None = None, synopsis: str = ""):
    item = {"id": ch_id, "title": title, "blocks": [], "prose": ""}
    if volume_id:
        item["volumeId"] = volume_id
    if synopsis:
        item["synopsis"] = synopsis
    return item


# ---------------------------------------------------------------------------
# 范围解析
# ---------------------------------------------------------------------------


def test_before_a_volume_covers_everything_earlier():
    p = _project(
        [
            _ch("c1", "一", "v1"),
            _ch("c2", "二", "v1"),
            _ch("c3", "三", "v2"),
            _ch("c4", "四", "v2"),
        ],
        [{"id": "v1", "title": "第一卷"}, {"id": "v2", "title": "第二卷"}],
    )
    ids, label, err = resolve_recap_targets(p, volume_id="v2", mode="before", up_to_chapter_id=None)
    assert err is None
    assert ids == ["c1", "c2"]
    assert "第二卷" in label and "2 章" in label


def test_whole_volume_mode():
    p = _project(
        [_ch("c1", "一", "v1"), _ch("c2", "二", "v2"), _ch("c3", "三", "v2")],
        [{"id": "v1", "title": "第一卷"}, {"id": "v2", "title": "第二卷"}],
    )
    ids, label, err = resolve_recap_targets(p, volume_id="v2", mode="volume", up_to_chapter_id=None)
    assert err is None
    assert ids == ["c2", "c3"]
    assert "第二卷" in label


def test_first_volume_has_nothing_before_it():
    p = _project([_ch("c1", "一", "v1")], [{"id": "v1", "title": "第一卷"}])
    ids, _, err = resolve_recap_targets(p, volume_id="v1", mode="before", up_to_chapter_id=None)
    assert ids == []
    assert err and "第一卷" in err


def test_unknown_volume_is_reported():
    p = _project([_ch("c1", "一", "v1")], [{"id": "v1", "title": "第一卷"}])
    _, _, err = resolve_recap_targets(p, volume_id="v-gone", mode="before", up_to_chapter_id=None)
    assert err and "不存在" in err


def test_without_volumes_it_recaps_up_to_the_last_chapter():
    """不分卷的作品也要能用：回述"写到现在"之前的内容。"""
    p = _project([_ch("c1", "一"), _ch("c2", "二"), _ch("c3", "三")])
    ids, label, err = resolve_recap_targets(p, volume_id=None, mode="before", up_to_chapter_id=None)
    assert err is None
    assert ids == ["c1", "c2"]
    assert "3" not in label  # 标签里是"之前的 2 章"
    assert "2 章" in label


def test_up_to_a_specific_chapter():
    p = _project([_ch("c1", "一"), _ch("c2", "二"), _ch("c3", "三")])
    ids, _, err = resolve_recap_targets(p, volume_id=None, mode="before", up_to_chapter_id="c3")
    assert err is None
    assert ids == ["c1", "c2"]
    # 指到第一章时前面没有内容
    _, _, err2 = resolve_recap_targets(p, volume_id=None, mode="before", up_to_chapter_id="c1")
    assert err2


def test_single_chapter_project_cannot_recap():
    p = _project([_ch("c1", "一")])
    _, _, err = resolve_recap_targets(p, volume_id=None, mode="before", up_to_chapter_id=None)
    assert err and "至少" in err


def test_volume_mode_without_volume_id_is_rejected():
    p = _project([_ch("c1", "一")])
    _, _, err = resolve_recap_targets(p, volume_id=None, mode="volume", up_to_chapter_id=None)
    assert err and "volume_id" in err


# ---------------------------------------------------------------------------
# 提示词
# ---------------------------------------------------------------------------


def test_prompt_carries_scope_chapters_and_foreshadows():
    messages = build_recap_messages(
        target_label="「第二卷」之前的 3 章",
        chapter_notes=[
            {"title": "第一章", "summary": "林越在陌生身体里醒来。", "closeHook": "他听见楼下有人喊他的名字。"},
            {"title": "第二章", "summary": "他确认自己顶替了另一个人。", "closeHook": ""},
        ],
        archive_notes=["前 5 章的连续性要点：……"],
        foreshadows=["锁骨上的烫痕来历未明"],
        ending_tail="他收回手，不敢再碰。",
    )
    system = messages[0]["content"]
    user = messages[1]["content"]
    assert "前情提要" in system
    assert "尚未收回的线索" in system
    assert "「第二卷」之前的 3 章" in user
    assert "林越在陌生身体里醒来。" in user
    assert "他听见楼下有人喊他的名字。" in user  # 收束钩子也要给模型
    assert "锁骨上的烫痕来历未明" in user
    assert "他收回手，不敢再碰。" in user


def test_prompt_clips_very_long_material():
    messages = build_recap_messages(
        target_label="全书",
        chapter_notes=[{"title": "第 X 章", "summary": "字" * 5000, "closeHook": ""}],
    )
    user = messages[1]["content"]
    assert "字" * 221 not in user  # 单章摘要被截到 220 字
    assert "字" * 100 in user


def test_clean_recap_text_strips_wrappers():
    assert clean_recap_text("前情提要：他把手举到眼前。") == "他把手举到眼前。"
    assert clean_recap_text("```\n他把手举到眼前。\n```") == "他把手举到眼前。"
    assert clean_recap_text("  他把手举到眼前。  ") == "他把手举到眼前。"
