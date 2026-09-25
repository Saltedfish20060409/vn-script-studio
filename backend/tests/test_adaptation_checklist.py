"""改编检查表（小说 → 视觉小说）：只报结构事实，且**不把 kinetic 当缺陷**。

依据：《文字冒险游戏设计中的沉浸式体验研究与实践》（学位论文）、《剧情交互式游戏的叙事研究》、
《视觉小说叙事逻辑的根源与变迁》（新闻传播 2022(15)）、『ノベルゲームのシナリオ作成技法』、
『キャラクター小説の作り方』——见 docs/references.md 的「视觉小说 / 轻小说实务（参考层）」。

要钉住的三件事：
1. **事实与建议分开**：每条都带 why（依据）与 action（具体改法），不是"建议优化"；
2. **没有选项不是缺陷**：kinetic 单独一条，且文案里明说这不是问题；
3. **只统计出场角色**：角色素材齐备度不能把没出场的角色也算成"缺素材"。
"""

from __future__ import annotations

from app.core.adaptation_checklist import (
    LOW_DIALOGUE_RATIO,
    TEXT_WALL_CHARS,
    build_adaptation_checklist,
    checklist_action_items,
    dominant_issue,
)
from app.core.project import normalize_project


def _project(*chapters, characters=None):
    return normalize_project(
        {
            "id": "p-adapt",
            "title": "改编",
            "characters": characters or [],
            "chapters": [
                {"id": f"c{i + 1}", "title": f"第{i + 1}章", "prose": text}
                for i, text in enumerate(chapters)
            ],
        }
    )


def _find(result, code):
    return next((i for i in result["items"] if i["code"] == code), None)


# ---- 一屏文字 -----------------------------------------------------------------


def test_text_wall_is_detected_with_paragraph_position():
    long_para = "雨停了。" * (TEXT_WALL_CHARS // 4 + 2)
    result = build_adaptation_checklist(_project(long_para + "\n「你等很久了？」"))
    item = _find(result, "text_wall")
    assert item is not None
    assert item["severity"] == "warn"
    assert item["evidence"]["count"] == 1
    sample = item["evidence"]["samples"][0]
    assert sample["paragraph"] == 1  # 第几段
    assert sample["chars"] >= TEXT_WALL_CHARS
    assert item["where"] and item["action"]


def test_dialogue_lines_are_not_text_walls():
    """整段都是对白不算"一屏文字"——对白正是 VN 的推进方式。"""
    long_dialogue = "\n".join("「这一句是台词，用来把这一段撑到很长很长。」" for _ in range(20))
    result = build_adaptation_checklist(_project(long_dialogue))
    assert _find(result, "text_wall") is None


def test_short_paragraphs_are_not_reported():
    result = build_adaptation_checklist(_project("雨停了。\n她抬头看了看天。\n「走吧。」"))
    assert _find(result, "text_wall") is None


# ---- 对白稀薄 / 分场 / 选项 ---------------------------------------------------


def test_low_dialogue_chapter_uses_ratio_and_minimum_length():
    dense = "他站在屋檐下，看雨一滴一滴落在石阶上。" * 40  # 长且几乎没对白
    result = build_adaptation_checklist(_project(dense))
    item = _find(result, "low_dialogue_chapter")
    assert item is not None
    assert item["evidence"]["chapters"][0]["dialogueRatio"] < LOW_DIALOGUE_RATIO
    # 太短的章节不参与（200 字以下样本没意义）
    tiny = build_adaptation_checklist(_project("雨停了。"))
    assert _find(tiny, "low_dialogue_chapter") is None


def test_missing_scene_markers_are_reported_with_count():
    result = build_adaptation_checklist(_project("雨停了。", "「走吧。」"))
    item = _find(result, "no_scene_markers")
    assert item is not None
    assert item["evidence"]["count"] == 2
    assert item["severity"] == "info"


def test_kinetic_book_is_described_not_blamed():
    """没有选项要**如实说明形态**，并在文案里明确"这不是问题"。"""
    result = build_adaptation_checklist(_project("雨停了。", "「走吧。」"))
    item = _find(result, "kinetic_book")
    assert item is not None
    assert "这不是问题" in item["why"]
    assert "kinetic" in item["why"]
    # 不该同时出现"必须有选项"这类口吻
    assert "必须" not in item["action"]


# ---- 角色素材 -----------------------------------------------------------------


def test_character_material_only_counts_appearing_characters():
    characters = [
        {"id": "c1", "displayName": "雨宫澪", "defineName": "mio"},  # 出场但没素材
        {"id": "c2", "displayName": "佐仓", "defineName": "sakura"},  # 没出场
        {
            "id": "c3",
            "displayName": "铃兰",
            "defineName": "rin",
            "voice": "短句",
        },  # 出场且有素材
    ]
    texts = "雨宫澪站在门口。铃兰抬起头。"
    result = build_adaptation_checklist(_project(texts, characters=characters))
    item = _find(result, "character_material_thin")
    assert item is not None
    names = [c["name"] for c in item["evidence"]["characters"]]
    assert names == ["雨宫澪"], "只有出场且没素材的角色才算"
    assert item["evidence"]["appearing"] == 2
    assert "佐仓" not in str(item["evidence"])


def test_single_char_names_are_documented_as_not_matched():
    """单字名（「澪」）太容易撞上普通用词，所以不参与出场匹配——这条局限要写在报告里。"""
    characters = [{"id": "c1", "displayName": "澪", "defineName": "mio"}]
    result = build_adaptation_checklist(_project("澪站在门口。", characters=characters))
    assert _find(result, "character_material_thin") is None
    assert any("单字名" in n for n in result["notes"])


def test_characters_with_corpus_or_mind_are_not_thin():
    characters = [
        {
            "id": "c1",
            "displayName": "雨宫澪",
            "defineName": "mio",
            "voiceMind": "她的思维卡",
        }
    ]
    result = build_adaptation_checklist(_project("雨宫澪站在门口。", characters=characters))
    assert _find(result, "character_material_thin") is None


# ---- 报告口径与边界 -----------------------------------------------------------


def test_report_states_limits_and_sources():
    result = build_adaptation_checklist(_project("雨停了。"))
    assert any("不评" in n for n in result["notes"])
    assert any("kinetic" in n for n in result["notes"])
    assert any("docs/references.md" in n for n in result["notes"])


def test_empty_project_does_not_crash_and_only_reports_info():
    """空工程不炸；已有的自动补章只会产生 info（没有 warn 就没有"要动手"的事）。

    注意 `normalize_project` 会给空工程自动补一章，所以"没有章节"这种情况不成立——
    这里断言的是"不炸 + 不误报 warn"。
    """
    result = build_adaptation_checklist(normalize_project({"id": "p", "title": "空"}))
    assert result["counts"]["warn"] == 0
    assert checklist_action_items(result) == []
    assert dominant_issue(result) is None
    assert all(i["severity"] == "info" for i in result["items"])


def test_action_items_only_include_warnings():
    long_para = "雨停了。" * 100
    result = build_adaptation_checklist(_project(long_para))
    actions = checklist_action_items(result)
    assert actions and all(i["severity"] == "warn" for i in actions)
    assert dominant_issue(result) == actions[0]["title"]


def test_per_chapter_readings_are_returned():
    result = build_adaptation_checklist(_project("雨停了。\n「走吧。」", "「又来了一句话。」"))
    rows = result["perChapter"]
    assert [r["chapterOrdinal"] for r in rows] == [1, 2]
    assert rows[0]["chars"] > 0
    assert rows[0]["dialogueRatio"] is not None
