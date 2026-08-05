"""Quality gate — mandatory check before chapter finalize."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.core.pipeline.ledger import digest_chapter_into_ledger, get_ledger, set_ledger
from app.core.pipeline.orchestrator import quality_gate_from_check, stage_check
from app.core.agent_context import _blocks_to_plain
from app.domain.types import VnProject


def run_quality_gate(
    draft: str,
    *,
    require_zero_warn: bool = False,
) -> Dict[str, Any]:
    check = stage_check(draft)
    gate = quality_gate_from_check(check)
    if require_zero_warn and gate["pass"] and int(check.get("warnCount") or 0) > 0:
        gate = {
            **gate,
            "pass": False,
            "message": f"严格门禁：仍有 {check.get('warnCount')} 条警告须处理",
        }
    return {"check": check, "gate": gate}


def finalize_chapter(
    project: VnProject,
    chapter_id: str,
    *,
    draft_override: Optional[str] = None,
    require_zero_warn: bool = False,
    update_ledger: bool = True,
) -> Dict[str, Any]:
    """
    Quality gate on chapter text. On pass, stamp chapter.qualityGate and
    optionally refresh writing ledger anchors.
    Does not mutate script blocks unless draft_override is used by caller separately.
    """
    ch = next((c for c in project.chapters if c.id == chapter_id), None)
    if not ch:
        raise ValueError("章节不存在")
    text = (draft_override or "").strip()
    if not text:
        text = _blocks_to_plain(ch.blocks, project.characters) or ""
    result = run_quality_gate(text, require_zero_warn=require_zero_warn)
    gate = result["gate"]
    stamp = {
        "pass": bool(gate.get("pass")),
        "at": datetime.now(timezone.utc).isoformat(),
        "errorCount": gate.get("errorCount"),
        "warnCount": gate.get("warnCount"),
        "message": gate.get("message"),
    }
    data = project.model_dump()
    chapters: List[Dict[str, Any]] = []
    for c in data.get("chapters") or []:
        if c.get("id") == chapter_id:
            c = {**c, "qualityGate": stamp}
        chapters.append(c)
    data["chapters"] = chapters
    vn = VnProject.model_validate(data)

    ledger_updated = False
    if gate.get("pass") and update_ledger:
        ledger = digest_chapter_into_ledger(vn, chapter_id)
        vn = set_ledger(vn, ledger)
        ledger_updated = True

    return {
        **result,
        "qualityGate": stamp,
        "project": vn,
        "ledgerUpdated": ledger_updated,
        "ledger": get_ledger(vn) if ledger_updated else None,
    }
