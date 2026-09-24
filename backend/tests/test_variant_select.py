"""多变体取舍（Best-of-N）：按证据排序，缺的信号说"未测量"而不是给 0 分。

依据：Kang et al., *Scalable Best-of-N Selection for LLMs via Self-Certainty*
（NeurIPS 2025，多变体应按模型自身置信度选，无需奖励模型/额外训练）；
Wang et al., *Self-Consistency*（arXiv:2203.11171，多份采样之间一致的那份更可能可靠）。

背景（清单里那条待办的原话）：标记批改一次给 2–3 版改写时，"选哪一版"过去是
`variants[0]`——**输出顺序**，没有任何质量含义。

这里钉住的性质：
1. 排序必须由证据决定，且证据本身可复核（分数、罚分、权重都在返回值里）；
2. 拿不到的信号是 `None`（"未测量"），不是 0——0 会被当成"这版很差"；
3. N=2 时不用一致性信号（两份彼此的相似度是同一个数，没有多数可依）；
4. 分差小于 `TIE_MARGIN` 时如实说"没有明显更好的一版"，不编一个推荐；
5. `top_logprobs` 只是论文全词表 KL 的**代理**，字段名与论文区分开（`peakedness`）。
"""

from __future__ import annotations

import pytest

from app.core.variant_select import (
    MIN_CERTAINTY_TOKENS,
    SIGNAL_WEIGHTS,
    TIE_MARGIN,
    CertaintyReport,
    certainty_from_logprobs,
    char_ngram_similarity,
    consensus_scores,
    reason_for_winner,
    score_variant,
    select_best_variant,
)


def _peaked_logprobs(token_count: int = 40) -> dict:
    """每次几乎都确定的分布（峰度接近 1，置信度也高）。"""
    return {
        "content": [
            {
                "token": "他",
                "logprob": -0.01,
                "top_logprobs": [
                    {"token": "他", "logprob": -0.01},
                    {"token": "她", "logprob": -6.0},
                    {"token": "它", "logprob": -8.0},
                ],
            }
            for _ in range(token_count)
        ]
    }


def _flat_logprobs(token_count: int = 40) -> dict:
    """三个候选几乎等概率（峰度接近 0，置信度低）。"""
    return {
        "content": [
            {
                "token": "的",
                "logprob": -1.1,
                "top_logprobs": [
                    {"token": "的", "logprob": -1.09},
                    {"token": "地", "logprob": -1.10},
                    {"token": "得", "logprob": -1.11},
                ],
            }
            for _ in range(token_count)
        ]
    }


# ---- 置信度：top-k 代理 -------------------------------------------------------


def test_certainty_scores_peaked_above_flat():
    peaked = certainty_from_logprobs(_peaked_logprobs())
    flat = certainty_from_logprobs(_flat_logprobs())
    assert peaked is not None and flat is not None
    assert peaked.peakedness > 0.8 > flat.peakedness
    assert peaked.composite > flat.composite
    # 名字不能与论文的 self-certainty（全词表 KL）混用，来源要标出来
    assert peaked.kind == "topk-proxy"


def test_certainty_is_none_when_logprobs_unavailable():
    """没有 logprobs 是"未测量"，不是 0 分——0 会被读成"模型完全没把握"。"""
    assert certainty_from_logprobs(None) is None
    assert certainty_from_logprobs({}) is None
    assert certainty_from_logprobs({"content": []}) is None
    assert certainty_from_logprobs({"content": [{"token": "x"}]}) is None
    assert certainty_from_logprobs([{"token": "x", "logprob": "nope"}]) is None


def test_certainty_survives_partial_payloads():
    """缺 top_logprobs 的 token 仍算置信度；峰度只在有的 token 上算。"""
    payload = {
        "content": [
            {"token": "甲", "logprob": -0.2},  # 没有 top_logprobs
            {
                "token": "乙",
                "logprob": -0.3,
                "top_logprobs": [
                    {"token": "乙", "logprob": -0.3},
                    {"token": "丙", "logprob": -4.0},
                ],
            },
        ]
    }
    report = certainty_from_logprobs(payload)
    assert report is not None
    assert report.tokens == 2
    assert report.tokensWithTopk == 1
    assert 0.0 <= report.peakedness <= 1.0
    assert report.thin is True  # 样本太短，如实标出来


def test_certainty_flags_thin_samples():
    short = certainty_from_logprobs(_peaked_logprobs(token_count=3))
    long = certainty_from_logprobs(_peaked_logprobs(token_count=MIN_CERTAINTY_TOKENS))
    assert short is not None and long is not None
    assert short.thin is True
    assert long.thin is False


# ---- 一致性：少于 3 份就没有多数可依 -----------------------------------------


def test_similarity_bounds():
    assert char_ngram_similarity("他站住了。", "他站住了。") == 1.0
    assert char_ngram_similarity("他站住了。", "完全不同的句子。") < 0.2
    assert char_ngram_similarity("", "他站住了。") == 0.0
    # 极短文本退化成 unigram 也不能抛
    assert 0.0 <= char_ngram_similarity("甲", "乙") <= 1.0


def test_consensus_needs_three_candidates():
    texts = ["他站住了，没动。", "他站住了，没动一下。", "她慢慢坐了下去。"]
    scores = consensus_scores(texts)
    assert all(s is not None for s in scores)
    # 与那两份接近的那版一致度最高，孤立的第三版最低
    assert scores[0] > scores[2] and scores[1] > scores[2]
    # 两份候选：相似度对双方是同一个数，没有区分度 → 如实给 None
    assert consensus_scores(texts[:2]) == [None, None]
    assert consensus_scores([]) == []
    assert consensus_scores(["a"]) == [None]


# ---- 评分：缺席的信号不参与，也不变成免费加分 --------------------------------


def test_score_renormalizes_over_available_signals():
    only_constraint = score_variant("他站住了。", problems=[])
    assert only_constraint["penalties"]["consensus"] is None
    assert only_constraint["penalties"]["certainty"] is None
    assert only_constraint["weights"] == {"constraint": 1.0}
    assert only_constraint["score"] == 1.0

    all_three = score_variant(
        "他站住了。",
        problems=[],
        certainty=certainty_from_logprobs(_peaked_logprobs()),
        consensus=0.8,
    )
    assert set(all_three["weights"]) == set(SIGNAL_WEIGHTS)
    assert sum(all_three["weights"].values()) == pytest.approx(1.0, abs=1e-3)


def test_constraint_problems_lower_the_score():
    clean = score_variant("他站住了。", problems=[])
    dirty = score_variant("他站住了。", problems=["改写后长度是原文的 3.1 倍", "丢了原文里的专名：林夏"])
    assert dirty["score"] < clean["score"]
    assert dirty["penalties"]["constraint"] == 1.0


def test_constraint_outweighs_confidence():
    """一致性/置信度这类统计信号，不能把一条**能确定的问题**顶掉。

    这是**一票否决**（对齐 `pipeline.candidates.score_candidate` 的硬错误处理）：
    有问题的版本排在无问题版本之后，哪怕它的加权总分更高。
    用例构造的是最常见的翻车方式——"模型对跑偏的那一版反而更有信心"。
    """
    selection = select_best_variant(
        [
            {
                "text": "他站住了，没动。" * 8,
                "problems": ["丢了原文里的专名：林夏"],
                "certainty": certainty_from_logprobs(_peaked_logprobs()),
            },
            {
                "text": "他站住了，没动。",
                "problems": [],
                "certainty": certainty_from_logprobs(_flat_logprobs()),
            },
        ]
    )
    clean = [row for row in selection["ranking"] if not row["problems"]][0]
    problem = [row for row in selection["ranking"] if row["problems"]][0]
    assert problem["score"] > clean["score"], "用例前提：这一版的加权总分确实更高"
    assert selection["ranking"][0] is clean, "有问题的版本不该因为分数高而胜出"
    assert clean["vetoedByProblems"] is False
    assert problem["vetoedByProblems"] is True
    assert "没通过确定性检查" in selection["note"]


# ---- 选择：证据、分差与"接近并列" -------------------------------------------


def test_selection_picks_the_best_evidenced_variant_not_the_first():
    """回归：过去取的是"模型先写的那一版"（`variants[0]`），与质量无关。"""
    selection = select_best_variant(
        [
            {"text": "他站住了，没动。" * 8, "problems": ["改写后长度是原文的 3.1 倍（要求接近原文）"]},
            {"text": "他站住了，没动。", "problems": []},
            {"text": "他站住了，没动。" * 8, "problems": ["改写后长度是原文的 3.1 倍（要求接近原文）"]},
        ]
    )
    assert selection["winnerIndex"] == 1
    assert selection["ranking"][0]["variantIndex"] == 1


def test_selection_uses_certainty_when_the_other_two_are_equal():
    """两版都没有确定性问题、一致性也相同时，置信度就是唯一的区分依据。"""
    selection = select_best_variant(
        [
            {"text": "他站住了，没动。", "problems": [], "certainty": certainty_from_logprobs(_flat_logprobs())},
            {"text": "他站住了，没动。", "problems": [], "certainty": certainty_from_logprobs(_peaked_logprobs())},
        ]
    )
    assert selection["winnerIndex"] == 1


def test_selection_reports_tie_instead_of_pretending():
    selection = select_best_variant(
        [
            {"text": "他站住了，没动。", "problems": []},
            {"text": "他站住了，没动。", "problems": []},
            {"text": "他站住了，没动。", "problems": []},
        ]
    )
    assert selection["tie"] is True
    assert "没有明显更好的一版" in selection["note"]
    assert selection["margin"] < TIE_MARGIN


def test_selection_note_says_what_was_not_measured():
    no_signal = select_best_variant(
        [{"text": "甲", "problems": []}, {"text": "乙", "problems": []}]
    )
    assert "没有多数可依" in no_signal["note"]
    assert "logprobs" in no_signal["note"] and "未测量" in no_signal["note"]

    with_certainty = select_best_variant(
        [
            {"text": "甲", "problems": [], "certainty": certainty_from_logprobs(_peaked_logprobs())},
            {"text": "乙", "problems": [], "certainty": certainty_from_logprobs(_flat_logprobs())},
        ]
    )
    assert "置信度" in with_certainty["note"]
    assert "未测量" not in with_certainty["note"]


def test_selection_handles_empty_and_single():
    empty = select_best_variant([])
    assert empty["winner"] is None and empty["ranking"] == []

    single = select_best_variant([{"text": "只有这一版。", "problems": []}])
    assert single["winnerIndex"] == 0
    assert single["tie"] is False
    assert "只有一个候选" in single["note"]


def test_ranking_rows_expose_evidence_and_rank():
    selection = select_best_variant(
        [
            {"text": "他站住了，没动。", "problems": ["丢了原文里的专名：林夏"], "certainty": None},
            {"text": "她慢慢坐下。", "problems": [], "certainty": None},
        ]
    )
    ranks = [row["rank"] for row in selection["ranking"]]
    assert ranks == [1, 2]
    # 通过确定性检查的那版排在前面；每行都带自己的证据
    top = selection["ranking"][0]
    assert top["problems"] == []
    assert top["penalties"]["constraint"] == 0.0
    problem_row = selection["ranking"][1]
    assert problem_row["penalties"]["constraint"] == 0.5  # 2 条问题里出现 1 条
    assert "weights" in top and "score" in top
    # variantIndex 指向**原顺序**，前端才能把排序结果映射回自己那份列表
    assert {row["variantIndex"] for row in selection["ranking"]} == {0, 1}


def test_reason_names_the_actual_evidence():
    selection = select_best_variant(
        [
            {"text": "他站住了，没动。", "problems": [], "certainty": certainty_from_logprobs(_peaked_logprobs())},
            {"text": "她慢慢坐下。", "problems": [], "certainty": certainty_from_logprobs(_flat_logprobs())},
            {"text": "他站住了，没动一下。", "problems": [], "certainty": None},
        ]
    )
    reason = reason_for_winner(selection)
    assert "第 1 版" in reason
    assert "确定性检查通过" in reason
    assert "总分" in reason

    empty_reason = reason_for_winner(select_best_variant([]))
    assert "没有可比较的候选" in empty_reason


def test_certainty_report_is_json_serializable():
    """API 要把 ranking 直接序列化给前端：dataclass 必须能转成纯 dict。"""
    from dataclasses import asdict

    report = certainty_from_logprobs(_peaked_logprobs())
    assert isinstance(report, CertaintyReport)
    payload = asdict(report)
    assert set(payload) >= {"meanLogprob", "confidence", "peakedness", "composite", "thin", "kind"}
    assert all(isinstance(v, (int, float, bool, str)) for v in payload.values())
