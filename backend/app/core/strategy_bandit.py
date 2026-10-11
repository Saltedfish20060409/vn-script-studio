"""最小 strategyAdapt bandit：用采纳/拒绝更新 assist 档均值建议。

样本不足（< MIN_SAMPLES）时不覆盖用户设置；只提供 suggest。
数据来自 strategy_adapt JSONL（含 outcome=accept|reject）。
"""

from __future__ import annotations

from collections import defaultdict
from dataclasses import dataclass
from pathlib import Path
from typing import Dict, List, Optional, Tuple

from app.core.strategy_adapt_log import read_recent_events, resolve_log_dir

MIN_SAMPLES = 8
ASSIST_LEVELS = ("weak", "mid", "strong")


@dataclass
class BanditSuggestion:
    assist: Optional[str]
    samples: int
    scores: Dict[str, float]
    ready: bool
    reason: str


def _score_event(ev: dict) -> Optional[Tuple[str, float]]:
    assist = str(ev.get("suggestedAssist") or ev.get("assist") or "").strip().lower()
    if assist not in ASSIST_LEVELS:
        return None
    outcome = str(ev.get("outcome") or "").strip().lower()
    if outcome == "accept":
        return assist, 1.0
    if outcome == "reject":
        return assist, 0.0
    # 无 outcome：抬档成功记弱正样本，未变化忽略
    if ev.get("changed") is True:
        return assist, 0.55
    return None


def aggregate_assist_scores(
    project_id: str,
    *,
    limit: int = 200,
    log_dir: Optional[Path] = None,
) -> Dict[str, List[float]]:
    rows = read_recent_events(project_id, limit=limit, log_dir=log_dir)
    buckets: Dict[str, List[float]] = defaultdict(list)
    for ev in rows:
        scored = _score_event(ev)
        if not scored:
            continue
        assist, val = scored
        buckets[assist].append(val)
    return dict(buckets)


def suggest_assist_from_bandit(
    project_id: str,
    *,
    log_dir: Optional[Path] = None,
    min_samples: int = MIN_SAMPLES,
) -> BanditSuggestion:
    buckets = aggregate_assist_scores(project_id, log_dir=log_dir)
    total = sum(len(v) for v in buckets.values())
    means = {
        k: (sum(v) / len(v) if v else 0.0) for k, v in buckets.items() if v
    }
    if total < int(min_samples) or not means:
        return BanditSuggestion(
            assist=None,
            samples=total,
            scores=means,
            ready=False,
            reason=f"need>={min_samples}_samples",
        )
    best = max(means.items(), key=lambda kv: (kv[1], ASSIST_LEVELS.index(kv[0])))
    return BanditSuggestion(
        assist=best[0],
        samples=total,
        scores={k: round(v, 4) for k, v in means.items()},
        ready=True,
        reason="empirical_mean",
    )


def bandit_meta(project_id: str) -> dict:
    s = suggest_assist_from_bandit(project_id)
    return {
        "ready": s.ready,
        "suggestedAssist": s.assist,
        "samples": s.samples,
        "scores": s.scores,
        "reason": s.reason,
        "logDir": str(resolve_log_dir()),
    }
