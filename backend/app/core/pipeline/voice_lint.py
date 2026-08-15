"""Merge optional LLM voice check into pipeline audit issues."""
from __future__ import annotations

from typing import Any, Dict, List, Optional

from app.core.ai import DeepSeekConfig
from app.domain.types import VnProject


def _sev_to_audit(sev: str, *, hard: bool) -> str:
    s = (sev or "info").lower()
    if s in ("high", "error"):
        return "error" if hard else "warn"
    if s in ("warn", "warning", "medium"):
        return "warn"
    return "info"


async def merge_voice_issues(
    audit: Dict[str, Any],
    *,
    cfg: Optional[DeepSeekConfig],
    project: Optional[VnProject],
    chapter_id: Optional[str],
    hard: bool = False,
) -> Dict[str, Any]:
    """
    Run voice_check and fold into audit. On failure, attach soft warn and keep audit.
    high severity → warn by default; hard=True promotes high to error.
    """
    if cfg is None or project is None:
        return audit
    try:
        from app.core.voice_check import run_voice_check

        report = await run_voice_check(cfg, project, chapterId=chapter_id)
    except Exception as exc:  # noqa: BLE001 — soft fail for pipeline
        issues = list(audit.get("issues") or [])
        issues.append(
            {
                "severity": "warn",
                "code": "voice_check_unavailable",
                "message": f"角色声线检查未完成：{str(exc)[:120]}",
                "source": "voice",
            }
        )
        return _recount({**audit, "issues": issues, "voiceChecked": False})

    issues = list(audit.get("issues") or [])
    for vi in report.issues or []:
        issues.append(
            {
                "severity": _sev_to_audit(vi.severity, hard=hard),
                "code": "voice_break",
                "message": f"[{vi.character}] {vi.note}"
                + (f"（建议：{vi.suggestion}）" if vi.suggestion else ""),
                "source": "voice",
                "quote": (vi.quote or "")[:120],
            }
        )
    notes = list(audit.get("notes") or [])
    if report.summary:
        notes.append(f"声线：{report.summary[:200]}")
    out = {
        **audit,
        "issues": issues,
        "notes": notes,
        "voiceChecked": True,
        "voiceSummary": report.summary,
        "voiceModel": report.model,
    }
    return _recount(out)


def _recount(audit: Dict[str, Any]) -> Dict[str, Any]:
    issues: List[Dict[str, Any]] = [
        i for i in (audit.get("issues") or []) if isinstance(i, dict)
    ]
    err = sum(1 for i in issues if i.get("severity") == "error")
    warn = sum(1 for i in issues if i.get("severity") == "warn")
    info = sum(1 for i in issues if i.get("severity") == "info")
    return {
        **audit,
        "errorCount": err,
        "warnCount": warn,
        "infoCount": info,
        "pass": err == 0,
        "gateReady": err == 0,
    }
