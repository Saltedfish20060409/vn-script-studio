"""Plan → Write → Check → Revise orchestrator."""
from __future__ import annotations

import json
import re
import time
from typing import Any, Callable, Dict, List, Optional

from app.core.agent_context import _blocks_to_plain
from app.core.ai import DeepSeekConfig
from app.core.harness.audit_full import full_audit_draft
from app.core.harness.pipeline import build_writer_user_prompt, run_harness_llm
from app.core.pipeline.apply_draft import apply_draft_to_chapter, extract_script_body
from app.core.pipeline.beat_check import merge_beat_issues, resolve_beat_issues
from app.core.pipeline.ledger import format_ledger_for_agent, get_ledger
from app.core.pipeline.style_skill import load_style_skill
from app.domain.types import VnProject
from app.llm_models import DEFAULT_LLM_MODEL
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
    on_token: Optional[Callable[[str], None]] = None,
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

    if on_token is not None:
        # Token-level streaming: same prompt, SSE deltas forwarded to the sink.
        from app.core.harness.roles import build_role_system
        from app.core.llm_http import stream_chat_completions
        from app.core.renpy import project_to_context

        extra = "作品上下文（节选）：\n" + project_to_context(project)[:3500]
        system = build_role_system("writer", extra=extra, project=project)
        chunks: List[str] = []
        async for delta in stream_chat_completions(
            cfg,
            messages=[
                {"role": "system", "content": system},
                {"role": "user", "content": user},
            ],
            temperature=0.75,
        ):
            chunks.append(delta)
            try:
                on_token(delta)
            except Exception:  # noqa: BLE001 - token sink must not break run
                pass
        content = "".join(chunks)
        model = cfg.model or DEFAULT_LLM_MODEL
    else:
        llm = await run_harness_llm(
            cfg, role="writer", user_prompt=user, project=project, temperature=0.75
        )
        content = llm.get("content") or ""
        model = llm.get("model")

    return {
        "stage": "write",
        "content": content,
        "model": model,
        "styleConfirmed": True,
    }


def stage_check(draft: str, *, beat_sheet: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Sync check (keyword beats only). Prefer stage_check_async in pipeline."""
    audit = full_audit_draft(draft)
    notes: List[str] = []
    if beat_sheet and beat_sheet.get("goal"):
        notes.append(f"对照节拍目标：{beat_sheet.get('goal')}")
    from app.core.pipeline.beat_check import lint_beat_sheet

    beat_issues = lint_beat_sheet(draft, beat_sheet)
    if beat_issues:
        audit = merge_beat_issues(audit, beat_issues)
        notes.append(f"节拍对照：{len(beat_issues)} 条提示")
    return {
        "stage": "check",
        **audit,
        "notes": notes,
        "gateReady": bool(audit.get("pass")),
        "beatMode": "keyword",
    }


async def stage_check_async(
    draft: str,
    *,
    beat_sheet: Optional[Dict[str, Any]] = None,
    cfg: Optional[DeepSeekConfig] = None,
    semantic_beats: bool = True,
    project: Optional[VnProject] = None,
    chapter_id: Optional[str] = None,
    voice_check: bool = False,
    voice_hard: bool = False,
) -> Dict[str, Any]:
    audit = full_audit_draft(draft)
    notes: List[str] = []
    if beat_sheet and beat_sheet.get("goal"):
        notes.append(f"对照节拍目标：{beat_sheet.get('goal')}")
    beat_issues = await resolve_beat_issues(
        draft,
        beat_sheet,
        config=cfg,
        semantic=semantic_beats and cfg is not None,
    )
    mode = "semantic" if (semantic_beats and cfg is not None) else "keyword"
    if beat_issues:
        audit = merge_beat_issues(audit, beat_issues)
        notes.append(f"节拍对照（{mode}）：{len(beat_issues)} 条提示")
    out: Dict[str, Any] = {
        "stage": "check",
        **audit,
        "notes": notes,
        "gateReady": bool(audit.get("pass")),
        "beatMode": mode,
    }
    if voice_check and cfg is not None and project is not None:
        from app.core.pipeline.voice_lint import merge_voice_issues

        out = await merge_voice_issues(
            out,
            cfg=cfg,
            project=project,
            chapter_id=chapter_id,
            hard=voice_hard,
        )
    return out


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
        "先列仍须注意的点（短），再给出完整改写正文（可用 ```renpy 代码块）。\n\n"
        f"## 检查报告\n{json.dumps(issues[:24], ensure_ascii=False)}\n\n"
        f"## 原文\n{draft[:8000]}"
    )
    llm = await run_harness_llm(
        cfg, role="editor", user_prompt=prompt, project=project, temperature=0.4
    )
    revised = llm.get("content") or ""
    body = extract_script_body(revised) if revised.strip() else draft
    return {
        "stage": "revise",
        "content": body if body.strip() else revised,
        "rawContent": revised,
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
    apply_to_chapter: bool = False,
    apply_mode: str = "replace",
    semantic_beats: bool = True,
    max_revise_rounds: int = 2,
    voice_check: bool = True,
    voice_hard: bool = False,
    persist_run: bool = True,
    on_stage: Optional[Callable[[str, Dict[str, Any]], None]] = None,
    on_token: Optional[Callable[[str], None]] = None,
) -> Dict[str, Any]:
    """
    Run selected stages. Default: plan → write → check → revise×N → check.
    max_revise_rounds: after first check, revise+recheck until pass or cap.
    voice_check: character voice audit on the final check only.
    on_stage: sync callback fired after each stage completes (SSE progress).
    on_token: sync callback fired per write-stage text delta (SSE typing).
    """
    wanted = stages or ["plan", "write", "check", "revise", "check"]
    trace: List[Dict[str, Any]] = []
    result: Dict[str, Any] = {
        "stages": [],
        "plan": None,
        "draft": draft or "",
        "check": None,
        "revise": None,
        "reviseRounds": 0,
        "finalDraft": draft or "",
        "gate": None,
        "applied": False,
        "project": None,
        "trace": trace,
    }

    def _push_trace(
        stage: str,
        t0: float,
        *,
        ok: bool = True,
        extra: Optional[Dict[str, Any]] = None,
    ) -> None:
        row: Dict[str, Any] = {
            "stage": stage,
            "ms": int((time.perf_counter() - t0) * 1000),
            "ok": ok,
        }
        if extra:
            row.update(extra)
        trace.append(row)
        if on_stage is not None:
            try:
                on_stage(stage, dict(row))
            except Exception:  # noqa: BLE001 - progress sink must not break run
                pass

    continuity = None
    if db is not None and project_id:
        continuity = await get_latest_continuity(db, project_id)

    beat_sheet = None
    current = draft or ""
    vn = project
    want_check = "check" in wanted
    want_revise = "revise" in wanted
    rounds_cap = max(0, int(max_revise_rounds))

    if "plan" in wanted:
        t0 = time.perf_counter()
        plan = await stage_plan(
            cfg, vn, instruction=instruction, chapter_id=chapter_id
        )
        result["plan"] = plan
        result["stages"].append("plan")
        beat_sheet = plan.get("beatSheet")
        _push_trace(
            "plan",
            t0,
            ok=bool(beat_sheet),
            extra={"hasBeatSheet": bool(beat_sheet)},
        )

    if "write" in wanted:
        t0 = time.perf_counter()
        written = await stage_write(
            cfg,
            vn,
            instruction=instruction,
            chapter_id=chapter_id,
            selection=selection,
            beat_sheet=beat_sheet,
            db_continuity=continuity,
            on_token=on_token,
        )
        result["stages"].append("write")
        current = written.get("content") or current
        result["draft"] = current
        _push_trace(
            "write",
            t0,
            ok=bool(current.strip()),
            extra={"chars": len(current)},
        )

    if not current.strip() and want_check:
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
            "notes": [],
            "gateReady": False,
        }
        result["stages"].append("check")
        result["finalDraft"] = current
        result["gate"] = quality_gate_from_check(result["check"])
        _push_trace("check", time.perf_counter(), ok=False, extra={"errorCount": 1})
        return result

    async def _do_check(*, final: bool = False) -> Dict[str, Any]:
        return await stage_check_async(
            current,
            beat_sheet=beat_sheet,
            cfg=cfg,
            semantic_beats=semantic_beats,
            project=vn,
            chapter_id=chapter_id,
            voice_check=voice_check and final,
            voice_hard=voice_hard,
        )

    if want_check:
        t0 = time.perf_counter()
        chk = await _do_check(final=not want_revise)
        result["check"] = chk
        result["stages"].append("check")
        _push_trace(
            "check",
            t0,
            ok=bool(chk.get("pass")),
            extra={
                "errorCount": chk.get("errorCount"),
                "warnCount": chk.get("warnCount"),
                "beatMode": chk.get("beatMode"),
                "pass": 1,
            },
        )

    revise_done = 0
    if want_revise and result.get("check"):
        while revise_done < rounds_cap:
            chk_now = result["check"] or {}
            if chk_now.get("pass"):
                break

            t0 = time.perf_counter()
            rev = await stage_revise(cfg, vn, draft=current, check=chk_now)
            result["revise"] = rev
            result["stages"].append("revise")
            revise_done += 1
            if not rev.get("skipped"):
                current = rev.get("content") or current
                result["draft"] = current
            _push_trace(
                "revise",
                t0,
                ok=True,
                extra={
                    "skipped": bool(rev.get("skipped")),
                    "round": revise_done,
                },
            )
            if rev.get("skipped"):
                break

            if want_check:
                t0 = time.perf_counter()
                is_last = revise_done >= rounds_cap
                chk2 = await _do_check(final=is_last)
                result["check"] = chk2
                result["stages"].append("check")
                _push_trace(
                    "check",
                    t0,
                    ok=bool(chk2.get("pass")),
                    extra={
                        "errorCount": chk2.get("errorCount"),
                        "warnCount": chk2.get("warnCount"),
                        "beatMode": chk2.get("beatMode"),
                        "pass": revise_done + 1,
                        "voiceChecked": bool(chk2.get("voiceChecked")),
                    },
                )
                if chk2.get("pass"):
                    break

    result["reviseRounds"] = revise_done

    if (
        want_check
        and voice_check
        and result.get("check")
        and not (result["check"] or {}).get("voiceChecked")
    ):
        t0 = time.perf_counter()
        chk_v = await _do_check(final=True)
        result["check"] = chk_v
        result["stages"].append("check")
        _push_trace(
            "check",
            t0,
            ok=bool(chk_v.get("pass")),
            extra={
                "errorCount": chk_v.get("errorCount"),
                "warnCount": chk_v.get("warnCount"),
                "beatMode": chk_v.get("beatMode"),
                "voiceChecked": True,
                "pass": "voice",
            },
        )

    result["finalDraft"] = current
    result["gate"] = quality_gate_from_check(
        result.get("check")
        or await stage_check_async(
            current,
            beat_sheet=beat_sheet,
            cfg=cfg,
            semantic_beats=semantic_beats,
            project=vn,
            chapter_id=chapter_id,
            voice_check=voice_check,
            voice_hard=voice_hard,
        )
    )

    if (
        apply_to_chapter
        and chapter_id
        and (result["finalDraft"] or "").strip()
        and result["gate"].get("pass")
    ):
        t0 = time.perf_counter()
        try:
            vn = apply_draft_to_chapter(
                vn, chapter_id, result["finalDraft"], mode=apply_mode
            )
            result["applied"] = True
            result["project"] = vn
            ch = next(c for c in vn.chapters if c.id == chapter_id)
            types = [b.get("type") for b in (ch.blocks or [])]
            _push_trace(
                "apply",
                t0,
                ok=True,
                extra={
                    "blockCount": len(ch.blocks or []),
                    "blockTypes": sorted({t for t in types if t}),
                },
            )
        except ValueError as exc:
            result["applyError"] = str(exc)
            _push_trace("apply", t0, ok=False, extra={"error": str(exc)})

    if persist_run:
        from app.core.pipeline.run_history import append_harness_run

        base = result.get("project") or vn
        stamped = append_harness_run(
            base,
            kind="pipeline",
            chapter_id=chapter_id,
            gate=result.get("gate"),
            check=result.get("check"),
            stages=result.get("stages"),
            trace=trace,
            revise_rounds=revise_done,
            applied=bool(result.get("applied")),
            instruction=instruction,
        )
        result["project"] = stamped
        result["runId"] = (stamped.harnessRuns or [{}])[0].get("id")

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
