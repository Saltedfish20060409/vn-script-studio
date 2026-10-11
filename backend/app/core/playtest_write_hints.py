"""试玩覆盖 → 写路径钩子密度：把分支改进建议压成短 framing 块。

写路径注入闸：``basis == script+readers``（样本量够）才出 framing 块；
否则只记 meta（候选列表可算、不进 prompt）——与 P1「无试玩数据时静默」一致。
经验类建议本身已由 ``recommend_branch_improvements`` 按 ``MIN_RUNS_FOR_EVIDENCE`` 闸掉。
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Tuple

from app.core.branch_recommendations import (
    MIN_RUNS_FOR_EVIDENCE,
    recommend_branch_improvements,
)
from app.domain.types import VnProject

#: 写入 framing 的上限，避免冲掉正文指令。
MAX_WRITE_HINTS = 5


def _focus_boost(row: Mapping[str, Any], chapter_id: Optional[str]) -> int:
    if not chapter_id:
        return 0
    where = str(row.get("where") or "")
    cid = str(chapter_id)
    if cid and cid in where:
        return 30
    return 0


def select_write_hints(
    report: Mapping[str, Any],
    *,
    chapter_id: Optional[str] = None,
    max_items: int = MAX_WRITE_HINTS,
) -> List[Dict[str, Any]]:
    """从建议报告里挑出写路径可用的短条目（优先焦点章、error/warn）。"""
    rows = list(report.get("recommendations") or [])
    scored: List[Tuple[int, Dict[str, Any]]] = []
    for r in rows:
        if not isinstance(r, Mapping):
            continue
        sev = str(r.get("severity") or "info")
        # info 级（选项诗学等）默认不进写路径，避免噪声
        if sev == "info":
            continue
        pri = int(r.get("priority") or 0) + _focus_boost(r, chapter_id)
        scored.append((pri, dict(r)))
    scored.sort(key=lambda x: (-x[0], str(x[1].get("code") or "")))
    out: List[Dict[str, Any]] = []
    for _, row in scored[: max(0, int(max_items))]:
        out.append(
            {
                "code": str(row.get("code") or ""),
                "severity": str(row.get("severity") or "warn"),
                "title": str(row.get("title") or "")[:80],
                "action": str(row.get("action") or "")[:160],
                "where": str(row.get("where") or "")[:80],
                "confidence": str(row.get("confidence") or "static"),
            }
        )
    return out


def format_playtest_hints_block(
    items: List[Mapping[str, Any]],
    *,
    basis: str = "script-only",
    sample_note: str = "",
) -> str:
    if not items:
        return ""
    lines = [
        "## 试玩/结构改稿提示（钩子密度）",
        f"依据：{basis}。" + (f" {sample_note}" if sample_note else ""),
        "本场优先处理下列问题（只改当前意图相关处，勿另开支线）：",
    ]
    for i, it in enumerate(items, 1):
        title = str(it.get("title") or it.get("code") or "建议")
        action = str(it.get("action") or "").strip()
        where = str(it.get("where") or "").strip()
        bit = f"{i}. [{it.get('severity')}] {title}"
        if where:
            bit += f"（{where}）"
        if action:
            bit += f" → {action}"
        lines.append(bit)
    return "\n".join(lines).strip()


def build_playtest_write_hints(
    project: VnProject,
    *,
    chapter_id: Optional[str] = None,
    analytics: Optional[Mapping[str, Any]] = None,
    min_runs: int = MIN_RUNS_FOR_EVIDENCE,
    max_items: int = MAX_WRITE_HINTS,
) -> Dict[str, Any]:
    """产出写路径可用的 hints + framing 块 + meta。"""
    report = recommend_branch_improvements(
        project,
        analytics=analytics,
        min_runs=min_runs,
    )
    actionable = [
        r
        for r in (report.get("recommendations") or [])
        if str(r.get("severity") or "") in {"error", "warn"}
    ]
    items = select_write_hints(
        report, chapter_id=chapter_id, max_items=max_items
    )
    basis = str(report.get("basis") or "script-only")
    sample_note = str(report.get("sampleNote") or "")
    evidence_ready = basis == "script+readers"
    # 无足够读者样本：候选可算，写路径静默（只 meta）
    if evidence_ready and items:
        block = format_playtest_hints_block(items, basis=basis, sample_note="")
        injected = len(items)
    else:
        block = ""
        injected = 0
    return {
        "basis": basis,
        "sampleNote": sample_note,
        "evidenceReady": evidence_ready,
        "writeSilent": not evidence_ready,
        "minRuns": int(report.get("minRuns") or min_runs),
        "actionableCount": len(actionable),
        "candidateCount": len(items),
        "injectedCount": injected,
        "items": items,
        "block": block,
        "counts": dict(report.get("counts") or {}),
    }
