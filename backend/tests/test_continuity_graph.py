"""长程一致性图检查的测试。

这些断言锁住的是**语义**，不是实现细节：

- 断链与坏引用（说话人、关系端点、章节引用）一律 error：它们是硬缺陷，
  导出或检索时必然出问题；
- 启发式判断（死亡后还有戏、未知地点图）一律 warn 且必须自报"启发式"；
- **正常项目必须零 finding** —— 静态检查一旦误报，作者就会把它整体关掉，
  那时它连真问题也报不出来；
- 拿不准的情况只能进 `summary["unknown"]` 计数，不能进 `findings`。
"""

from __future__ import annotations

import json

from app.core.continuity_graph import analyze_continuity
from app.core.project import normalize_project
from app.domain.types import SceneChapter

ALL_CHECK_CODES = {
    "unknown_speaker",
    "dangling_character_link",
    "dangling_location_link",
    "alias_collision",
    "unused_character_card",
    "unknown_location_tag",
    "timeline_bad_ref",
    "timeline_order_conflict",
    "duplicate_timeline_event",
    "death_then_speaks",
}


# ------------------------------------------------------------------- 夹具


def _char(
    cid: str,
    define: str,
    display: str,
    aliases: list[str] | None = None,
    image_tag: str | None = None,
    bio: str | None = None,
) -> dict:
    card: dict = {"id": cid, "defineName": define, "displayName": display}
    if aliases:
        card["aliases"] = aliases
    if image_tag:
        card["imageTag"] = image_tag
    if bio:
        card["bio"] = bio
    return card


def _chapter(cid: str, title: str, blocks: list, prose: str | None = None) -> dict:
    chapter: dict = {"id": cid, "title": title, "blocks": blocks}
    if prose is not None:
        chapter["prose"] = prose
    return chapter


def _label(name: str) -> dict:
    return {"type": "label", "id": name, "name": name}


def _dialogue(cid: str, text: str) -> dict:
    return {"type": "dialogue", "characterId": cid, "text": text}


def _narration(text: str) -> dict:
    return {"type": "narration", "text": text}


def _scene(image: str) -> dict:
    return {"type": "scene", "image": image}


def _show(image: str) -> dict:
    return {"type": "show", "image": image}


def _event(
    eid: str,
    title: str,
    chapter_ref: str | None,
    order: float = 1,
    summary: str | None = None,
) -> dict:
    event: dict = {"id": eid, "title": title, "chapterRef": chapter_ref, "order": order}
    if summary is not None:
        event["summary"] = summary
    return event


def _project(**overrides: object):
    raw: dict = {
        "id": "p1",
        "title": "一致性测试",
        "characters": [],
        "chapters": [],
        "locations": [],
        "locationLinks": [],
        "characterLinks": [],
        "timeline": [],
        "loreEntries": [],
    }
    raw.update(overrides)
    return normalize_project(raw)


def _codes(result: dict) -> list[str]:
    return [f["code"] for f in result["findings"]]


def _of(result: dict, code: str) -> list[dict]:
    return [f for f in result["findings"] if f["code"] == code]


def _healthy_project():
    """正常项目：角色都在卡里、地点都声明过、时间线顺序正确。"""
    return _project(
        characters=[
            _char("ch-lin", "linxia", "林夏", image_tag="linxia"),
            _char("ch-zhou", "zhou", "周野"),
        ],
        locations=[
            {"id": "loc-station", "name": "车站", "imageTag": "bg station_night"},
            {"id": "loc-home", "name": "家", "imageTag": "bg home"},
        ],
        locationLinks=[
            {"id": "ll1", "fromId": "loc-station", "toId": "loc-home", "relation": "leads_to"}
        ],
        characterLinks=[{"id": "cl1", "fromId": "ch-lin", "toId": "ch-zhou", "label": "同学"}],
        timeline=[
            _event("t1", "车站告别", "c1", 1),
            _event("t2", "归家", "c2", 2),
        ],
        chapters=[
            _chapter(
                "c1",
                "雪夜",
                [
                    _label("start"),
                    _scene("bg station_night"),
                    _show("linxia sad"),
                    _dialogue("ch-lin", "你终于来了。"),
                    _narration("周野站在她身后。"),
                    {"type": "return"},
                ],
            ),
            _chapter(
                "c2",
                "归途",
                [
                    _label("home"),
                    _scene("bg home"),
                    _dialogue("ch-zhou", "路上小心。"),
                    {"type": "return"},
                ],
            ),
        ],
    )


# ------------------------------------------------------- ① 说话人（error）


def test_unknown_speaker_reports_id_missing_from_cards():
    project = _project(
        characters=[_char("ch-lin", "linxia", "林夏")],
        locations=[{"id": "loc1", "name": "车站", "imageTag": "bg station_night"}],
        chapters=[
            _chapter(
                "c1",
                "雪夜",
                [
                    _label("start"),
                    _scene("bg station_night"),
                    _dialogue("ch-lin", "你终于来了。"),
                    _dialogue("ch-ghost", "我来接你。"),
                    {"type": "return"},
                ],
            )
        ],
    )
    result = analyze_continuity(project)
    found = _of(result, "unknown_speaker")
    assert len(found) == 1
    assert found[0]["severity"] == "error"
    assert found[0]["chapterId"] == "c1"
    assert found[0]["label"] == "start"
    assert "ch-ghost" in found[0]["message"]
    assert "我来接你" in found[0]["message"]  # 证据要带原句
    assert result["counts"]["pass"] is False


def test_speaker_stored_as_define_name_is_not_reported():
    """导出器本身就按 id 或 defineName 找人，这里不能把合法说话人报成不存在。"""
    project = _project(
        characters=[_char("ch-lin", "linxia", "林夏")],
        chapters=[_chapter("c1", "雪夜", [_label("start"), _dialogue("linxia", "嗯。")])],
    )
    assert _codes(analyze_continuity(project)) == []


def test_dialogue_without_any_speaker_is_reported():
    project = _project(
        characters=[_char("ch-lin", "linxia", "林夏")],
        chapters=[
            _chapter(
                "c1",
                "雪夜",
                [_label("start"), _dialogue("ch-lin", "嗯。"), _dialogue("", "……")],
            )
        ],
    )
    found = _of(analyze_continuity(project), "unknown_speaker")
    assert len(found) == 1
    assert "没有指定说话人" in found[0]["message"]


def test_dialogue_inside_menu_choice_body_is_scanned():
    """菜单选项正文里的台词也是台词——少算这一层就会漏报。"""
    project = _project(
        chapters=[
            _chapter(
                "c2",
                "分岔",
                [
                    _label("start"),
                    {
                        "type": "menu",
                        "id": "m1",
                        "choices": [
                            {"text": "留下", "blocks": [_dialogue("ch-x", "我不走。")]},
                            {"text": "离开"},
                        ],
                    },
                ],
            )
        ],
    )
    found = _of(analyze_continuity(project), "unknown_speaker")
    assert len(found) == 1
    assert found[0]["chapterId"] == "c2"
    assert found[0]["label"] == "start"
    assert "我不走" in found[0]["message"]


def test_dialogue_inside_if_branch_body_is_scanned():
    project = _project(
        chapters=[
            _chapter(
                "c3",
                "条件",
                [
                    _label("start"),
                    {
                        "type": "if",
                        "branches": [
                            {
                                "condition": "flag == 1",
                                "blocks": [_dialogue("ch-y", "果然如此。")],
                            }
                        ],
                    },
                ],
            )
        ],
        variables=[{"id": "v1", "name": "flag", "key": "flag", "type": "number", "value": 1}],
    )
    found = _of(analyze_continuity(project), "unknown_speaker")
    assert len(found) == 1
    assert "果然如此" in found[0]["message"]


# ----------------------------------------------------- ②③ 断链（error）


def test_dangling_character_link_reports_missing_end():
    project = _project(
        characters=[_char("ch-lin", "linxia", "林夏"), _char("ch-zhou", "zhou", "周野")],
        characterLinks=[
            {"id": "l1", "fromId": "ch-lin", "toId": "ch-zhou", "label": "同学"},
            {"id": "l2", "fromId": "ch-lin", "toId": "ch-gone", "label": "旧友"},
        ],
        chapters=[
            _chapter(
                "c1",
                "雪夜",
                [_dialogue("ch-lin", "嗯。"), _dialogue("ch-zhou", "哦。")],
            )
        ],
    )
    found = _of(analyze_continuity(project), "dangling_character_link")
    assert len(found) == 1
    assert found[0]["severity"] == "error"
    assert "ch-gone" in found[0]["message"]
    assert "旧友" in found[0]["message"]


def test_character_link_between_known_cards_is_clean():
    project = _project(
        characters=[_char("ch-lin", "linxia", "林夏"), _char("ch-zhou", "zhou", "周野")],
        characterLinks=[{"id": "l1", "fromId": "ch-lin", "toId": "ch-zhou", "label": "同学"}],
        chapters=[
            _chapter(
                "c1",
                "雪夜",
                [_dialogue("ch-lin", "嗯。"), _dialogue("ch-zhou", "哦。")],
            )
        ],
    )
    assert _of(analyze_continuity(project), "dangling_character_link") == []


def test_dangling_location_link_reports_missing_end():
    project = _project(
        locations=[{"id": "loc1", "name": "车站"}, {"id": "loc2", "name": "家"}],
        locationLinks=[
            {"id": "ll1", "fromId": "loc1", "toId": "loc2", "relation": "leads_to"},
            {"id": "ll2", "fromId": "loc1", "toId": "loc-void", "relation": "adjacent"},
        ],
    )
    found = _of(analyze_continuity(project), "dangling_location_link")
    assert len(found) == 1
    assert found[0]["severity"] == "error"
    assert "loc-void" in found[0]["message"]


def test_location_link_between_known_locations_is_clean():
    project = _project(
        locations=[{"id": "loc1", "name": "车站"}, {"id": "loc2", "name": "家"}],
        locationLinks=[
            {"id": "ll1", "fromId": "loc1", "toId": "loc2", "relation": "leads_to"}
        ],
    )
    assert analyze_continuity(project)["findings"] == []


# --------------------------------------------------- ④ 撞名（error）


def test_alias_collision_reports_cross_character_alias():
    project = _project(
        characters=[
            _char("ch-lin", "linxia", "林夏", aliases=["小夏"]),
            _char("ch-two", "xia2", "小夏"),
        ],
        chapters=[
            _chapter(
                "c1",
                "雪夜",
                [_dialogue("ch-lin", "嗯。"), _dialogue("ch-two", "哦。")],
            )
        ],
    )
    found = _of(analyze_continuity(project), "alias_collision")
    assert len(found) == 1
    assert found[0]["severity"] == "error"
    assert "小夏" in found[0]["message"]
    assert "林夏" in found[0]["message"]  # 要说清是哪两个角色撞了


def test_display_name_colliding_with_other_card_define_name_is_reported():
    project = _project(
        characters=[
            _char("ch-lin", "linxia", "林夏"),
            _char("ch-two", "林夏", "周野"),
        ],
        chapters=[
            _chapter(
                "c1",
                "雪夜",
                [_dialogue("ch-lin", "嗯。"), _dialogue("ch-two", "哦。")],
            )
        ],
    )
    found = _of(analyze_continuity(project), "alias_collision")
    assert len(found) == 1
    assert "林夏" in found[0]["message"]


def test_character_repeating_its_own_name_is_not_a_collision():
    """同一个角色的显示名与别名相同不是问题，只有跨角色共用才是。"""
    project = _project(
        characters=[_char("ch-lin", "linxia", "林夏", aliases=["林夏", "linxia"])],
        chapters=[_chapter("c1", "雪夜", [_dialogue("ch-lin", "嗯。")])],
    )
    assert _of(analyze_continuity(project), "alias_collision") == []


def test_distinct_names_are_not_a_collision():
    project = _project(
        characters=[
            _char("ch-lin", "linxia", "林夏", aliases=["小夏"]),
            _char("ch-zhou", "zhou", "周野", aliases=["野哥"]),
        ],
        chapters=[
            _chapter(
                "c1",
                "雪夜",
                [_dialogue("ch-lin", "嗯。"), _dialogue("ch-zhou", "哦。")],
            )
        ],
    )
    assert analyze_continuity(project)["findings"] == []


# --------------------------------------------- ⑤ 闲置角色卡（info）


def test_unused_character_card_is_info_not_failure():
    project = _project(
        characters=[
            _char("ch-lin", "linxia", "林夏"),
            _char("ch-ghost", "ghostcard", "幽灵设定"),
        ],
        chapters=[_chapter("c1", "雪夜", [_label("start"), _dialogue("ch-lin", "走吧。")])],
    )
    result = analyze_continuity(project)
    found = _of(result, "unused_character_card")
    assert len(found) == 1
    assert found[0]["severity"] == "info"
    assert "幽灵设定" in found[0]["message"]
    assert result["counts"]["pass"] is True  # info 不是失败


def test_character_mentioned_only_by_alias_is_not_unused():
    project = _project(
        characters=[
            _char("ch-lin", "linxia", "林夏"),
            _char("ch-shen", "shenyan", "沈砚", aliases=["阿砚"]),
        ],
        chapters=[
            _chapter(
                "c1",
                "雪夜",
                [_label("start"), _dialogue("ch-lin", "谁在外面？"), _narration("阿砚站在门口。")],
            )
        ],
    )
    assert _of(analyze_continuity(project), "unused_character_card") == []


def test_character_mentioned_in_prose_manuscript_is_not_unused():
    project = _project(
        characters=[_char("ch-zhou", "zhou", "周野")],
        chapters=[
            _chapter(
                "c1",
                "雪夜",
                [_label("start")],
                prose="周野推开门，雪灌进来。",
            )
        ],
    )
    assert _of(analyze_continuity(project), "unused_character_card") == []


def test_speaking_character_is_never_unused():
    project = _project(
        characters=[_char("ch-lin", "linxia", "林夏")],
        chapters=[_chapter("c1", "雪夜", [_dialogue("ch-lin", "嗯。")])],
    )
    assert _of(analyze_continuity(project), "unused_character_card") == []


# ------------------------------------------- ⑥ 未知地点图（warn）


def test_unknown_location_tag_warns_for_undeclared_scene_image():
    project = _project(
        locations=[{"id": "loc1", "name": "车站", "imageTag": "bg station_night"}],
        chapters=[
            _chapter(
                "c1",
                "雪夜",
                [_label("start"), _scene("bg station_night"), _scene("bg roof_void")],
            )
        ],
    )
    found = _of(analyze_continuity(project), "unknown_location_tag")
    assert len(found) == 1
    assert found[0]["severity"] == "warn"
    assert "bg roof_void" in found[0]["message"]
    assert found[0]["chapterId"] == "c1"


def test_scene_images_matching_location_tags_are_clean():
    project = _project(
        locations=[
            {"id": "loc1", "name": "车站", "imageTag": "bg station_night"},
            {"id": "loc2", "name": "旧校舍", "imageTag": "bg old_school"},
        ],
        chapters=[
            _chapter(
                "c1",
                "雪夜",
                [_label("start"), _scene("bg station_night"), _scene("bg old_school")],
            )
        ],
    )
    assert _of(analyze_continuity(project), "unknown_location_tag") == []


def test_show_of_character_sprite_is_not_treated_as_location_image():
    """立绘写错是资产审计的事，不能在这里报成"未知地点"。"""
    project = _project(
        characters=[_char("ch-lin", "linxia", "林夏", image_tag="linxia")],
        locations=[{"id": "loc1", "name": "车站", "imageTag": "bg station_night"}],
        chapters=[
            _chapter(
                "c1",
                "雪夜",
                [
                    _label("start"),
                    _scene("bg station_night"),
                    _show("linxia sad"),
                    _dialogue("ch-lin", "嗯。"),
                ],
            )
        ],
    )
    result = analyze_continuity(project)
    assert result["findings"] == []
    assert result["summary"]["unknown"].get("showImageNotClassified", 0) == 0


def test_show_with_background_prefix_is_checked_like_a_scene():
    project = _project(
        locations=[{"id": "loc1", "name": "车站", "imageTag": "bg station_night"}],
        chapters=[_chapter("c1", "雪夜", [_label("start"), _show("bg nowhere")])],
    )
    found = _of(analyze_continuity(project), "unknown_location_tag")
    assert len(found) == 1
    assert "bg nowhere" in found[0]["message"]


def test_project_without_location_table_skips_the_check():
    """没有地点表时没有任何权威可比对，整条检查跳过并只记数（避免一片噪音）。"""
    project = _project(
        chapters=[_chapter("c1", "雪夜", [_label("start"), _scene("bg station_night")])],
    )
    result = analyze_continuity(project)
    assert _of(result, "unknown_location_tag") == []
    assert result["summary"]["unknown"]["locationTableEmpty"] == 1


# ------------------------------------------------ ⑦⑧⑨ 时间线（error/warn）


def test_timeline_bad_ref_is_error():
    project = _project(
        chapters=[_chapter("c1", "雪夜", [_label("start"), _narration("雨。")])],
        timeline=[_event("t1", "告别", "c-void", 1)],
    )
    found = _of(analyze_continuity(project), "timeline_bad_ref")
    assert len(found) == 1
    assert found[0]["severity"] == "error"
    assert "c-void" in found[0]["message"]


def test_timeline_valid_ref_is_clean():
    project = _project(
        chapters=[_chapter("c1", "雪夜", [_label("start"), _narration("雨。")])],
        timeline=[_event("t1", "告别", "c1", 1)],
    )
    assert analyze_continuity(project)["findings"] == []


def test_timeline_order_conflict_warns_when_chapter_and_order_disagree():
    project = _project(
        characters=[_char("ch-lin", "linxia", "林夏")],
        chapters=[
            _chapter("c1", "第一章", [_dialogue("ch-lin", "一。")]),
            _chapter("c2", "第二章", [_narration("二。")]),
            _chapter("c3", "第三章", [_narration("三。")]),
        ],
        timeline=[
            _event("t1", "早章大 order", "c1", 5),
            _event("t2", "晚章小 order", "c3", 2),
        ],
    )
    found = _of(analyze_continuity(project), "timeline_order_conflict")
    assert len(found) == 1
    assert found[0]["severity"] == "warn"
    assert "早章大 order" in found[0]["message"]
    assert "晚章小 order" in found[0]["message"]


def test_timeline_order_matching_chapter_sequence_is_clean():
    project = _project(
        chapters=[
            _chapter("c1", "第一章", [_narration("一。")]),
            _chapter("c2", "第二章", [_narration("二。")]),
            _chapter("c3", "第三章", [_narration("三。")]),
        ],
        timeline=[
            _event("t1", "一", "c1", 1),
            _event("t2", "二", "c2", 2),
            _event("t3", "三", "c3", 3),
        ],
    )
    assert _of(analyze_continuity(project), "timeline_order_conflict") == []


def test_same_order_in_same_chapter_is_not_a_conflict():
    project = _project(
        chapters=[_chapter("c1", "第一章", [_narration("一。")])],
        timeline=[_event("t1", "一", "c1", 1), _event("t2", "二", "c1", 1)],
    )
    assert _of(analyze_continuity(project), "timeline_order_conflict") == []


def test_duplicate_timeline_event_warns():
    project = _project(
        chapters=[_chapter("c1", "第一章", [_narration("一。")])],
        timeline=[
            _event("t1", "葬礼", "c1", 1),
            _event("t2", " 葬礼 ", "c1", 2),
        ],
    )
    found = _of(analyze_continuity(project), "duplicate_timeline_event")
    assert len(found) == 1
    assert found[0]["severity"] == "warn"
    assert "葬礼" in found[0]["message"]
    assert "2 次" in found[0]["message"]


def test_same_title_in_different_chapters_is_not_duplicate():
    """同名但不同章是两条事件（每章都有"战斗"很常见），不能报重复。"""
    project = _project(
        chapters=[
            _chapter("c1", "第一章", [_narration("一。")]),
            _chapter("c2", "第二章", [_narration("二。")]),
        ],
        timeline=[_event("t1", "战斗", "c1", 1), _event("t2", "战斗", "c2", 2)],
    )
    assert _of(analyze_continuity(project), "duplicate_timeline_event") == []


# ------------------------------------ ⑩ 死亡后还有戏（warn，启发式）


def test_death_then_speaks_warns_and_marks_heuristic():
    project = _project(
        characters=[_char("ch-lin", "linxia", "林夏")],
        chapters=[
            _chapter("c1", "葬礼", [_label("start"), _narration("林夏的葬礼在雨里结束。")]),
            _chapter("c2", "归途", [_label("home"), _dialogue("ch-lin", "我回来了。")]),
        ],
        timeline=[_event("t1", "林夏的葬礼", "c1", 1, summary="林夏去世，众人送别")],
    )
    result = analyze_continuity(project)
    found = _of(result, "death_then_speaks")
    assert len(found) == 1
    assert found[0]["severity"] == "warn"
    assert "启发式" in found[0]["message"]  # 必须在文案里自报是启发式
    assert "林夏" in found[0]["message"]
    assert "第 2 章" in found[0]["message"]
    assert "第 1 章" in found[0]["message"]
    assert "我回来了" in found[0]["message"]
    assert found[0]["chapterId"] == "c2"
    assert result["counts"]["pass"] is True  # warn 不是失败


def test_death_without_later_dialogue_is_clean():
    project = _project(
        characters=[_char("ch-lin", "linxia", "林夏")],
        chapters=[
            _chapter("c1", "葬礼", [_label("start"), _dialogue("ch-lin", "别哭。")]),
            _chapter("c2", "归途", [_narration("雪停了。")]),
        ],
        timeline=[_event("t1", "林夏的葬礼", "c1", 1, summary="林夏去世")],
    )
    assert _of(analyze_continuity(project), "death_then_speaks") == []


def test_dialogue_before_death_chapter_is_not_reported():
    project = _project(
        characters=[_char("ch-lin", "linxia", "林夏")],
        chapters=[
            _chapter("c1", "第一章", [_dialogue("ch-lin", "我先走了。")]),
            _chapter("c2", "葬礼", [_narration("林夏去世。")]),
        ],
        timeline=[_event("t1", "葬礼", "c2", 2, summary="林夏去世")],
    )
    assert _of(analyze_continuity(project), "death_then_speaks") == []


def test_death_evidence_without_chapter_is_counted_not_reported():
    """事件没定位到章节 → 判不了先后，宁可不报，只进 unknown。"""
    project = _project(
        characters=[_char("ch-lin", "linxia", "林夏")],
        chapters=[_chapter("c1", "第一章", [_dialogue("ch-lin", "我在。")])],
        timeline=[_event("t1", "林夏去世", None, 1, summary="林夏已故")],
    )
    result = analyze_continuity(project)
    assert _of(result, "death_then_speaks") == []
    assert result["summary"]["unknown"]["deathEvidenceWithoutChapter"] == 1


def test_death_marker_only_in_card_bio_is_counted_not_reported():
    project = _project(
        characters=[_char("ch-lin", "linxia", "林夏", bio="已故，生前是钟表匠。")],
        chapters=[_chapter("c1", "第一章", [_dialogue("ch-lin", "我在。")])],
    )
    result = analyze_continuity(project)
    assert _of(result, "death_then_speaks") == []
    assert result["summary"]["unknown"]["deathMentionedInCardOnly"] == 1


def test_lore_entry_with_chapter_link_can_locate_death():
    project = _project(
        characters=[_char("ch-shen", "shenyan", "沈砚")],
        chapters=[
            _chapter("c1", "雪夜", [_narration("雪落在城墙上。")]),
            _chapter("c2", "春归", [_dialogue("ch-shen", "我回来了。")]),
        ],
        loreEntries=[
            {
                "id": "lore1",
                "title": "沈砚之死",
                "body": "沈砚牺牲于雪夜，尸骨未还。",
                "links": [{"toType": "chapter", "toId": "c1"}],
            }
        ],
    )
    found = _of(analyze_continuity(project), "death_then_speaks")
    assert len(found) == 1
    assert "沈砚" in found[0]["message"]
    assert "设定条目" in found[0]["message"]


def test_death_marker_for_another_character_does_not_trigger():
    """死亡记录里的名字必须是被查的那个角色，否则会张冠李戴。"""
    project = _project(
        characters=[
            _char("ch-lin", "linxia", "林夏"),
            _char("ch-zhou", "zhou", "周野"),
        ],
        chapters=[
            _chapter("c1", "葬礼", [_narration("周野死了。")]),
            _chapter(
                "c2",
                "归途",
                [_dialogue("ch-lin", "我回来了。"), _dialogue("ch-zhou", "嗯。")],
            ),
        ],
        timeline=[_event("t1", "周野去世", "c1", 1, summary="周野死了")],
    )
    found = _of(analyze_continuity(project), "death_then_speaks")
    assert len(found) == 1
    assert "周野" in found[0]["message"]
    assert "林夏" not in found[0]["message"]


# ------------------------------------------------------ 正常项目不误报


def test_healthy_project_has_no_findings_and_passes():
    result = analyze_continuity(_healthy_project())
    assert result["findings"] == []
    assert result["counts"] == {"error": 0, "warn": 0, "info": 0, "pass": True}
    assert result["summary"]["chapters"] == 2
    assert result["summary"]["dialogueLines"] == 2


# ------------------------------------------------------------ 边界安全


def test_empty_project_is_safe():
    result = analyze_continuity(normalize_project({}))
    assert result["findings"] == []
    assert result["counts"]["pass"] is True


def test_project_without_characters_is_safe():
    project = _project(
        chapters=[_chapter("c1", "第一章", [_label("start"), _narration("雨。")])],
    )
    result = analyze_continuity(project)
    assert result["findings"] == []
    assert result["summary"]["characters"] == 0


def test_project_without_chapters_is_safe():
    """章节列表被清空时，时间线与角色检查照样能跑，不抛异常。"""
    project = _project(
        characters=[_char("ch-lin", "linxia", "林夏")],
        timeline=[_event("t1", "葬礼", "c1", 1)],
    ).model_copy(update={"chapters": []})
    result = analyze_continuity(project)
    assert result["summary"]["chapters"] == 0
    assert _of(result, "timeline_bad_ref")  # 章节真没了 → 引用就是坏的
    assert "unused_character_card" in _codes(result)
    assert result["counts"]["pass"] is False


def test_blocks_that_are_not_dicts_do_not_crash():
    """块列表里混进非 dict（老数据/手改 JSON）时不能让整份体检崩掉。"""
    project = _project(characters=[_char("ch-lin", "linxia", "林夏")])
    # model_construct 刻意绕过校验：真实的脏数据就是这么进来的（直接改过 JSON）。
    dirty = SceneChapter.model_construct(
        id="c1",
        title="第一章",
        blocks=[_label("start"), "oops", None, _dialogue("ch-lin", "嗯。")],
    )
    project = project.model_copy(update={"chapters": [dirty]})
    result = analyze_continuity(project)
    assert result["findings"] == []
    assert result["counts"]["pass"] is True


def test_missing_optional_collections_are_safe():
    project = normalize_project({"id": "p2", "title": "T", "chapters": []})
    project = project.model_copy(
        update={
            "characters": [],
            "locations": None,
            "characterLinks": None,
            "locationLinks": None,
            "timeline": None,
            "loreEntries": None,
        }
    )
    assert analyze_continuity(project)["counts"]["pass"] is True


# -------------------------------------------------------- 输出形状


def _messy_project():
    return _project(
        characters=[
            _char("ch-lin", "linxia", "林夏", aliases=["小夏"]),
            _char("ch-two", "xia2", "小夏"),
            _char("ch-ghost", "ghostcard", "幽灵设定"),
        ],
        characterLinks=[{"id": "l1", "fromId": "ch-lin", "toId": "ch-gone", "label": "旧友"}],
        locations=[{"id": "loc1", "name": "车站", "imageTag": "bg station_night"}],
        chapters=[
            _chapter(
                "c1",
                "雪夜",
                [
                    _label("start"),
                    _scene("bg station_night"),
                    _scene("bg roof_void"),
                    _dialogue("ch-lin", "你终于来了。"),
                    _dialogue("ch-none", "谁？"),
                    {"type": "return"},
                ],
            ),
            _chapter("c2", "归途", [_dialogue("ch-two", "嗯。")]),
        ],
        timeline=[
            _event("t1", "告别", "c-void", 1),
            _event("t2", "重复", "c1", 2),
            _event("t3", "重复", "c1", 3),
        ],
    )


def test_findings_shape_is_renderable_and_json_serializable():
    result = analyze_continuity(_messy_project())
    json.dumps(result, ensure_ascii=False)  # 不能有活对象
    for finding in result["findings"]:
        assert set(finding) == {"severity", "code", "message", "source", "chapterId", "label"}
        assert finding["source"] == "continuity"
        assert finding["severity"] in {"error", "warn", "info"}
        assert isinstance(finding["message"], str) and finding["message"]


def test_findings_are_sorted_error_first_then_warn_then_info():
    result = analyze_continuity(_messy_project())
    severities = [f["severity"] for f in result["findings"]]
    rank = {"error": 0, "warn": 1, "info": 2}
    assert severities == sorted(severities, key=lambda s: rank[s])
    codes = _codes(result)
    assert {"unknown_speaker", "alias_collision", "dangling_character_link"} <= set(codes)
    assert {"unknown_location_tag", "duplicate_timeline_event", "timeline_bad_ref"} <= set(codes)
    assert "unused_character_card" in codes


def test_counts_match_findings_and_summary_lists_every_check():
    result = analyze_continuity(_messy_project())
    counts = result["counts"]
    assert counts["error"] == len([f for f in result["findings"] if f["severity"] == "error"])
    assert counts["warn"] == len([f for f in result["findings"] if f["severity"] == "warn"])
    assert counts["info"] == len([f for f in result["findings"] if f["severity"] == "info"])
    assert counts["pass"] is (counts["error"] == 0)
    checks = result["summary"]["checks"]
    assert set(checks) == ALL_CHECK_CODES
    for stats in checks.values():
        assert isinstance(stats["checked"], int)
        assert isinstance(stats["issues"], int)
    assert result["summary"]["unknown"]
