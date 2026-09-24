"""比例读数必须带区间（Dror et al. 显著性指南那一条）。

离线 A/B 那套（`core/eval_stats.py` 的配对 bootstrap / 符号检验 / McNemar）早就有了；
这一轮补的是**比例型读数**——试玩样本常常只有个位数，而界面上显示的是百分比。

这里只测纯函数：`wilson_interval` 的数学性质，以及它被接到试玩遥测的两处
（选项占比、结局到达率）与"读者证据"建议上。
"""

from __future__ import annotations

import math

import pytest

from app.core.eval_stats import format_proportion, wilson_interval, z_for_alpha

# ---- 正态分位数：与标准表对齐（写死期望值，防止逼近式被改坏） ------------------


@pytest.mark.parametrize(
    "alpha,expected",
    [
        (0.10, 1.644854),
        (0.05, 1.959964),
        (0.02, 2.326348),
        (0.01, 2.575829),
    ],
)
def test_z_for_alpha_matches_standard_tables(alpha, expected):
    assert z_for_alpha(alpha) == pytest.approx(expected, abs=1e-6)


def test_z_for_alpha_rejects_impossible_values():
    for bad in (0, 1, -0.1, 2):
        with pytest.raises(ValueError):
            z_for_alpha(bad)


# ---- Wilson 区间的性质 ---------------------------------------------------------


def test_wilson_interval_contains_point_estimate_and_stays_in_range():
    for k, n in ((0, 1), (1, 1), (0, 7), (7, 7), (1, 2), (3, 10), (13, 13), (99, 100)):
        ci = wilson_interval(k, n)
        assert 0.0 <= ci["lo"] <= ci["p"] <= ci["hi"] <= 1.0, (k, n, ci)


def test_small_sample_interval_is_wide_and_flagged():
    """n=5 时「80%」的 95% 区间约 38%–96%：必须被标成"样本太少"。"""
    ci = wilson_interval(4, 5)
    assert ci["p"] == 0.8
    assert ci["lo"] == pytest.approx(0.3756, abs=0.01)
    assert ci["hi"] == pytest.approx(0.9638, abs=0.01)
    assert ci["wide"] is True
    assert ci["thin"] is True


def test_five_out_of_five_is_thin_even_though_not_half_wide():
    """5/5 的区间是 57%–100%（宽 0.44，不到 0.5），但它同样撑不住"读者一致选它"。"""
    ci = wilson_interval(5, 5)
    assert ci["wide"] is False
    assert ci["thin"] is True
    assert "样本太少" in format_proportion(ci)


def test_large_sample_interval_is_narrow_and_not_flagged():
    ci = wilson_interval(800, 1000)
    assert ci["lo"] == pytest.approx(0.774, abs=0.01)
    assert ci["hi"] == pytest.approx(0.823, abs=0.01)
    assert ci["wide"] is False
    assert ci["thin"] is False


def test_zero_and_full_are_not_degenerate():
    """「没人选」与「都选它」在 Wilson 下仍是区间，而不是 0 宽度——这正是它比正态近似好的地方。"""
    none_ci = wilson_interval(0, 5)
    assert none_ci["lo"] == 0.0
    assert none_ci["hi"] > 0.3  # 0/5 不代表"永远没人选"
    all_ci = wilson_interval(5, 5)
    assert all_ci["hi"] == 1.0
    assert all_ci["lo"] < 0.7


def test_no_samples_returns_none_not_zero():
    ci = wilson_interval(0, 0)
    assert ci == {"n": 0, "k": 0, "p": None, "lo": None, "hi": None, "alpha": 0.05}


def test_successes_are_clamped_to_total():
    """脏数据（k > n）不该算出越界区间。"""
    ci = wilson_interval(9, 4)
    assert ci["k"] == 4
    assert ci["p"] == 1.0
    assert ci["hi"] <= 1.0


def test_alpha_changes_width_monotonically():
    """置信水平越高区间越宽（0.01 的区间必须比 0.10 宽）。"""
    narrow = wilson_interval(4, 5, alpha=0.10)
    wide = wilson_interval(4, 5, alpha=0.01)
    assert wide["width"] > narrow["width"]


def test_interval_width_shrinks_with_n():
    """同样比例、样本越多区间越窄（这是"样本量"唯一该被这样用的地方）。"""
    small = wilson_interval(8, 10)
    big = wilson_interval(80, 100)
    assert big["width"] < small["width"]
    assert not big["wide"]


def test_format_proportion_is_readable_and_says_when_sample_is_thin():
    assert format_proportion(wilson_interval(4, 5)) == "80%（95%CI 38%–96%，n=5，样本太少）"
    assert "样本太少" not in format_proportion(wilson_interval(800, 1000))
    assert format_proportion(wilson_interval(0, 0)) == "n/a（没有样本）"


def test_interval_matches_closed_form_for_a_known_case():
    """对 n=10、k=5 手算一遍（半宽公式），防止实现被改成"看起来差不多"。"""
    ci = wilson_interval(5, 10)
    z = z_for_alpha(0.05)
    n, phat = 10, 0.5
    denom = 1 + z * z / n
    centre = (phat + z * z / (2 * n)) / denom
    half = z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n)) / denom
    assert ci["lo"] == pytest.approx(centre - half, abs=1e-3)
    assert ci["hi"] == pytest.approx(centre + half, abs=1e-3)


# ---- 接进建议：区间也进了"读者证据" --------------------------------------------


def test_dominant_option_recommendation_carries_the_interval_and_a_sample_warning():
    from app.core.branch_recommendations import recommend_branch_improvements
    from app.core.project import normalize_project

    project = normalize_project(
        {
            "id": "p-dom",
            "title": "伪二元",
            "chapters": [
                {
                    "id": "ch1",
                    "title": "第一章",
                    "blocks": [
                        {"type": "label", "id": "start", "name": "start"},
                        {
                            "type": "menu",
                            "id": "m1",
                            "prompt": "选哪个？",
                            "choices": [
                                {"text": "A", "jump": "l1"},
                                {"text": "B", "jump": "l2"},
                            ],
                        },
                        {"type": "label", "id": "l1", "name": "l1"},
                        {"type": "narration", "text": "A 线。"},
                        {"type": "label", "id": "l2", "name": "l2"},
                        {"type": "narration", "text": "B 线。"},
                    ],
                }
            ],
        }
    )
    # 小样本 + 极端占比：5 次选择里 5 次都选第 0 项
    analytics = {
        "sample": {"runs": 5, "finishedRuns": 5},
        "choices": {
            "menus": [
                {
                    "menuId": "m1",
                    "chapterId": "ch1",
                    "selections": 5,
                    "options": [
                        {"index": 0, "selected": 5, "share": 1.0, "shareCi": wilson_interval(5, 5)},
                        {"index": 1, "selected": 0, "share": 0.0, "shareCi": wilson_interval(0, 5)},
                    ],
                }
            ]
        },
        "coverage": {"ratio": 1.0},
        "funnel": {"chapters": []},
        "endings": {"reached": [], "neverReached": []},
    }
    out = recommend_branch_improvements(project, analytics=analytics, min_runs=5)
    rec = next(r for r in out["recommendations"] if r["code"] == "dominant_option")
    assert rec["evidence"]["shareCi"]["n"] == 5
    assert rec["evidence"]["smallSample"] is True
    # 依据里必须如实提示样本，别把"100%"当共识
    assert "样本" in rec["why"]
    assert "不足以说明" in rec["why"]


def test_dominant_option_without_interval_does_not_crash():
    """老数据（没有 shareCi）也要照常出建议——只是没有样本提示。"""
    from app.core.branch_recommendations import recommend_branch_improvements
    from app.core.project import normalize_project

    project = normalize_project(
        {
            "id": "p-dom2",
            "title": "老数据",
            "chapters": [
                {
                    "id": "ch1",
                    "title": "第一章",
                    "blocks": [
                        {"type": "label", "id": "start", "name": "start"},
                        {
                            "type": "menu",
                            "id": "m1",
                            "prompt": "选哪个？",
                            "choices": [{"text": "A", "jump": "l1"}, {"text": "B", "jump": "l2"}],
                        },
                        {"type": "label", "id": "l1", "name": "l1"},
                        {"type": "narration", "text": "A 线。"},
                        {"type": "label", "id": "l2", "name": "l2"},
                        {"type": "narration", "text": "B 线。"},
                    ],
                }
            ],
        }
    )
    analytics = {
        "sample": {"runs": 20, "finishedRuns": 20},
        "choices": {
            "menus": [
                {
                    "menuId": "m1",
                    "chapterId": "ch1",
                    "selections": 20,
                    "options": [
                        {"index": 0, "selected": 19, "share": 0.95},
                        {"index": 1, "selected": 1, "share": 0.05},
                    ],
                }
            ]
        },
        "coverage": {"ratio": 1.0},
        "funnel": {"chapters": []},
        "endings": {"reached": [], "neverReached": []},
    }
    out = recommend_branch_improvements(project, analytics=analytics, min_runs=10)
    rec = next(r for r in out["recommendations"] if r["code"] == "dominant_option")
    assert rec["evidence"]["shareCi"] is None
    assert rec["evidence"]["smallSample"] is False
    assert "样本" not in rec["why"]
