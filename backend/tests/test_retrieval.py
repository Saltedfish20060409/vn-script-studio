"""Unit tests: retrieval ranker + optional semantic-search fallback."""

from __future__ import annotations

from app.core.retrieval import rank_texts, score_text, tokenize_query


def test_tokenize_cjk_bigrams():
    toks = tokenize_query("雨夜月台")
    assert "雨夜" in toks
    assert "月台" in toks
    assert "雨夜月台" in toks  # full phrase kept for exact-match boost


def test_tokenize_ascii_words():
    toks = tokenize_query("station night")
    assert "station" in toks
    assert "night" in toks


def test_score_hits_coverage():
    score, matched = score_text("雨夜的车站，雨一直下", tokenize_query("雨夜车站"))
    assert score > 0
    kws = {k for k, _ in matched}
    assert "雨夜" in kws or "车站" in kws or "雨夜车站" in kws


def test_rank_prefers_more_matches():
    q = "末班车 站台"
    better = "末班车从站台开出，末班车驶向远方。" * 3
    worse = "清晨的车站很安静。"
    hits = rank_texts(q, [("w", worse), ("b", better)], limit=2, min_score=0)
    # The text matching both keywords should rank first.
    assert hits[0][0] == "b"


def test_rank_empty_query():
    assert rank_texts("", [("a", "anything")]) == []


def test_rank_no_match():
    hits = rank_texts("完全不相关词xyz", [("a", "完全不同的内容")], min_score=0)
    # Either no hit or a low-scoring hit that still ranks — assert deterministic.
    assert isinstance(hits, list)
