"""P2：垂直 overall 加权与可归档表。"""

from __future__ import annotations

from app.core.eval_vn_sota import (
    DISCLAIMER,
    OVERALL_WEIGHTS,
    compute_weighted_overall,
)


def test_weights_sum_near_one():
    total = sum(OVERALL_WEIGHTS.values())
    assert abs(total - 1.0) < 1e-9


def test_weighted_skips_none_and_renormalizes():
    metrics = [
        {"id": "route_isolation", "score": 1.0},
        {"id": "foreshadow_ending_completeness", "score": 0.5},
        {"id": "capability_probes", "score": 0.8},
        {"id": "playtest_hook_density", "score": None},
    ]
    out = compute_weighted_overall(metrics)
    assert out["overall"] is not None
    assert out["renormalized"] is True
    ids = {a["id"] for a in out["applied"]}
    assert "playtest_hook_density" not in ids
    assert "route_isolation" in ids
    # 手工：出席权重 0.25+0.20+0.20=0.65
    expected = (1.0 * 0.25 + 0.5 * 0.20 + 0.8 * 0.20) / 0.65
    assert abs(float(out["overall"]) - expected) < 1e-6


def test_disclaimer_mentions_non_arena():
    assert "非通用 Arena" in DISCLAIMER


def test_ab_appendix_missing_file_soft_fails():
    from pathlib import Path

    from app.core.demo import create_demo_project
    from app.core.eval_vn_sota import run_vn_sota_suite

    p = create_demo_project()
    base = run_vn_sota_suite(p, chapter_id=p.chapters[0].id)
    missing = run_vn_sota_suite(
        p,
        chapter_id=p.chapters[0].id,
        ab_appendix_path=Path("__no_such_ab_report__.json"),
    )
    assert missing["overall"] == base["overall"]
    assert (missing.get("appendix") or {}).get("abFiveDim", {}).get(
        "error"
    ) == "file_not_found"
