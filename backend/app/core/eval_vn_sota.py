"""垂直 SOTA 评测骨架：VN/轻小说特异指标（本地可跑，不调模型）。

**非通用 Arena**：本套件 overall 只刻画长篇 VN/LN 连贯性窄任务，
不可与 LMSYS / MMLU 等通用榜混读。

指标轴（见 docs/adr/0002-vn-ln-vertical-sota.md）：
1. 分支记忆隔离率 route_isolation
2. 伏笔支付图 foreshadow_payoff_graph
3. 伏笔结局完备 foreshadow_ending_completeness
4. 声线先验覆盖 voice_prior_coverage
5. 能力探针 capability_probes
6. 试玩钩子密度 playtest_hook_density（样本不足 score=None）
7. 可演硬伤 stageable_blocker_rate（对草稿）
8. 长程暴露 longrange_exposure_synthetic（可选）
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Dict, List, Mapping, Optional, Tuple

from app.domain.types import VnProject

#: 垂直 overall 固定权重（缺测或 score=None 的轴不参与，权重按出席轴重归一）。
#: 人评 / --ab 五维只进 appendix，永不进主 overall。
OVERALL_WEIGHTS: Dict[str, float] = {
    "route_isolation": 0.25,
    "foreshadow_ending_completeness": 0.20,
    "capability_probes": 0.20,
    "foreshadow_payoff_graph": 0.15,
    "voice_prior_coverage": 0.10,
    "playtest_hook_density": 0.05,
    "stageable_blocker_rate": 0.03,
    "longrange_exposure_synthetic": 0.02,
}

SUITE_ID = "vn_ln_vertical_sota_v1"
DISCLAIMER = (
    "非通用 Arena：本 overall 仅衡量 VN/轻小说垂直连贯性（分支隔离、伏笔、可演等），"
    "不得与通用写作榜或 LMSYS Arena 混比。"
)


def metric_route_isolation(project: VnProject, *, chapter_id: Optional[str] = None) -> Dict[str, Any]:
    """他线伏笔是否被正确隔离出本路线账本。"""
    from app.core.branch_memory import filter_ledger_for_route, resolve_branch_memory_scope
    from app.core.pipeline.ledger import get_ledger

    scope = resolve_branch_memory_scope(project, chapter_id=chapter_id)
    raw = get_ledger(project)
    filtered = filter_ledger_for_route(raw, scope)
    raw_open = [
        f
        for f in (raw.get("foreshadows") or [])
        if str(f.get("status") or "open") != "paid"
    ]
    other = list(filtered.get("_otherRouteForeshadows") or [])
    unreachable_planted = [
        f
        for f in raw_open
        if str(f.get("plantedChapter") or "") in scope.unreachable_chapter_ids
    ]
    denom = len(unreachable_planted)
    isolated = len(other)
    return {
        "id": "route_isolation",
        "score": (isolated / denom) if denom else 1.0,
        "isolated": isolated,
        "unreachablePlanted": denom,
        "mode": scope.mode,
    }


def metric_foreshadow_graph(project: VnProject, *, chapter_id: Optional[str] = None) -> Dict[str, Any]:
    from app.core.branch_memory import resolve_branch_memory_scope
    from app.core.foreshadow_graph import build_foreshadow_graph

    scope = resolve_branch_memory_scope(project, chapter_id=chapter_id)
    g = build_foreshadow_graph(
        project, reachable_chapter_ids=scope.reachable_chapter_ids
    )
    open_n = g.open_count
    edged = len({e.foreshadow_id or e.hook for e in g.edges})
    return {
        "id": "foreshadow_payoff_graph",
        "score": (edged / open_n) if open_n else 1.0,
        "open": open_n,
        "withCandidates": edged,
        "pressure": g.pressure_count,
        "edges": len(g.edges),
    }


def metric_voice_prior_coverage(
    project: VnProject, *, chapter_id: Optional[str] = None
) -> Dict[str, Any]:
    from app.core.voice_write_prior import build_voice_write_priors

    priors = build_voice_write_priors(project, chapter_id=chapter_id)
    cast_n = len(project.characters or [])
    return {
        "id": "voice_prior_coverage",
        "score": (len(priors) / min(4, cast_n)) if cast_n else 0.0,
        "priorCount": len(priors),
        "cast": cast_n,
    }


def metric_stageable_on_draft(draft: str) -> Dict[str, Any]:
    from app.core.write_gate import gate_continue_draft

    gate = gate_continue_draft(draft or "")
    blockers = [
        i for i in (gate.issues or []) if str(i.get("severity") or "") == "error"
    ]
    return {
        "id": "stageable_blocker_rate",
        "score": 1.0 if not blockers else max(0.0, 1.0 - len(blockers) / 5.0),
        "blockers": len(blockers),
        "passed": gate.passed,
    }


def metric_foreshadow_ending_completeness(project: VnProject) -> Dict[str, Any]:
    from app.core.foreshadow_endings import check_foreshadow_ending_completeness

    report = check_foreshadow_ending_completeness(project)
    return {
        "id": "foreshadow_ending_completeness",
        "score": report.completeness_rate,
        **report.as_meta(),
    }


def metric_capability_probes(
    project: VnProject, *, chapter_id: Optional[str] = None
) -> Dict[str, Any]:
    from app.core.capability_probes import run_capability_probes

    cap = run_capability_probes(project, chapter_id=chapter_id)
    avg = (
        cap.reasoning + cap.attention + cap.memory + cap.instruction_following
    ) / 4.0
    return {
        "id": "capability_probes",
        "score": avg,
        **cap.as_meta(),
    }


def metric_playtest_hook_density(
    project: VnProject,
    *,
    chapter_id: Optional[str] = None,
    analytics: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """读者证据就绪时的钩子注入覆盖率；样本不足则 score=None（不进加权 overall）。"""
    from app.core.playtest_write_hints import (
        MAX_WRITE_HINTS,
        build_playtest_write_hints,
    )

    hints = build_playtest_write_hints(
        project, chapter_id=chapter_id, analytics=analytics
    )
    actionable = int(hints.get("actionableCount") or 0)
    injected = int(hints.get("injectedCount") or 0)
    evidence = bool(hints.get("evidenceReady"))
    if not evidence:
        score = None
    else:
        denom = min(MAX_WRITE_HINTS, actionable) if actionable else 0
        score = 1.0 if denom == 0 else injected / denom
    return {
        "id": "playtest_hook_density",
        "score": score,
        "basis": hints.get("basis"),
        "evidenceReady": evidence,
        "writeSilent": bool(hints.get("writeSilent")),
        "actionableCount": actionable,
        "candidateCount": hints.get("candidateCount"),
        "injectedCount": injected,
        "sampleNote": hints.get("sampleNote"),
    }


def compute_weighted_overall(
    metrics: List[Mapping[str, Any]],
    *,
    weights: Optional[Mapping[str, float]] = None,
) -> Dict[str, Any]:
    """按固定权重表算 overall；缺测/None 轴跳过并重归一。"""
    wmap = dict(weights or OVERALL_WEIGHTS)
    parts: List[Tuple[str, float, float]] = []
    skipped: List[Dict[str, Any]] = []
    for m in metrics:
        mid = str(m.get("id") or "")
        if mid not in wmap:
            skipped.append({"id": mid, "reason": "unweighted"})
            continue
        raw = m.get("score")
        if not isinstance(raw, (int, float)):
            skipped.append({"id": mid, "reason": "no_score", "weight": wmap[mid]})
            continue
        parts.append((mid, float(raw), float(wmap[mid])))

    total_w = sum(w for _, _, w in parts)
    if total_w <= 0:
        return {
            "overall": None,
            "weights": dict(wmap),
            "applied": [],
            "skipped": skipped,
            "renormalized": False,
        }

    applied = []
    overall = 0.0
    for mid, score, w in parts:
        share = w / total_w
        contrib = score * share
        overall += contrib
        applied.append(
            {
                "id": mid,
                "score": round(score, 6),
                "weight": w,
                "share": round(share, 6),
                "contribution": round(contrib, 6),
            }
        )
    nominal = sum(wmap.values())
    return {
        "overall": round(overall, 6),
        "weights": dict(wmap),
        "applied": applied,
        "skipped": skipped,
        "renormalized": abs(total_w - nominal) > 1e-9,
        "weightSumApplied": round(total_w, 6),
    }


def build_overall_table(result: Mapping[str, Any]) -> Dict[str, Any]:
    """可归档表：权重、分项、overall、免责声明。"""
    weighted = result.get("weighted") or compute_weighted_overall(
        list(result.get("metrics") or [])
    )
    rows = []
    by_id = {str(m.get("id")): m for m in (result.get("metrics") or [])}
    for mid, w in (weighted.get("weights") or OVERALL_WEIGHTS).items():
        m = by_id.get(mid) or {}
        rows.append(
            {
                "id": mid,
                "weight": w,
                "score": m.get("score"),
                "inOverall": any(
                    a.get("id") == mid for a in (weighted.get("applied") or [])
                ),
            }
        )
    return {
        "suite": result.get("suite") or SUITE_ID,
        "disclaimer": DISCLAIMER,
        "overall": weighted.get("overall"),
        "seed": result.get("seed"),
        "chapterId": result.get("chapterId"),
        "rows": rows,
        "applied": weighted.get("applied") or [],
        "skipped": weighted.get("skipped") or [],
        "renormalized": bool(weighted.get("renormalized")),
        "appendix": result.get("appendix") or {},
    }


def attach_ab_appendix(
    result: Dict[str, Any],
    ab_path: Optional[Path] = None,
    *,
    ab_payload: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """把 ``eval --ab`` 报告挂到 appendix（永不进主 overall）。

    缺文件 / JSON 损坏时**软失败**：overall 不变，appendix 记 error。
    """
    appendix = dict(result.get("appendix") or {})
    payload: Optional[Mapping[str, Any]] = ab_payload
    src = str(ab_path) if ab_path else "inline"
    if payload is None and ab_path is not None:
        path = Path(ab_path)
        if not path.is_file():
            appendix["abFiveDim"] = {
                "note": "人评/对照盲评五维仅附录，不计入垂直 overall",
                "source": src,
                "error": "file_not_found",
            }
            out = dict(result)
            out["appendix"] = appendix
            return out
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, UnicodeError, json.JSONDecodeError) as exc:
            appendix["abFiveDim"] = {
                "note": "人评/对照盲评五维仅附录，不计入垂直 overall",
                "source": src,
                "error": f"read_failed:{type(exc).__name__}",
            }
            out = dict(result)
            out["appendix"] = appendix
            return out
    if not payload:
        return result
    # 只摘摘要字段，避免整份盲评冲爆归档
    summary_keys = (
        "kind",
        "model",
        "arms",
        "repeats",
        "seed",
        "summary",
        "scores",
        "aggregate",
        "blindFile",
    )
    slim = {k: payload[k] for k in summary_keys if k in payload}
    if not slim:
        slim = {"rawKeys": sorted(str(k) for k in payload.keys())[:40]}
    appendix["abFiveDim"] = {
        "note": "人评/对照盲评五维仅附录，不计入垂直 overall",
        "source": src,
        "data": slim,
    }
    out = dict(result)
    out["appendix"] = appendix
    return out


def run_vn_sota_suite(
    project: VnProject,
    *,
    chapter_id: Optional[str] = None,
    draft: str = "",
    include_longrange: bool = False,
    analytics: Optional[Dict[str, Any]] = None,
    seed: int = 20260409,
    ab_appendix_path: Optional[Path] = None,
) -> Dict[str, Any]:
    """跑垂直指标套件；产出加权 overall（确定性，同 seed 可复现）。"""
    metrics: List[Dict[str, Any]] = [
        metric_route_isolation(project, chapter_id=chapter_id),
        metric_foreshadow_graph(project, chapter_id=chapter_id),
        metric_foreshadow_ending_completeness(project),
        metric_voice_prior_coverage(project, chapter_id=chapter_id),
        metric_capability_probes(project, chapter_id=chapter_id),
        metric_playtest_hook_density(
            project, chapter_id=chapter_id, analytics=analytics
        ),
    ]
    if (draft or "").strip():
        metrics.append(metric_stageable_on_draft(draft))
    if include_longrange:
        try:
            from app.core.eval_longrange import detect_deterministic, run_benchmark

            bench = run_benchmark(
                chapters=30, seed=int(seed), detector=detect_deterministic
            )
            exp = float(
                ((bench.get("exposure") or {}).get("exposureRecall"))
                or ((bench.get("summary") or {}).get("exposureRecall"))
                or 0.0
            )
            metrics.append(
                {
                    "id": "longrange_exposure_synthetic",
                    "score": exp,
                    "chapters": 30,
                    "seed": int(seed),
                }
            )
        except Exception as exc:  # noqa: BLE001
            metrics.append(
                {
                    "id": "longrange_exposure_synthetic",
                    "score": None,
                    "error": str(exc)[:120],
                }
            )

    weighted = compute_weighted_overall(metrics)
    result: Dict[str, Any] = {
        "overall": weighted.get("overall"),
        "weighted": weighted,
        "metrics": metrics,
        "chapterId": chapter_id,
        "suite": SUITE_ID,
        "seed": int(seed),
        "disclaimer": DISCLAIMER,
        "appendix": {},
    }
    if ab_appendix_path is not None:
        result = attach_ab_appendix(result, Path(ab_appendix_path))
    return result


def format_vn_sota_report(result: Dict[str, Any], *, overall_table: bool = False) -> str:
    lines = [
        f"# VN/LN 垂直 SOTA 套件 {result.get('suite')}",
        f"overall={result.get('overall')}",
        DISCLAIMER,
        "",
    ]
    if overall_table:
        table = build_overall_table(result)
        lines.append("## overall 权重表")
        for row in table.get("rows") or []:
            flag = "in" if row.get("inOverall") else "skip"
            lines.append(
                f"- [{flag}] {row.get('id')}: weight={row.get('weight')} score={row.get('score')}"
            )
        lines.append("")
        if table.get("renormalized"):
            lines.append("（部分轴缺测，权重已重归一）")
            lines.append("")
    for m in result.get("metrics") or []:
        lines.append(
            f"- {m.get('id')}: score={m.get('score')}  { {k: v for k, v in m.items() if k not in ('id', 'score', 'detail')} }"
        )
    appendix = result.get("appendix") or {}
    if appendix.get("abFiveDim"):
        lines.append("")
        lines.append("## 附录：--ab 五维（不进 overall）")
        lines.append(json.dumps(appendix["abFiveDim"], ensure_ascii=False)[:800])
    return "\n".join(lines)
