"""P1: narrative critic must not silently pass on parse failure."""
from __future__ import annotations

from app.core.narrative_review import _parse_review_json


def test_parse_fail_is_not_ok():
    r = _parse_review_json("not json at all {{{")
    assert r.ok is False
    assert "critic_parse_failed" in r.issues


def test_parse_ok_true():
    r = _parse_review_json('{"ok": true, "issues": [], "note": "fine"}')
    assert r.ok is True


def test_parse_ok_false_with_revise():
    r = _parse_review_json(
        '{"ok": false, "issues": ["qa"], "revised_text": "改后正文足够长。"}'
    )
    assert r.ok is False
    assert r.revisedText
    assert "qa" in r.issues


def test_parse_rubric_scores_dict():
    """Rubric 化：scores 以 {dim: {score, evidence}} 解析。"""
    r = _parse_review_json(
        '{"ok": false, "scores": {"social": {"score": 2, "evidence": "追问两次"}, '
        '"dialogue": 3}, "issues": ["x"], "revised_text": "改后。"}'
    )
    assert r.scores is not None
    assert r.scores["social"]["score"] == 2
    assert r.scores["social"]["evidence"] == "追问两次"
    # 裸数字也兼容
    assert r.scores["dialogue"]["score"] == 3


def test_parse_rubric_scores_missing_is_none():
    r = _parse_review_json('{"ok": true, "issues": [], "note": "ok"}')
    assert r.scores is None
