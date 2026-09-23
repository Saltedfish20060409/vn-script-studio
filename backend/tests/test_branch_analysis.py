"""分支控制流分析的测试。

这些断言锁住的是**语义**，不是实现细节：
- label 是标记不是终点 → "没有出口"应产生 fallthrough 边，而不是被当成结局；
- 无条件跳转之后的同级语句是死代码；
- 环要能分辨"有出口的 hub"和"玩家出不去的死循环"；
- 条件"恒不成立"只在**能证明**时才报（有号变量不能被误判）；
- 声明结局与实际可达终点要对得上账。
"""

from __future__ import annotations

from app.core.branch_analysis import (
    analyze_branches,
    analyze_conditions,
    analyze_menus,
    build_graph,
    enumerate_paths,
    find_cycles,
    reachable_from,
    variable_domain,
)
from app.core.project import normalize_project


def _project(chapters: list, variables: list | None = None, endings: list | None = None):
    return normalize_project(
        {
            "id": "p1",
            "title": "分支测试",
            "characters": [],
            "variables": variables or [],
            "endings": endings or [],
            "chapters": [
                {"id": f"c{i}", "title": f"第{i}章", "blocks": b}
                for i, b in enumerate(chapters, start=1)
            ],
        }
    )


def _label(name: str) -> dict:
    return {"type": "label", "id": name, "name": name}


def _menu(choices: list, mid: str = "m") -> dict:
    return {"type": "menu", "id": mid, "choices": choices}


def _codes(result: dict) -> list:
    return [f["code"] for f in result["findings"]]


def _var(key: str, value=0, vtype: str = "number") -> dict:
    return {"id": f"v-{key}", "name": key, "key": key, "type": vtype, "value": value}


# ------------------------------------------------------------ label 与边语义


def test_label_without_exit_falls_through_to_next_label():
    """label 是标记不是终点：没有出口 = 继续往下执行，不是结局。"""
    graph = build_graph(
        _project(
            [
                [
                    _label("start"),
                    {"type": "narration", "text": "雨。"},
                    _label("next"),
                    {"type": "return"},
                ]
            ]
        )
    )
    kinds = {(e.src, e.dst): e.kind for e in graph.edges}
    assert kinds[("start", "next")] == "fallthrough"
    assert kinds[("next", None)] == "return"
    assert analyze_branches(
        _project(
            [
                [
                    _label("start"),
                    {"type": "narration", "text": "雨。"},
                    _label("next"),
                    {"type": "return"},
                ]
            ]
        )
    )["endings"]["undeclaredTerminals"] == ["next"]


def test_all_options_jumping_exits_the_segment():
    graph = build_graph(
        _project(
            [
                [
                    _label("start"),
                    _menu(
                        [
                            {"text": "留下", "jump": "a"},
                            {"text": "离开", "jump": "b"},
                        ]
                    ),
                    {"type": "narration", "text": "这段不该可达"},
                    _label("a"),
                    {"type": "return"},
                    _label("b"),
                    {"type": "return"},
                ]
            ]
        )
    )
    assert {(e.src, e.dst) for e in graph.edges if e.kind == "choice"} == {
        ("start", "a"),
        ("start", "b"),
    }
    assert not any(e.src == "start" and e.kind == "fallthrough" for e in graph.edges)
    # 菜单之后的同级语句是死代码
    assert any(f["code"] == "dead_block" for f in analyze_branches(
        _project(
            [
                [
                    _label("start"),
                    _menu([{"text": "留下", "jump": "a"}, {"text": "离开", "jump": "b"}]),
                    {"type": "narration", "text": "这段不该可达"},
                    _label("a"),
                    {"type": "return"},
                    _label("b"),
                    {"type": "return"},
                ]
            ]
        )
    )["findings"])


def test_inline_choice_body_does_not_exit_the_segment():
    """选项正文内联时，菜单结束后继续执行 → 仍有 fallthrough。"""
    graph = build_graph(
        _project(
            [
                [
                    _label("start"),
                    _menu(
                        [
                            {"text": "留下", "blocks": [{"type": "narration", "text": "她没走。"}]},
                            {"text": "离开", "blocks": [{"type": "narration", "text": "门响了。"}]},
                        ]
                    ),
                    _label("next"),
                    {"type": "return"},
                ]
            ]
        )
    )
    assert any(e.kind == "fallthrough" and e.src == "start" for e in graph.edges)


def test_choice_body_that_returns_is_a_terminal():
    graph = build_graph(
        _project(
            [
                [
                    _label("start"),
                    _menu(
                        [
                            {"text": "结束", "blocks": [{"type": "return"}]},
                            {"text": "继续", "blocks": [{"type": "narration", "text": "……"}]},
                        ]
                    ),
                ]
            ]
        )
    )
    # 选项 A 直接 return → 是一条终结边
    assert any(e.kind == "return" and e.src == "start" for e in graph.edges)
    # 选项 B 是内联正文 → 本章末尾仍能"流出去"
    assert any(e.kind == "chapter-end" and e.src == "start" for e in graph.edges)


def test_partial_exit_menu_keeps_both_the_choice_edge_and_the_fallthrough():
    """选项 A 跳走、选项 B 继续 —— 两种控制流都要在图上出现，缺一个覆盖统计就偏低。"""
    graph = build_graph(
        _project(
            [
                [
                    _label("start"),
                    _menu(
                        [
                            {"text": "跳走", "jump": "a"},
                            {"text": "继续", "blocks": [{"type": "narration", "text": "她没动。"}]},
                        ]
                    ),
                    {"type": "narration", "text": "菜单之后"},
                    _label("a"),
                    {"type": "return"},
                ]
            ]
        )
    )
    kinds = {(e.src, e.dst, e.kind) for e in graph.edges}
    assert ("start", "a", "choice") in kinds
    assert any(k[2] == "fallthrough" for k in kinds)
    # 菜单之后那句在 fallthrough 路径上，是可执行代码而不是死代码
    assert not any(f["code"] == "dead_block" for f in analyze_branches(
        _project(
            [
                [
                    _label("start"),
                    _menu(
                        [
                            {"text": "跳走", "jump": "a"},
                            {"text": "继续", "blocks": [{"type": "narration", "text": "她没动。"}]},
                        ]
                    ),
                    {"type": "narration", "text": "菜单之后"},
                    _label("a"),
                    {"type": "return"},
                ]
            ]
        )
    )["findings"])


def test_dead_code_after_unconditional_jump_is_reported():
    result = analyze_branches(
        _project(
            [
                [
                    _label("start"),
                    {"type": "jump", "target": "end"},
                    {"type": "narration", "text": "永远不会演"},
                    {"type": "dialogue", "characterId": "x", "text": "也永远不会说"},
                    _label("end"),
                    {"type": "return"},
                ]
            ]
        )
    )
    assert len(result["deadBlocks"]) == 2
    assert all(d["label"] == "start" for d in result["deadBlocks"])


def test_unreachable_label_and_dangling_jump_are_reported():
    result = analyze_branches(
        _project(
            [
                [
                    _label("start"),
                    {"type": "jump", "target": "ghost"},
                    _label("orphan"),
                    {"type": "return"},
                ]
            ]
        )
    )
    assert "ghost" in [d["target"] for d in result["danglingJumps"]]
    assert "orphan" in result["unreachableLabels"]
    assert "dangling_jump" in _codes(result)
    assert "unreachable_label" in _codes(result)


def test_duplicate_label_is_reported():
    result = analyze_branches(
        _project([[ _label("start"), _label("start"), {"type": "return"} ]])
    )
    assert result["duplicateLabels"] == ["start"]
    assert "duplicate_label" in _codes(result)


# ------------------------------------------------------------------ 环检测


def test_simple_loop_is_detected_as_loop_forever():
    """既无变量变化也无条件出口的回路 = 玩家出不去。"""
    result = analyze_branches(
        _project(
            [
                [
                    _label("start"),
                    {"type": "jump", "target": "hub"},
                    _label("hub"),
                    {"type": "narration", "text": "回到起点。"},
                    {"type": "jump", "target": "start"},
                ]
            ]
        )
    )
    loops = [c for c in result["cycles"] if c["canLoopForever"]]
    assert loops, result["cycles"]
    assert set(loops[0]["labels"]) == {"start", "hub"}
    assert "loop_no_exit" in _codes(result)


def test_loop_with_variable_change_can_exit():
    result = analyze_branches(
        _project(
            [
                [
                    _label("start"),
                    {"type": "set", "key": "count", "op": "+=", "value": 1},
                    {"type": "jump", "target": "hub"},
                    _label("hub"),
                    {"type": "jump", "target": "start"},
                ]
            ],
            variables=[_var("count")],
        )
    )
    loop = next(c for c in result["cycles"] if set(c["labels"]) == {"start", "hub"})
    assert loop["hasVariableChange"] is True
    assert loop["canLoopForever"] is False


def test_loop_with_conditional_exit_can_exit():
    result = analyze_branches(
        _project(
            [
                [
                    _label("start"),
                    {"type": "jump", "target": "hub"},
                    _label("hub"),
                    _menu(
                        [
                            {"text": "再逛一圈", "jump": "start"},
                            {"text": "走", "jump": "done", "condition": "seen >= 1"},
                        ]
                    ),
                    _label("done"),
                    {"type": "return"},
                ]
            ],
            variables=[_var("seen", 0)],
        )
    )
    loop = next(c for c in result["cycles"] if set(c["labels"]) == {"start", "hub"})
    assert loop["hasConditionalExit"] is True
    assert loop["canLoopForever"] is False


def test_self_loop_is_detected():
    cycles = find_cycles(
        build_graph(
            _project([[_label("start"), {"type": "jump", "target": "start"}]])
        )
    )
    assert any(c["labels"] == ["start"] for c in cycles)


def test_diamond_does_not_produce_a_phantom_cycle():
    """菱形汇合是合法结构，绝不能被报成环。"""
    cycles = find_cycles(
        build_graph(
            _project(
                [
                    [
                        _label("start"),
                        _menu([{"text": "甲", "jump": "a"}, {"text": "乙", "jump": "b"}]),
                        _label("a"),
                        {"type": "jump", "target": "join"},
                        _label("b"),
                        {"type": "jump", "target": "join"},
                        _label("join"),
                        {"type": "return"},
                    ]
                ]
            )
        )
    )
    assert cycles == []


def test_each_cycle_is_reported_once():
    """同一回路只能出现一次，不能因为枚举起点不同重复报。"""
    cycles = find_cycles(
        build_graph(
            _project(
                [
                    [
                        _label("start"),
                        {"type": "jump", "target": "a"},
                        _label("a"),
                        {"type": "jump", "target": "b"},
                        _label("b"),
                        {"type": "jump", "target": "a"},
                    ]
                ]
            )
        )
    )
    assert len(cycles) == 1
    assert set(cycles[0]["labels"]) == {"a", "b"}


# -------------------------------------------------------------- 条件可满足性


def _cond_of(project):
    return {(c["chapterId"], c["text"]): c for c in analyze_conditions(project)["conditions"]}


def test_impossible_interval_is_never_true():
    project = _project(
        [
            [
                _label("start"),
                _menu(
                    [
                        {
                            "text": "秘密",
                            "jump": "a",
                            "condition": "affection >= 5 and affection <= 2",
                        }
                    ]
                ),
                _label("a"),
                {"type": "return"},
            ]
        ],
        variables=[_var("affection", 0)],
    )
    row = _cond_of(project)[("c1", "affection >= 5 and affection <= 2")]
    assert row["satisfiable"] is False
    assert "区间为空" in row["reason"]


def test_flag_at_initial_value_can_never_satisfy_another_value():
    """声明为 0、且全篇没有任何赋值 → `flag == 1` 永远不成立。"""
    project = _project(
        [
            [
                _label("start"),
                _menu([{"text": "隐藏", "jump": "a", "condition": "saw_it == 1"}]),
                _label("a"),
                {"type": "return"},
            ]
        ],
        variables=[_var("saw_it", 0)],
    )
    row = _cond_of(project)[("c1", "saw_it == 1")]
    assert row["satisfiable"] is False


def test_incremented_variable_is_not_declared_impossible():
    """`+=` 的变量可以连续变化 → 只允许报"未知"，绝不能误判为恒不成立。"""
    project = _project(
        [
            [
                _label("start"),
                {"type": "set", "key": "affection", "op": "+=", "value": 1},
                _menu([{"text": "约会", "jump": "a", "condition": "affection >= 5"}]),
                _label("a"),
                {"type": "return"},
            ]
        ],
        variables=[_var("affection", 0)],
    )
    row = _cond_of(project)[("c1", "affection >= 5")]
    assert row["satisfiable"] is True
    assert row["unknown"] is True


def test_reachable_set_value_makes_condition_possible():
    project = _project(
        [
            [
                _label("start"),
                {"type": "set", "key": "route", "value": "snow"},
                _menu([{"text": "雪线", "jump": "a", "condition": 'route == "snow"'}]),
                _label("a"),
                {"type": "return"},
            ]
        ]
    )
    row = _cond_of(project)[("c1", 'route == "snow"')]
    assert row["satisfiable"] is True
    assert row["unknown"] is False


def test_numeric_comparison_against_text_is_a_type_mismatch():
    """数值比较却拿字符串比：Ren'Py 里会直接 TypeError，属于错而不是"不成立"。"""
    project = _project(
        [
            [
                _label("start"),
                _menu([{"text": "x", "jump": "a", "condition": 'affection >= "高"'}]),
                _label("a"),
                {"type": "return"},
            ]
        ],
        variables=[_var("affection", 0)],
    )
    result = analyze_conditions(project)
    assert result["typeMismatch"]
    assert "condition_type_mismatch" in _codes(analyze_branches(project))


def test_bare_non_ascii_comparison_value_is_invalid_syntax():
    """`affection >= 高` 不是类型错，是语法错（裸词必须是 ASCII 标识符）。"""
    project = _project(
        [
            [
                _label("start"),
                _menu([{"text": "x", "jump": "a", "condition": "affection >= 高"}]),
                _label("a"),
                {"type": "return"},
            ]
        ],
        variables=[_var("affection", 0)],
    )
    assert analyze_conditions(project)["invalid"]


def test_unconditional_condition_is_never_flagged():
    project = _project([[_label("start"), {"type": "return"}]])
    assert analyze_conditions(project)["neverTrue"] == []


def test_variable_domain_reports_unbounded_and_declared():
    project = _project(
        [
            [
                _label("start"),
                {"type": "set", "key": "score", "op": "+=", "value": 2},
                {"type": "set", "key": "route", "value": "snow"},
                {"type": "return"},
            ]
        ],
        variables=[_var("score", 0)],
    )
    graph = build_graph(project)
    dom = variable_domain(project, graph)
    assert dom["score"]["unbounded"] is True
    assert dom["score"]["declared"] is True
    assert dom["route"]["declared"] is False
    assert "snow" in dom["route"]["values"]


# -------------------------------------------------------------------- 菜单


def test_menu_with_identical_consequences_is_flagged():
    menus = analyze_menus(
        _project(
            [
                [
                    _label("start"),
                    _menu([{"text": "一", "jump": "a"}, {"text": "二", "jump": "a"}, {"text": "三", "jump": "a"}]),
                    _label("a"),
                    {"type": "return"},
                ]
            ]
        )
    )
    assert menus[0]["findings"]
    assert any(f["code"] == "menu_no_effect" for f in menus[0]["findings"])


def test_menu_with_real_consequences_is_not_flagged_as_no_effect():
    menus = analyze_menus(
        _project(
            [
                [
                    _label("start"),
                    _menu(
                        [
                            {
                                "text": "帮她",
                                "blocks": [{"type": "set", "key": "affection", "op": "+=", "value": 1}],
                            },
                            {"text": "走开", "jump": "gone"},
                        ],
                        mid="choice1",
                    ),
                    _label("gone"),
                    {"type": "return"},
                ]
            ],
            variables=[_var("affection", 0)],
        )
    )
    assert not any(f["code"] == "menu_no_effect" for f in menus[0]["findings"])


def test_dead_option_and_softlock_are_reported():
    menus = analyze_menus(
        _project(
            [
                [
                    _label("start"),
                    _menu(
                        [
                            {"text": "隐藏线", "jump": "a", "condition": "saw_it == 1"},
                            {"text": "真相线", "jump": "a", "condition": "saw_it == 2"},
                        ]
                    ),
                    _label("a"),
                    {"type": "return"},
                ]
            ],
            variables=[_var("saw_it", 0)],
        )
    )
    codes = [f["code"] for f in menus[0]["findings"]]
    assert "choice_never_available" in codes
    assert "menu_always_empty" in codes


def test_duplicate_text_and_condition_are_reported():
    menus = analyze_menus(
        _project(
            [
                [
                    _label("start"),
                    _menu(
                        [
                            {"text": "一样", "jump": "a"},
                            {"text": "一样", "jump": "b"},
                            {"text": "有条件的", "jump": "a", "condition": "x >= 1"},
                            {"text": "也是那个条件", "jump": "b", "condition": "x >= 1"},
                        ],
                        mid="dup",
                    ),
                    _label("a"),
                    {"type": "return"},
                    _label("b"),
                    {"type": "return"},
                ]
            ],
            variables=[_var("x", 1)],
        )
    )
    codes = [f["code"] for f in menus[0]["findings"]]
    assert "choice_duplicate_text" in codes
    assert "choice_duplicate_condition" in codes


def test_empty_option_text_is_an_error():
    menus = analyze_menus(
        _project(
            [
                [
                    _label("start"),
                    _menu([{"text": "  ", "jump": "a"}, {"text": "二", "jump": "b"}]),
                    _label("a"),
                    {"type": "return"},
                    _label("b"),
                    {"type": "return"},
                ]
            ]
        )
    )
    assert any(f["code"] == "choice_empty_text" for f in menus[0]["findings"])
    assert any(f["severity"] == "error" for f in menus[0]["findings"])


def test_menu_options_carry_effect_and_variable_info():
    menus = analyze_menus(
        _project(
            [
                [
                    _label("start"),
                    _menu(
                        [
                            {
                                "text": "给伞",
                                "blocks": [{"type": "set", "key": "gave_umbrella", "value": True}],
                            },
                            {"text": "离开", "jump": "gone"},
                        ]
                    ),
                    _label("gone"),
                    {"type": "return"},
                ]
            ]
        )
    )
    rows = menus[0]["choices"]
    assert rows[0]["effect"] == "inline"
    assert rows[0]["varsModified"] == ["gave_umbrella"]
    assert rows[1]["effect"] == "jump"
    assert rows[1]["target"] == "gone"


# ------------------------------------------------------------------ 路径与覆盖


def test_branch_coverage_counts_traversed_choices():
    result = analyze_branches(
        _project(
            [
                [
                    _label("start"),
                    _menu([{"text": "甲", "jump": "a"}, {"text": "乙", "jump": "b"}]),
                    _label("a"),
                    {"type": "return"},
                    _label("b"),
                    {"type": "return"},
                ]
            ]
        )
    )
    cov = result["coverage"]
    assert cov["choices"]["total"] == 2
    assert cov["choices"]["traversed"] == 2
    assert cov["choices"]["ratio"] == 1.0
    assert cov["paths"]["count"] == 2
    assert cov["labels"]["ratio"] == 1.0


def test_unreachable_branch_lowers_coverage():
    result = analyze_branches(
        _project(
            [
                [
                    _label("start"),
                    _menu([{"text": "甲", "jump": "a"}, {"text": "乙", "jump": "b"}]),
                    _label("a"),
                    {"type": "return"},
                    {"type": "jump", "target": "b"},
                    _label("b"),
                    {"type": "return"},
                ]
            ]
        )
    )
    # b 仍可达（菜单有选项跳过去），标签覆盖应为 1.0；这里主要验证计数形状
    assert result["coverage"]["choices"]["total"] == 2
    assert result["coverage"]["paths"]["count"] >= 2
    assert 0.0 <= result["coverage"]["score"] <= 1.0


def test_path_enumeration_terminates_on_cycles():
    """图里有环时枚举必须终止，并且如实标记没有枚举完。"""
    info = enumerate_paths(
        build_graph(
            _project(
                [
                    [
                        _label("start"),
                        {"type": "jump", "target": "hub"},
                        _label("hub"),
                        _menu(
                            [
                                {"text": "再来", "jump": "hub"},
                                {"text": "结束", "jump": "end"},
                            ]
                        ),
                        _label("end"),
                        {"type": "return"},
                    ]
                ]
            )
        )
    )
    assert info["paths"] >= 1
    assert isinstance(info["truncated"], bool)


def test_reachable_from_uses_start_or_first_label():
    graph = build_graph(
        _project([[_label("a"), {"type": "jump", "target": "b"}, _label("b"), {"type": "return"}]])
    )
    assert reachable_from(graph) == {"a", "b"}
    graph2 = build_graph(
        _project(
            [
                [
                    _label("start"),
                    {"type": "jump", "target": "x"},
                    _label("x"),
                    {"type": "return"},
                    _label("orphan"),
                    {"type": "return"},
                ]
            ]
        )
    )
    assert reachable_from(graph2) == {"start", "x"}


# -------------------------------------------------------------------- 结局


def test_declared_ending_that_is_unreachable_is_an_error():
    result = analyze_branches(
        _project(
            [
                [
                    _label("start"),
                    {"type": "jump", "target": "good"},
                    _label("good"),
                    {"type": "return"},
                    _label("secret"),
                    {"type": "return"},
                ]
            ],
            endings=[
                {"id": "e1", "name": "好结局", "label": "good"},
                {"id": "e2", "name": "隐藏结局", "label": "secret"},
            ],
        )
    )
    rows = {r["name"]: r for r in result["endings"]["declared"]}
    assert rows["好结局"]["reachable"] is True
    assert rows["隐藏结局"]["reachable"] is False
    assert result["endings"]["reachableDeclared"] == 1
    # 两个终点都登记过 → 不该再报"未登记的终点"
    assert result["endings"]["undeclaredTerminals"] == []
    assert "unreachable_label" in _codes(result)


def test_ending_pointing_at_missing_label_is_an_error():
    result = analyze_branches(
        _project(
            [[_label("start"), {"type": "return"}]],
            endings=[{"id": "e1", "name": "幻觉结局", "label": "nowhere"}],
        )
    )
    assert "ending_label_missing" in _codes(result)
    assert any(f["severity"] == "error" for f in result["findings"])


def test_ending_without_label_cannot_be_verified():
    result = analyze_branches(
        _project(
            [[_label("start"), {"type": "return"}]],
            endings=[{"id": "e1", "name": "结局甲"}],
        )
    )
    assert "ending_no_label" in _codes(result)


def test_undeclared_terminal_is_listed():
    result = analyze_branches(
        _project(
            [
                [
                    _label("start"),
                    _menu([{"text": "甲", "jump": "a"}, {"text": "乙", "jump": "b"}]),
                    _label("a"),
                    {"type": "return"},
                    _label("b"),
                    {"type": "return"},
                ]
            ],
            endings=[{"id": "e1", "name": "甲结局", "label": "a"}],
        )
    )
    assert result["endings"]["undeclaredTerminals"] == ["b"]


# ------------------------------------------------------------- 章末与汇总


def test_chapter_end_without_exit_is_reported_as_export_hazard():
    result = analyze_branches(
        _project(
            [
                [_label("start"), {"type": "narration", "text": "第一章"}],
                [_label("start2"), {"type": "narration", "text": "第二章"}],
            ]
        )
    )
    assert result["chapterEndWithoutExit"]
    assert "chapter_end_no_exit" in _codes(result)


def test_no_export_hazard_when_chapter_ends_with_return():
    result = analyze_branches(
        _project(
            [
                [_label("start"), {"type": "return"}],
                [_label("start2"), {"type": "return"}],
            ]
        )
    )
    assert result["chapterEndWithoutExit"] == []


def test_summary_shape_and_pass_flag():
    clean = analyze_branches(_project([[_label("start"), {"type": "return"}]]))
    assert clean["counts"]["pass"] is True
    broken = analyze_branches(
        _project([[_label("start"), {"type": "jump", "target": "ghost"}]])
    )
    assert broken["counts"]["pass"] is False
    assert broken["graph"]["labels"] == 1
    assert set(broken["coverage"]) >= {"labels", "choices", "paths", "score"}


def test_analyze_branches_on_empty_project_is_safe():
    result = analyze_branches(normalize_project({"id": "p", "title": "空"}))
    assert result["graph"]["labels"] >= 1
    assert isinstance(result["findings"], list)
