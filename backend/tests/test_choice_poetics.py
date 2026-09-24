"""选项分类（Dunyazad 三分法的结构代理）与它给作者的建议。

依据：Towards a Theory of Choice Poetics（FDG 2014）、Intentionally Generating Choices
in Interactive Narratives（ICCC 2015）、Dunyazad（AIIDE）——见 docs/references.md。

这里测的是**判据本身**：结构上怎么算"怎么选都一样""意图明确""两难"，
以及报告有没有如实说明它只判结构、不判心理。
"""

from __future__ import annotations

from app.core.branch_analysis import analyze_branches
from app.core.branch_recommendations import recommend_branch_improvements
from app.core.choice_poetics import (
    CLASS_DILEMMA,
    CLASS_OBVIOUS,
    CLASS_RELAXED,
    analyze_choice_variety,
    classify_choice_menu,
    variety_recommendations,
)
from app.core.project import normalize_project


def _menu(choices):
    """按 branch_analysis 的菜单形状造菜单（这里只用到这些字段）。"""
    return {"chapterId": "ch1", "menuId": "m1", "prompt": "该怎么回应？", "choices": choices}


def _choice(text, *, target="", effect="jump", vars_=()):
    return {
        "text": text,
        "effect": effect,
        "target": target or None,
        "varsModified": list(vars_),
    }


def test_all_same_outcome_is_relaxed():
    """同目标、同变量 → 怎么选都一样（relaxed）。"""
    result = classify_choice_menu(
        _menu([_choice("A", target="next"), _choice("B", target="next")])
    )
    assert result["verdict"] == "all_relaxed"
    assert result["counts"][CLASS_RELAXED] == 2
    assert "选了没有区别" in result["choices"][0]["reason"]


def test_mutually_exclusive_variable_is_dilemma():
    """同一状态位取互斥的值 → 两难（选了 A 就拿不到 B）。"""
    result = classify_choice_menu(
        _menu(
            [
                _choice("告诉她自己听见了", target="tell", vars_=["trust"]),
                _choice("把这件事咽下去", target="hide", vars_=["trust"]),
            ]
        )
    )
    assert result["verdict"] == "has_dilemma"
    assert result["counts"][CLASS_DILEMMA] == 2
    assert "拿不到" in result["choices"][0]["reason"]


def test_distinct_targets_without_shared_state_are_obvious():
    """后果不同但不争同一个状态位 → 意图明确（obvious）。"""
    result = classify_choice_menu(
        _menu([_choice("去天台", target="roof"), _choice("留在教室", target="classroom")])
    )
    assert result["verdict"] == "no_dilemma"
    assert result["counts"][CLASS_OBVIOUS] == 2


def test_choices_touching_different_variables_are_not_a_dilemma():
    """各改各的变量不构成取舍（一边设 A、一边设 B，两样都拿得到）。"""
    result = classify_choice_menu(
        _menu(
            [
                _choice("拿伞", target="umbrella", vars_=["has_umbrella"]),
                _choice("拿手电", target="torch", vars_=["has_torch"]),
            ]
        )
    )
    assert result["counts"][CLASS_DILEMMA] == 0
    assert result["verdict"] == "no_dilemma"


def test_mixed_menu_reports_both_classes():
    """一个菜单里同时有两难与意图明确：各归各类，verdict 取"有两难"。"""
    result = classify_choice_menu(
        _menu(
            [
                _choice("说出口", target="say", vars_=["honesty"]),
                _choice("沉默", target="silent", vars_=["honesty"]),
                _choice("问她借伞", target="umbrella"),
            ]
        )
    )
    assert result["verdict"] == "has_dilemma"
    assert result["counts"][CLASS_DILEMMA] == 2
    assert result["counts"][CLASS_OBVIOUS] == 1


def test_empty_menu_is_safe():
    assert classify_choice_menu({"choices": []})["verdict"] == "empty"
    assert classify_choice_menu({})["choices"] == []


# ---- 整本书的类别分布 ----------------------------------------------------------


def _project(menus_spec):
    """造一个用菜单表达的作品；menus_spec 是 [(选项…), …]。"""
    blocks = [{"type": "label", "id": "start", "name": "start"}]
    for i, choices in enumerate(menus_spec, start=1):
        blocks.append(
            {
                "type": "menu",
                "id": f"m{i}",
                "prompt": f"第 {i} 处选择",
                "choices": [
                    {
                        "text": c[0],
                        "jump": c[1],
                        "blocks": [{"type": "set", "key": k, "value": 1} for k in c[2]],
                    }
                    for c in choices
                ],
            }
        )
    for i in range(1, 5):
        blocks.append({"type": "label", "id": f"l{i}", "name": f"l{i}"})
        blocks.append({"type": "narration", "text": f"第 {i} 段。"})
        blocks.append({"type": "jump", "target": "start" if i < 4 else "l1"})
    return normalize_project(
        {"id": "p-choice", "title": "选项样本", "chapters": [{"id": "ch1", "title": "第一章", "blocks": blocks}]}
    )


def test_variety_counts_and_all_relaxed_menus():
    project = _project(
        [
            [("相同 A", "l1", []), ("相同 B", "l1", [])],  # all relaxed
            [("说出口", "l1", ["honesty"]), ("沉默", "l2", ["honesty"])],  # dilemma
        ]
    )
    variety = analyze_choice_variety(project)
    assert variety["counts"]["menus"] == 2
    assert variety["counts"][CLASS_RELAXED] == 2
    assert variety["counts"][CLASS_DILEMMA] == 2
    assert len(variety["allRelaxedMenus"]) == 1
    # 报告要如实说明它只判结构
    assert any("结构启发式" in note for note in variety["notes"])


def test_all_relaxed_menu_produces_a_recommendation_with_a_concrete_action():
    project = _project([[("相同 A", "l1", []), ("相同 B", "l1", [])]])
    variety = analyze_choice_variety(project)
    recs = variety_recommendations(variety)
    assert any(r["code"] == "menu_all_relaxed" for r in recs)
    rec = next(r for r in recs if r["code"] == "menu_all_relaxed")
    # 建议必须给出**具体改法**，不是"优化一下"
    assert "状态位" in rec["action"]
    assert rec["where"]


def test_no_dilemma_recommendation_needs_enough_menus():
    """只有一两个菜单时不下"全书没有取舍"的结论——样本太少，说了也没用。"""
    one = _project([[("去天台", "l1", []), ("留在教室", "l2", [])]])
    assert not any(
        r["code"] == "no_dilemma_choice" for r in variety_recommendations(analyze_choice_variety(one))
    )


def test_book_with_only_obvious_choices_gets_the_no_dilemma_hint():
    project = _project(
        [
            [("去天台", "l1", []), ("留在教室", "l2", [])],
            [("看窗外", "l1", []), ("看书", "l2", [])],
            [("先说话", "l1", []), ("等她开口", "l2", [])],
        ]
    )
    recs = variety_recommendations(analyze_choice_variety(project))
    rec = next(r for r in recs if r["code"] == "no_dilemma_choice")
    assert rec["severity"] == "info"  # 没有两难不是错误
    assert "放弃了什么" in rec["why"]
    assert "互斥" in rec["action"]


# ---- 接进现有建议链路 ----------------------------------------------------------


def test_recommendations_include_choice_variety_and_its_notes():
    """分类结果要真的出现在 /branch/recommendations 的输出里（含 self-limits 说明）。"""
    project = _project([[("相同 A", "l1", []), ("相同 B", "l1", [])]])
    out = recommend_branch_improvements(project)
    assert "choiceVariety" in out
    assert out["choiceVariety"]["counts"]["menus"] == 1
    assert any("结构启发式" in n for n in out["notes"])
    codes = [r["code"] for r in out["recommendations"]]
    assert "menu_all_relaxed" in codes


def test_recommendations_are_still_sorted_and_counted():
    """新增建议不能破坏原有的排序与计数（它们由优先级决定）。"""
    project = _project(
        [
            [("相同 A", "l1", []), ("相同 B", "l1", [])],
            [("说出口", "l1", ["honesty"]), ("沉默", "l2", ["honesty"])],
        ]
    )
    out = recommend_branch_improvements(project)
    priorities = [r["priority"] for r in out["recommendations"]]
    assert priorities == sorted(priorities, reverse=True)
    assert out["counts"]["total"] == len(out["recommendations"])


def test_analyze_branches_can_be_reused_without_reparsing():
    """传进已算好的 branch 时不该重新解析剧本（两处各解析一遍会互相打架）。"""
    project = _project([[("相同 A", "l1", []), ("相同 B", "l1", [])]])
    branch = analyze_branches(project)
    variety = analyze_choice_variety(project, branch=branch)
    assert variety["counts"]["menus"] == 1
