"""strategyAdapt bandit。"""

from __future__ import annotations

from pathlib import Path

from app.core.strategy_adapt_log import append_strategy_adapt_event
from app.core.strategy_bandit import suggest_assist_from_bandit


def test_bandit_needs_min_samples(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("VNSS_STRATEGY_ADAPT_LOG", "all")
    for i in range(3):
        append_strategy_adapt_event(
            project_id="p1",
            outcome="accept",
            adapt={"suggestedAssist": "strong", "changed": True},
            log_dir=tmp_path,
        )
    s = suggest_assist_from_bandit("p1", log_dir=tmp_path, min_samples=8)
    assert s.ready is False


def test_bandit_picks_higher_accept_rate(tmp_path: Path, monkeypatch):
    monkeypatch.setenv("VNSS_STRATEGY_ADAPT_LOG", "all")
    for _ in range(6):
        append_strategy_adapt_event(
            project_id="p2",
            outcome="accept",
            adapt={"suggestedAssist": "mid", "changed": False},
            log_dir=tmp_path,
        )
    for _ in range(6):
        append_strategy_adapt_event(
            project_id="p2",
            outcome="reject",
            adapt={"suggestedAssist": "strong", "changed": False},
            log_dir=tmp_path,
        )
    s = suggest_assist_from_bandit("p2", log_dir=tmp_path, min_samples=8)
    assert s.ready is True
    assert s.assist == "mid"
