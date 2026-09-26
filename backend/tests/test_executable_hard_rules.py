"""可执行作者硬规则：只有结构上能证伪的才进校验。"""

from __future__ import annotations

from app.core.constraints import check_executable_hard_rules


def test_pov_first_hard_rule_flags_third_person_narration():
    issues = check_executable_hard_rules(
        ["必须用第一人称写"],
        first=1,
        third=20,
        first_ratio=1 / 21,
    )
    assert len(issues) == 1
    assert issues[0]["code"] == "hard_rule_pov_first"
    assert issues[0]["severity"] == "warn"


def test_pov_third_hard_rule_flags_first_person_narration():
    issues = check_executable_hard_rules(
        ["不要用第一人称，必须第三人称"],
        first=18,
        third=2,
        first_ratio=18 / 20,
    )
    assert len(issues) == 1
    assert issues[0]["code"] == "hard_rule_pov_third"


def test_insufficient_markers_is_unmeasured_not_fail():
    assert (
        check_executable_hard_rules(
            ["必须第一人称"],
            first=1,
            third=1,
            first_ratio=0.5,
        )
        == []
    )


def test_conflicting_pov_rules_skipped_here():
    """互斥人称由 detect_conflicts 管；这里不下结论，避免双重打扰。"""
    assert (
        check_executable_hard_rules(
            ["必须第一人称", "必须第三人称"],
            first=1,
            third=20,
            first_ratio=0.05,
        )
        == []
    )


def test_no_pov_hard_rule_yields_empty():
    assert (
        check_executable_hard_rules(
            ["禁止解释超自然设定"],
            first=1,
            third=20,
            first_ratio=0.05,
        )
        == []
    )
