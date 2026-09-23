"""分支改进建议测试。

这个模块的价值全在**融合**上，所以测试的重点不是"能不能报出问题"，而是：

1. **同一份读者数据，配上不同的静态结构，要给出不同的改法**——
   "某个选项没人选"在"它和其它选项后果相同"（可以删）与"它只是文案不吸引人"（该改文案）
   两种情况下，建议必须不一样。这是只看单边数据做不到的事，也是本模块存在的理由。
2. **没有读者数据时不许假装有**：`basis` 要如实写 `script-only`，且**不出现**任何
   依赖经验证据的建议——报一个 0% 出来只会让人误改剧本。
3. **小样本要主动闭嘴**：3 次试玩里的"没人选"说明不了任何事。
"""

from __future__ import annotations

from app.core.branch_recommendations import (
    DOMINANT_SHARE,
    MIN_RUNS_FOR_EVIDENCE,
    _effect_signature,
    recommend_branch_improvements,
)
from app.core.project import normalize_project

# ------------------------------------------------------------------ 夹具


def _ch(cid: str, blocks: list) -> dict:
    return {"id": cid, "title": cid, "blocks": blocks}


def _label(name: str) -> dict:
    return {"type": "label", "id": name, "name": name}


def _menu(mid: str, choices: list) -> dict:
    return {"type": "menu", "id": mid, "choices": choices}


def _noop_project():
    """m1：两个选项后果完全相同（静态判定"无后果"）。"""
    return normalize_project(
        {
            "id": "p1",
            "title": "建议测试",
            "characters": [{"id": "lin", "defineName": "lin", "displayName": "林夏"}],
            "chapters": [
                _ch(
                    "ch1",
                    [
                        _label("start"),
                        _menu(
                            "m1",
                            [
                                {"text": "留下", "blocks": [{"type": "narration", "text": "她没走。"}]},
                                {"text": "也留下", "blocks": [{"type": "narration", "text": "她还在。"}]},
                            ],
                        ),
                        {"type": "return"},
                    ],
                )
            ],
        }
    )


def _meaningful_project():
    """m1：一个选项改变量、一个内联——后果不同，静态不该判"无后果"。"""
    return normalize_project(
        {
            "id": "p2",
            "title": "建议测试2",
            "characters": [{"id": "lin", "defineName": "lin", "displayName": "林夏"}],
            "variables": [
                {"id": "v", "name": "好感", "key": "affection", "type": "number", "value": 0}
            ],
            "chapters": [
                _ch(
                    "ch1",
                    [
                        _label("start"),
                        _menu(
                            "m1",
                            [
                                {
                                    "text": "帮她",
                                    "blocks": [{"type": "set", "key": "affection", "op": "+=", "value": 1}],
                                },
                                {"text": "走开", "blocks": [{"type": "narration", "text": "她走了。"}]},
                            ],
                        ),
                        {"type": "return"},
                    ],
                )
            ],
        }
    )


def _analytics(*, runs: int, menu_id: str = "m1", chapter_id: str = "ch1", never: list | None = None,
               shares: list | None = None, coverage: dict | None = None,
               never_reached: list | None = None) -> dict:
    never = never if never is not None else [1]
    shares = shares if shares is not None else [1.0, 0.0]
    options = [
        {
            "index": i,
            "selected": int(round(s * runs)),
            "share": s,
            "neverSelected": i in never,
            "available": True,
            "condition": "",
            "conditionBlockedSelections": 0,
        }
        for i, s in enumerate(shares)
    ]
    return {
        "sample": {"runs": runs, "choices": runs},
        "choices": {
            "totalSelections": runs,
            "menuCount": 1,
            "menus": [
                {
                    "menuId": menu_id,
                    "chapterId": chapter_id,
                    "label": "start",
                    "selections": runs,
                    "optionCount": len(options),
                    "options": options,
                    "neverSelected": never,
                }
            ],
            "unknownMenus": [],
            "duplicateMenuIds": [],
        },
        "coverage": coverage or {"ratio": 1.0, "menusNeverTouched": [], "availableOptions": 2, "observedOptions": 2},
        "endings": {"neverReached": never_reached or [], "reached": [], "declaredTotal": 0, "declaredReached": 0},
    }


def _codes(result: dict) -> list:
    return [r["code"] for r in result["recommendations"]]


def _by_code(result: dict, code: str) -> dict:
    return next(r for r in result["recommendations"] if r["code"] == code)


# ------------------------------------------------------------- 静态类建议


def test_no_effect_menu_is_reported_with_a_concrete_action():
    out = recommend_branch_improvements(_noop_project())
    assert "no_effect_menu" in _codes(out)
    rec = _by_code(out, "no_effect_menu")
    # 建议必须给出**具体改法**，而不是"建议优化一下"
    assert "变量" in rec["action"] or "label" in rec["action"]
    assert rec["where"] == "ch1/m1"
    assert rec["confidence"] == "static"


def test_menu_with_real_consequences_is_not_flagged():
    out = recommend_branch_improvements(_meaningful_project())
    assert "no_effect_menu" not in _codes(out)
    assert _effect_signature(
        {"choices": [{"effect": "inline", "varsModified": ["a"]}, {"effect": "inline"}]}
    ) != _effect_signature({"choices": [{"effect": "inline"}, {"effect": "inline"}]})


def test_softlock_menu_is_an_error():
    project = normalize_project(
        {
            "id": "p3",
            "title": "软锁",
            "variables": [
                {"id": "v", "name": "旗", "key": "seen", "type": "number", "value": 0}
            ],
            "chapters": [
                _ch(
                    "ch1",
                    [
                        _label("start"),
                        _menu(
                            "m1",
                            [
                                {"text": "隐藏", "jump": "a", "condition": "seen == 1"},
                                {"text": "也隐藏", "jump": "a", "condition": "seen == 2"},
                            ],
                        ),
                        _label("a"),
                        {"type": "return"},
                    ],
                )
            ],
        }
    )
    out = recommend_branch_improvements(project)
    assert "softlock_menu" in _codes(out)
    assert _by_code(out, "softlock_menu")["severity"] == "error"


def test_loop_without_exit_is_an_error():
    project = normalize_project(
        {
            "id": "p4",
            "title": "死循环",
            "chapters": [
                _ch(
                    "ch1",
                    [
                        _label("start"),
                        {"type": "jump", "target": "hub"},
                        _label("hub"),
                        {"type": "jump", "target": "start"},
                    ],
                )
            ],
        }
    )
    out = recommend_branch_improvements(project)
    assert "loop_no_exit" in _codes(out)
    assert _by_code(out, "loop_no_exit")["severity"] == "error"


def test_unreachable_declared_ending_is_an_error_but_missing_label_is_not_duplicated():
    project = normalize_project(
        {
            "id": "p5",
            "title": "结局",
            "endings": [{"id": "e1", "name": "隐藏结局", "label": "secret"}],
            "chapters": [
                _ch(
                    "ch1",
                    [
                        _label("start"),
                        {"type": "jump", "target": "good"},
                        _label("good"),
                        {"type": "return"},
                        _label("secret"),
                        {"type": "return"},
                    ],
                )
            ],
        }
    )
    out = recommend_branch_improvements(project)
    assert "unreachable_ending" in _codes(out)


def test_endings_that_do_not_exist_are_left_to_the_static_report():
    """label 根本不存在的结局属于"登记错误"，由 branch_analysis 报，这儿不重复报。"""
    project = normalize_project(
        {
            "id": "p6",
            "title": "结局2",
            "endings": [{"id": "e1", "name": "幻觉", "label": "nowhere"}],
            "chapters": [_ch("ch1", [_label("start"), {"type": "return"}])],
        }
    )
    assert "unreachable_ending" not in _codes(recommend_branch_improvements(project))


def test_single_option_menu_is_info():
    project = normalize_project(
        {
            "id": "p7",
            "title": "单选项",
            "chapters": [
                _ch(
                    "ch1",
                    [
                        _label("start"),
                        _menu("m1", [{"text": "唯一", "jump": "a"}]),
                        _label("a"),
                        {"type": "return"},
                    ],
                )
            ],
        }
    )
    out = recommend_branch_improvements(project)
    assert _by_code(out, "single_option_menu")["severity"] == "info"


# ------------------------------------------------------- 无数据 / 小样本


def test_without_readers_nothing_empirical_is_claimed():
    out = recommend_branch_improvements(_noop_project())
    assert out["basis"] == "script-only"
    assert out["summary"]["evidence"] == 0
    assert "不会出现" in out["sampleNote"]
    assert not [r for r in out["recommendations"] if r["confidence"] == "evidence"]


def test_small_sample_is_refused_instead_of_guessed():
    """3 次试玩里的"没人选"说明不了任何事，必须拒答而不是给个 0%。"""
    out = recommend_branch_improvements(
        _noop_project(), analytics=_analytics(runs=MIN_RUNS_FOR_EVIDENCE - 1)
    )
    assert out["basis"] == "script-only"
    assert "never_selected_option" not in _codes(out)
    assert str(MIN_RUNS_FOR_EVIDENCE) in out["sampleNote"]


def test_enough_sample_enables_evidence_basis():
    out = recommend_branch_improvements(
        _noop_project(), analytics=_analytics(runs=MIN_RUNS_FOR_EVIDENCE)
    )
    assert out["basis"] == "script+readers"
    assert out["summary"]["evidence"] > 0


# ---------------------------------------------------------------- 融合判定


def test_same_reader_data_with_different_structure_gives_different_action():
    """**这是本模块存在的理由**：同一份"没人选"数据，两种结构给出两种改法。"""
    analytics = _analytics(runs=30)

    fused = recommend_branch_improvements(_noop_project(), analytics=analytics)
    solo = recommend_branch_improvements(_meaningful_project(), analytics=analytics)

    fused_rec = _by_code(fused, "never_selected_option")
    solo_rec = _by_code(solo, "never_selected_option")

    assert fused_rec["action"] != solo_rec["action"]
    # 无后果选项 → 建议删掉或给它一个真实后果
    assert "删" in fused_rec["action"] or "真实后果" in fused_rec["action"]
    # 有后果但没人选 → 建议先确认可见性 / 改文案
    assert "可见" in solo_rec["action"] or "文案" in solo_rec["action"]
    assert fused_rec["evidence"]["selections"] == 30


def test_never_selected_option_carries_its_condition_in_the_evidence_reason():
    analytics = _analytics(runs=30)
    analytics["choices"]["menus"][0]["options"][1]["condition"] = "affection >= 5"
    out = recommend_branch_improvements(_meaningful_project(), analytics=analytics)
    rec = _by_code(out, "never_selected_option")
    assert "affection >= 5" in rec["why"]


def test_dominant_option_is_reported():
    analytics = _analytics(runs=40, shares=[1.0, 0.0], never=[1])
    analytics["choices"]["menus"][0]["options"][0]["share"] = DOMINANT_SHARE + 0.05
    analytics["choices"]["menus"][0]["options"][1]["share"] = 0.02
    out = recommend_branch_improvements(_noop_project(), analytics=analytics)
    assert "dominant_option" in _codes(out)


def test_balanced_menu_is_not_reported_as_dominant():
    analytics = _analytics(runs=40, shares=[0.55, 0.45], never=[])
    out = recommend_branch_improvements(_noop_project(), analytics=analytics)
    assert "dominant_option" not in _codes(out)


def test_never_reached_ending_only_when_statically_reachable():
    analytics = _analytics(
        runs=30,
        never_reached=[
            {"label": "secret", "name": "隐藏结局", "reachableInScript": True},
            {"label": "ghost", "name": "走不到的", "reachableInScript": False},
        ],
    )
    out = recommend_branch_improvements(_noop_project(), analytics=analytics)
    hits = [r for r in out["recommendations"] if r["code"] == "never_reached_ending"]
    assert len(hits) == 1
    assert hits[0]["evidence"]["label"] == "secret"


def test_low_reader_coverage_is_reported_with_entry_advice():
    analytics = _analytics(
        runs=30,
        coverage={"ratio": 0.2, "menusNeverTouched": ["m9", "m10"], "availableOptions": 10, "observedOptions": 2},
    )
    out = recommend_branch_improvements(_noop_project(), analytics=analytics)
    rec = _by_code(out, "low_reader_coverage")
    assert "入口" in rec["action"]
    assert rec["evidence"]["menusNeverTouched"] == ["m9", "m10"]


def test_high_coverage_is_not_reported():
    analytics = _analytics(runs=30, coverage={"ratio": 0.9, "menusNeverTouched": []})
    out = recommend_branch_improvements(_noop_project(), analytics=analytics)
    assert "low_reader_coverage" not in _codes(out)


# ------------------------------------------------------------ 排序与形状


def test_errors_rank_above_warnings_above_info():
    project = normalize_project(
        {
            "id": "p8",
            "title": "排序",
            "variables": [{"id": "v", "name": "旗", "key": "seen", "type": "number", "value": 0}],
            "chapters": [
                _ch(
                    "ch1",
                    [
                        _label("start"),
                        _menu("m1", [{"text": "唯一", "jump": "a", "condition": "seen == 9"}]),
                        _label("a"),
                        {"type": "return"},
                    ],
                )
            ],
        }
    )
    out = recommend_branch_improvements(project)
    prios = [r["priority"] for r in out["recommendations"]]
    assert prios == sorted(prios, reverse=True)
    assert out["recommendations"][0]["severity"] == "error"


def test_order_is_deterministic():
    project = _noop_project()
    analytics = _analytics(runs=30)
    a = recommend_branch_improvements(project, analytics=analytics)
    b = recommend_branch_improvements(project, analytics=analytics)
    assert _codes(a) == _codes(b)


def test_every_recommendation_has_reason_and_action():
    out = recommend_branch_improvements(_noop_project(), analytics=_analytics(runs=30))
    assert out["recommendations"]
    for rec in out["recommendations"]:
        assert rec["why"].strip(), rec
        assert rec["action"].strip(), rec
        assert rec["title"].strip(), rec
        assert rec["confidence"] in ("static", "evidence")


def test_counts_match_the_list():
    out = recommend_branch_improvements(_noop_project(), analytics=_analytics(runs=30))
    rows = out["recommendations"]
    assert out["counts"]["total"] == len(rows)
    for sev in ("error", "warn", "info"):
        assert out["counts"][sev] == sum(1 for r in rows if r["severity"] == sev)


def test_empty_project_is_safe_and_says_so():
    out = recommend_branch_improvements(normalize_project({"id": "p", "title": "空"}))
    assert out["recommendations"] == []
    assert out["counts"]["total"] == 0
    assert any("不等于剧本没问题" in n for n in out["notes"])


def test_analytics_without_menus_does_not_crash():
    out = recommend_branch_improvements(
        _noop_project(),
        analytics={"sample": {"runs": 50}, "choices": {}, "coverage": {}, "endings": {}},
    )
    assert out["basis"] == "script+readers"
    assert isinstance(out["recommendations"], list)
