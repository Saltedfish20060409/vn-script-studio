"""Persist recent harness / pipeline run summaries on the project for replay."""
from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.domain.types import VnProject

_MAX_RUNS = 24


def append_harness_run(
    project: VnProject,
    *,
    kind: str,
    chapter_id: Optional[str] = None,
    gate: Optional[Dict[str, Any]] = None,
    check: Optional[Dict[str, Any]] = None,
    stages: Optional[List[str]] = None,
    trace: Optional[List[Dict[str, Any]]] = None,
    revise_rounds: int = 0,
    applied: bool = False,
    enrich_meta: Optional[Dict[str, Any]] = None,
    instruction: str = "",
    beat_sheet: Optional[Dict[str, Any]] = None,
) -> VnProject:
    """Prepend a compact run record onto project.harnessRuns (capped).

    ``beat_sheet`` 会被一并存下：它是 plan 阶段的产出，而"声明的情感弧线"只有靠它才能
    与写出来之后实际的情绪走向对账（`analysis/story-metrics`）。此前这条记录里**没有**
    节拍表，于是那个对账在生产里**永远返回空**——一个看着有、其实从不报的功能。
    """
    gate = gate or {}
    check = check or {}
    issues = check.get("issues") or []
    blockers = [
        {
            "code": i.get("code"),
            "message": (i.get("message") or "")[:160],
            "severity": i.get("severity"),
        }
        for i in issues
        if isinstance(i, dict) and i.get("severity") == "error"
    ][:12]
    summary: Dict[str, Any] = {
        "id": f"hr_{uuid.uuid4().hex[:12]}",
        "at": datetime.now(timezone.utc).isoformat(),
        "kind": kind,
        "chapterId": chapter_id,
        "instruction": (instruction or "")[:200],
        "gatePass": bool(gate.get("pass")),
        "errorCount": int(gate.get("errorCount") or check.get("errorCount") or 0),
        "warnCount": int(gate.get("warnCount") or check.get("warnCount") or 0),
        "beatMode": check.get("beatMode"),
        "stages": list(stages or []),
        "reviseRounds": revise_rounds,
        "applied": applied,
        "blockers": blockers,
        "trace": (trace or [])[-16:],
    }
    if enrich_meta:
        summary["enrichMeta"] = enrich_meta
    if isinstance(beat_sheet, dict) and beat_sheet:
        # 只留对账需要的字段，别把整张表塞进每次运行的历史里
        keep = ("goal", "beats", "emotionStart", "emotionEnd", "triggers", "hooks", "constraints")
        summary["beatSheet"] = {k: beat_sheet[k] for k in keep if k in beat_sheet}

    data = project.model_dump()
    runs = list(data.get("harnessRuns") or [])
    runs.insert(0, summary)
    data["harnessRuns"] = runs[:_MAX_RUNS]
    return VnProject.model_validate(data)


def list_harness_runs(project: VnProject, *, limit: int = 12) -> List[Dict[str, Any]]:
    runs = getattr(project, "harnessRuns", None) or []
    if not isinstance(runs, list):
        return []
    return [r for r in runs if isinstance(r, dict)][: max(1, limit)]
