"""Quality gate — mandatory check before chapter finalize."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.core.agent_context import _blocks_to_plain
from app.core.ai import DeepSeekConfig
from app.core.pipeline.apply_draft import apply_draft_to_chapter
from app.core.pipeline.ledger import digest_chapter_into_ledger, get_ledger, set_ledger
from app.core.pipeline.orchestrator import (
    quality_gate_from_check,
    stage_check,
    stage_check_async,
)
from app.core.pipeline.run_history import append_harness_run
from app.domain.types import VnProject


def run_quality_gate(
    draft: str,
    *,
    require_zero_warn: bool = False,
    beat_sheet: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Sync gate (keyword beats only). Prefer run_quality_gate_async."""
    check = stage_check(draft, beat_sheet=beat_sheet)
    gate = quality_gate_from_check(check)
    if require_zero_warn and gate["pass"] and int(check.get("warnCount") or 0) > 0:
        gate = {
            **gate,
            "pass": False,
            "message": f"严格门禁：仍有 {check.get('warnCount')} 条警告须处理",
        }
    return {"check": check, "gate": gate}


async def run_quality_gate_async(
    draft: str,
    *,
    cfg: Optional[DeepSeekConfig] = None,
    beat_sheet: Optional[Dict[str, Any]] = None,
    require_zero_warn: bool = False,
    semantic_beats: bool = True,
    project: Optional[VnProject] = None,
    chapter_id: Optional[str] = None,
    voice_check: bool = False,
    voice_hard: bool = False,
) -> Dict[str, Any]:
    check = await stage_check_async(
        draft,
        beat_sheet=beat_sheet,
        cfg=cfg,
        semantic_beats=semantic_beats and cfg is not None,
        project=project,
        chapter_id=chapter_id,
        voice_check=voice_check and cfg is not None,
        voice_hard=voice_hard,
    )
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
    apply_draft: bool = True,
) -> Dict[str, Any]:
    """
    Sync finalize (keyword gate + heuristic ledger). Prefer finalize_chapter_async.
    """
    ch = next((c for c in project.chapters if c.id == chapter_id), None)
    if not ch:
        raise ValueError("章节不存在")
    text = (draft_override or "").strip()
    if not text:
        text = _blocks_to_plain(ch.blocks, project.characters) or ""
    result = run_quality_gate(text, require_zero_warn=require_zero_warn)
    return _finalize_body(
        project,
        chapter_id,
        text=text,
        draft_override=draft_override,
        result=result,
        apply_draft=apply_draft,
        update_ledger=update_ledger,
        enrich_meta=None,
        persist_run=True,
    )


async def finalize_chapter_async(
    project: VnProject,
    chapter_id: str,
    *,
    cfg: Optional[DeepSeekConfig] = None,
    draft_override: Optional[str] = None,
    require_zero_warn: bool = False,
    update_ledger: bool = True,
    apply_draft: bool = True,
    enrich_ledger: bool = True,
    beat_sheet: Optional[Dict[str, Any]] = None,
    semantic_beats: bool = True,
    voice_check: bool = True,
    voice_hard: bool = False,
) -> Dict[str, Any]:
    """
    Industrial finalize: async full audit + optional semantic beats + voice,
    structured apply, optional LLM ledger enrich, harness run history.
    """
    ch = next((c for c in project.chapters if c.id == chapter_id), None)
    if not ch:
        raise ValueError("章节不存在")
    text = (draft_override or "").strip()
    if not text:
        text = _blocks_to_plain(ch.blocks, project.characters) or ""

    result = await run_quality_gate_async(
        text,
        cfg=cfg,
        beat_sheet=beat_sheet,
        require_zero_warn=require_zero_warn,
        semantic_beats=semantic_beats,
        project=project,
        chapter_id=chapter_id,
        voice_check=voice_check,
        voice_hard=voice_hard,
    )

    enrich_meta: Optional[Dict[str, Any]] = None
    llm_kwargs: Dict[str, Any] = {}
    if (
        result["gate"].get("pass")
        and update_ledger
        and enrich_ledger
        and cfg is not None
    ):
        try:
            from app.core.pipeline.ledger_enrich import enrich_chapter_ledger_payload

            # Apply draft first conceptually for enrich text — enrich reads chapter;
            # if draft_override will apply, enrich from override text via temp apply.
            vn_for_enrich = project
            if apply_draft and (draft_override or "").strip():
                vn_for_enrich = apply_draft_to_chapter(
                    project, chapter_id, draft_override or "", mode="replace"
                )
            payload = await enrich_chapter_ledger_payload(
                cfg, vn_for_enrich, chapter_id
            )
            llm_kwargs = {
                "llm_facts": payload.get("llm_facts"),
                "llm_states": payload.get("llm_states"),
                "llm_foreshadows": payload.get("llm_foreshadows"),
            }
            enrich_meta = {
                "enrich": True,
                "factCount": len(payload.get("llm_facts") or []),
                "stateCount": len(payload.get("llm_states") or []),
                "foreshadowCount": len(payload.get("llm_foreshadows") or []),
                "error": None,
            }
        except Exception as exc:  # noqa: BLE001
            enrich_meta = {"enrich": False, "error": str(exc)[:200]}

    out = _finalize_body(
        project,
        chapter_id,
        text=text,
        draft_override=draft_override,
        result=result,
        apply_draft=apply_draft,
        update_ledger=update_ledger,
        enrich_meta=enrich_meta,
        ledger_kwargs=llm_kwargs,
        persist_run=True,
    )
    out["enrichMeta"] = enrich_meta
    return out


def _finalize_body(
    project: VnProject,
    chapter_id: str,
    *,
    text: str,
    draft_override: Optional[str],
    result: Dict[str, Any],
    apply_draft: bool,
    update_ledger: bool,
    enrich_meta: Optional[Dict[str, Any]],
    ledger_kwargs: Optional[Dict[str, Any]] = None,
    persist_run: bool = True,
) -> Dict[str, Any]:
    gate = result["gate"]
    stamp = {
        "pass": bool(gate.get("pass")),
        "at": datetime.now(timezone.utc).isoformat(),
        "errorCount": gate.get("errorCount"),
        "warnCount": gate.get("warnCount"),
        "message": gate.get("message"),
        "beatMode": (result.get("check") or {}).get("beatMode"),
        "voiceChecked": (result.get("check") or {}).get("voiceChecked"),
    }

    vn = project
    applied = False
    if gate.get("pass") and apply_draft and (draft_override or "").strip():
        vn = apply_draft_to_chapter(vn, chapter_id, draft_override or "", mode="replace")
        applied = True

    data = vn.model_dump()
    chapters: List[Dict[str, Any]] = []
    for c in data.get("chapters") or []:
        if c.get("id") == chapter_id:
            c = {**c, "qualityGate": stamp}
        chapters.append(c)
    data["chapters"] = chapters
    vn = VnProject.model_validate(data)

    ledger_updated = False
    if gate.get("pass") and update_ledger:
        ledger = digest_chapter_into_ledger(
            vn, chapter_id, **(ledger_kwargs or {})
        )
        vn = set_ledger(vn, ledger)
        ledger_updated = True

    if persist_run:
        vn = append_harness_run(
            vn,
            kind="finalize",
            chapter_id=chapter_id,
            gate=gate,
            check=result.get("check"),
            stages=["gate", "finalize"],
            applied=applied,
            enrich_meta=enrich_meta,
        )

    return {
        **result,
        "qualityGate": stamp,
        "project": vn,
        "applied": applied,
        "ledgerUpdated": ledger_updated,
        "ledger": get_ledger(vn) if ledger_updated else None,
        "draftChars": len(text or ""),
    }
