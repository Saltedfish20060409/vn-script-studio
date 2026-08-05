"""Plan → Write → Check → Revise orchestrator."""
from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from app.core.ai import DeepSeekConfig
from app.core.agent_context import _blocks_to_plain
from app.core.harness.pipeline import (
    audit_draft,
    build_writer_user_prompt,
    run_harness_llm,
)
from app.core.novel_memory import format_memory_for_agent
from app.core.pipeline.ledger import format_ledger_for_agent, get_ledger
from app.core.pipeline.style_skill import (
    load_style_skill,
    merge_audit_with_style,
)
from app.domain.types import VnProject
from app.services.novel_memory import get_latest_continuity


def _extract_json_obj(text: str) -> Optional[Dict[str, Any]]:
    raw = (text or "").strip()
    if not raw:
        return None
    try:
        data = json.loads(raw)
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        pass
    m = re.search(r"\{[\s\S]*\}", raw)
    if not m:
        return None
    try:
        data = json.loads(m.group(0))
        return data if isinstance(data, dict) else None
    except json.JSONDecodeError:
        return None


async def stage_plan(
    cfg: DeepSeekConfig,
    project: VnProject,
    *,
    instruction: str,
    chapter_id: Optional[str] = None,
) -> Dict[str, Any]:
    skill = load_style_skill()
    ch_hint = ""
    if chapter_id:
        ch = next((c for c in project.chapters if c.id == chapter_id), None)
        if ch:
            plain = _blocks_to_plain(ch.blocks, project.characters)
            ch_hint = f"当前章「{ch.title}」末尾：\n{(plain or '')[-800:]}"
    ledger_block = format_ledger_for_agent(get_ledger(project))
    prompt = (
        f"{skill.confirm_preamble()}\n\n"
        f"{skill.prompt_block(max_chars=2200)}\n\n"
        "请输出本场景的节拍表（Beat Sheet），用 JSON：\n"
        '{"goal":"...","beats":[{"name":"...","action":"..."}],'
        '"emotionStart":{"角色":"..."},"emotionEnd":{"角色":"..."},'
        '"triggers":["物件或触发"],"hooks":"收束钩子","constraints":["勿推翻的事实"]}\n'
        "只要 JSON。\n\n"
        f"用户意图：{instruction or '续写下场戏'}\n\n"
        f"{ch_hint}\n\n{ledger_block}"
    )
    llm = await run_harness_llm(
        cfg, role="architect", user_prompt=prompt, project=project, temperature=0.45
    )
    parsed = _extract_json_obj(llm.get("content") or "")
    return {
        "stage": "plan",
        "content": llm.get("content") or "",
        "beatSheet": parsed,
        "model": llm.get("model"),
        "styleConfirmed": True,
    }


async def stage_write(
    cfg: DeepSeekConfig,
    project: VnProject,
    *,
    instruction: str,
    chapter_id: Optional[str] = None,
    selection: str = "",
    beat_sheet: Optional[Dict[str, Any]] = None,
    long_memory: str = "",
    db_continuity: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    skill = load_style_skill()
    chapter_tail = ""
    if chapter_id:
        ch = next((c for c in project.chapters if c.id == chapter_id), None)
        if ch:
            plain = _blocks_to_plain(ch.blocks, project.characters)
            chapter_tail = (plain or "")[-1200:]
    ledger_block = format_ledger_for_agent(get_ledger(project))
    mem = long_memory
    if not mem and db_continuity:
        mem = db_continuity.get("agentBlock") or ""
    beat_txt = ""
    if beat_sheet:
        beat_txt = "## 已确认节拍表\n" + json.dumps(beat_sheet, ensure_ascii=False)
    elif instruction:
        beat_txt = f"## 意图\n{instruction}"
    user = build_writer_user_prompt(
        f"{skill.confirm_preamble()}\n\n请严格按节拍表与风格 Skill 生成可上演片段（Ren'Py 风格优先）。\n{beat_txt}",
        selection=selection,
        chapter_tail=chapter_tail,
        long_memory=mem,
        lore_craft=ledger_block,
    )
    user = f"{skill.prompt_block(max_chars=2000)}\n\n{user}"
    llm = await run_harness_llm(
        cfg, role="writer", user_prompt=user, project=project, temperature=0.75
    )
    return {
        "stage": "write",
        "content": llm.get("content") or "",
        "model": llm.get("model"),
        "styleConfirmed": True,
    }


def stage_check(draft: str, *, beat_sheet: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    audit = merge_audit_with_style(audit_draft(draft), draft)
    notes: List[str] = []
    if beat_sheet and beat_sheet.get("goal"):
        notes.append(f"对照节拍目标：{beat_sheet.get('goal')}")
    return {
        "stage": "check",
        **audit,
        "notes": notes,
        "gateReady": bool(audit.get("pass")),
    }


async def stage_revise(
    cfg: DeepSeekConfig,
    project: VnProject,
    *,
    draft: str,
    check: Dict[str, Any],
) -> Dict[str, Any]:
    skill = load_style_skill()
    if check.get("pass") and int(check.get("warnCount") or 0) == 0:
        return {
            "stage": "revise",
            "content": draft,
            "skipped": True,
            "message": "检查已通过，无需修正",
        }
    issues = check.get("issues") or []
    prompt = (
        f"{skill.confirm_preamble()}\n\n"
        f"{skill.prompt_block(max_chars=1800)}\n\n"
        "根据检查报告做**最小化改动**修正。保持剧情意图与节拍。"
        "先列仍须注意的点（短），再给出完整改写正文。\n\n"
        f"## 检查报告\n{json.dumps(issues[:24], ensure_ascii=False)}\n\n"
        f"## 原文\n{draft[:8000]}"
    )
    llm = await run_harness_llm(
        cfg, role="editor", user_prompt=prompt, project=project, temperature=0.4
    )
    revised = llm.get("content") or ""
    # Prefer last fenced or whole content as draft; keep full for chat display
    return {
        "stage": "revise",
        "content": revised,
        "skipped": False,
        "model": llm.get("model"),
    }


async def run_pipeline(
    cfg: DeepSeekConfig,
    project: VnProject,
    *,
    instruction: str = "",
    chapter_id: Optional[str] = None,
    selection: str = "",
    draft: str = "",
    stages: Optional[List[str]] = None,
    db=None,
    project_id: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Run selected stages. Default full loop: plan → write → check → revise → check.
    If draft provided and stages omit write, can check/revise existing draft.
    """
    wanted = stages or ["plan", "write", "check", "revise", "check"]
    result: Dict[str, Any] = {
        "stages": [],
        "plan": None,
        "draft": draft or "",
        "check": None,
        "revise": None,
        "finalDraft": draft or "",
        "gate": None,
    }

    continuity = None
    if db is not None and project_id:
        continuity = await get_latest_continuity(db, project_id)

    beat_sheet = None
    current = draft or ""

    if "plan" in wanted:
        plan = await stage_plan(
            cfg, project, instruction=instruction, chapter_id=chapter_id
        )
        result["plan"] = plan
        result["stages"].append("plan")
        beat_sheet = plan.get("beatSheet")

    if "write" in wanted:
        written = await stage_write(
            cfg,
            project,
            instruction=instruction,
            chapter_id=chapter_id,
            selection=selection,
            beat_sheet=beat_sheet,
            db_continuity=continuity,
        )
        result["stages"].append("write")
        current = written.get("content") or current
        result["draft"] = current

    if not current.strip() and "check" in wanted:
        result["check"] = {
            "stage": "check",
            "pass": False,
            "errorCount": 1,
            "warnCount": 0,
            "infoCount": 0,
            "issues": [
                {
                    "severity": "error",
                    "code": "empty_draft",
                    "message": "无正文可检查",
                    "source": "pipeline",
                }
            ],
        }
        result["stages"].append("check")
        result["finalDraft"] = current
        result["gate"] = quality_gate_from_check(result["check"])
        return result

    # First check
    check_indices = [i for i, s in enumerate(wanted) if s == "check"]
    ran_first_check = False
    if check_indices:
        chk = stage_check(current, beat_sheet=beat_sheet)
        result["check"] = chk
        result["stages"].append("check")
        ran_first_check = True

    if "revise" in wanted and result.get("check"):
        rev = await stage_revise(
            cfg, project, draft=current, check=result["check"]
        )
        result["revise"] = rev
        result["stages"].append("revise")
        if not rev.get("skipped"):
            # Try to pull body after last markdown header
            body = rev.get("content") or current
            current = body
            result["draft"] = current

    # Second check after revise if requested twice or always after revise
    if "revise" in wanted and ran_first_check:
        chk2 = stage_check(current, beat_sheet=beat_sheet)
        result["check"] = chk2
        result["stages"].append("check")

    result["finalDraft"] = current
    result["gate"] = quality_gate_from_check(result.get("check") or stage_check(current))
    return result


def quality_gate_from_check(check: Dict[str, Any]) -> Dict[str, Any]:
    err = int(check.get("errorCount") or 0)
    warn = int(check.get("warnCount") or 0)
    passed = err == 0
    return {
        "pass": passed,
        "errorCount": err,
        "warnCount": warn,
        "message": (
            "质量门禁通过：无硬错误，可考虑定稿"
            if passed
            else f"质量门禁未通过：{err} 个硬错误须修正后再定稿"
        ),
        "blockers": [
            i
            for i in (check.get("issues") or [])
            if i.get("severity") == "error"
        ][:16],
    }
