"""配对统计量具的测试。

统计代码最危险的不是算错，而是**看起来很确定**。所以这里重点验证：
- 区间在跨 0 时必须说跨 0；
- 样本太少时必须承认给不出区间，而不是硬编一个；
- 同一 seed 必须完全可复现；
- 精确检验的 p 值要落在合理范围（不会出现 p>1 这种低级错误）。
"""

from __future__ import annotations

import random

from app.core.eval_stats import (
    binom_two_sided_p,
    format_ci,
    mcnemar_exact,
    paired_bootstrap_ci,
    sign_test,
    summarize_binary_paired,
    summarize_paired,
)


def test_bootstrap_ci_is_reproducible_with_same_seed():
    diffs = [1.4, 1.2, 0.5, 2.0, 0.1, 1.8, 0.9, 1.1, 1.6, 0.4]
    a = paired_bootstrap_ci(diffs, iters=800, rng=random.Random(7))
    b = paired_bootstrap_ci(diffs, iters=800, rng=random.Random(7))
    assert a == b
    c = paired_bootstrap_ci(diffs, iters=800, rng=random.Random(8))
    assert c["lo"] != a["lo"] or c["hi"] != a["hi"]


def test_bootstrap_ci_brackets_the_mean():
    diffs = [1.0, 1.5, 0.5, 2.0, 1.2, 0.8, 1.3, 1.1]
    ci = paired_bootstrap_ci(diffs, iters=2000, rng=random.Random(1))
    assert ci["lo"] <= ci["mean"] <= ci["hi"]
    assert ci["n"] == 8


def test_ci_crossing_zero_is_flagged():
    """方向相反、相互抵消的差值 → 必须报"跨 0"。"""
    diffs = [2.0, -2.0, 1.5, -1.5, 2.5, -2.5, 1.0, -1.0]
    ci = paired_bootstrap_ci(diffs, iters=2000, rng=random.Random(3))
    assert ci["crossesZero"] is True


def test_ci_not_crossing_zero_for_consistent_gain():
    diffs = [1.0, 1.2, 0.9, 1.1, 1.3, 0.8, 1.4, 1.0, 1.2, 1.1]
    ci = paired_bootstrap_ci(diffs, iters=2000, rng=random.Random(3))
    assert ci["crossesZero"] is False
    assert ci["lo"] > 0


def test_single_sample_admits_it_cannot_give_an_interval():
    ci = paired_bootstrap_ci([1.0])
    assert ci["n"] == 1
    assert ci["lo"] is None
    assert "无法给出区间" in ci["note"]


def test_empty_sample_returns_no_numbers():
    ci = paired_bootstrap_ci([])
    assert ci["n"] == 0
    assert ci["mean"] is None


def test_sign_test_counts_and_p():
    assert sign_test([1, 1, 1, -1])["positive"] == 3
    assert sign_test([1, 1, 1, -1])["negative"] == 1
    ties = sign_test([1, 0, 0, -1])
    assert ties["ties"] == 2
    assert ties["n"] == 2
    # 全对全错：极端结果 → p 很小
    assert sign_test([1] * 8)["p"] < 0.02
    assert sign_test([1, -1])["p"] == 1.0


def test_binomial_p_value_stays_in_range():
    for n in (0, 1, 5, 13, 40):
        for k in range(n + 1):
            p = binom_two_sided_p(k, n)
            assert 0.0 <= p <= 1.0, (n, k, p)
    assert binom_two_sided_p(0, 0) == 1.0


def test_symmetric_binomial_is_one():
    assert binom_two_sided_p(5, 10) == 1.0


def test_mcnemar_only_counts_discordant_pairs():
    out = mcnemar_exact(9, 0)
    assert out["discordant"] == 9
    assert out["p"] < 0.01
    same = mcnemar_exact(0, 0)
    assert same["p"] == 1.0


def test_summarize_binary_paired_separates_directions():
    # 工具臂 9 例否决、裸聊臂没有；反向 0 例
    tool = [True] * 9 + [False] * 4
    bare = [False] * 13
    out = summarize_binary_paired(tool, bare)
    assert out["b"] == 9
    assert out["c"] == 0
    assert out["neither"] == 4
    assert out["p"] < 0.01


def test_summarize_paired_ignores_cases_missing_an_arm():
    tool = [3.0, 4.0, None, 2.0]
    bare = [2.0, 3.0, 1.0, None]
    out = summarize_paired(tool, bare, iters=500, rng=random.Random(2))
    assert out["n"] == 2
    assert out["meanDiff"] == 1.0


def test_summarize_paired_reports_means_of_both_arms():
    out = summarize_paired([3.0, 3.5], [2.0, 2.5], iters=200, rng=random.Random(1))
    assert out["toolMean"] == 3.25
    assert out["bareMean"] == 2.25
    assert out["meanDiff"] == 1.0


def test_format_ci_mentions_sample_size_and_direction():
    ci = paired_bootstrap_ci([1.0] * 6, iters=300, rng=random.Random(1))
    text = format_ci(ci)
    assert "n=6" in text
    assert "不含 0" in text
    crossing = format_ci(
        paired_bootstrap_ci([2.0, -2.0, 1.0, -1.0], iters=300, rng=random.Random(1))
    )
    assert "跨 0" in crossing
    assert format_ci({"mean": None}) == "n/a"
