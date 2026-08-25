"""Multi-step editor agent loop with project-scoped tools + trajectory."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from app.core.agent import (
    AGENT_SYSTEM,
    ApplyAgentResult,
    _normalize_agent_actions,
    _parse_agent_json,
    apply_agent_actions,
)
from app.core.agent_context import (
    build_agent_context,
    infer_agent_task,
    is_agent_task,
    task_hint,
)
from app.core.agent_tools import (
    format_tool_result_message,
    run_agent_tool,
    tool_catalog_for_prompt,
)
from app.core.ai import DeepSeekConfig
from app.core.harness.audit_full import full_audit_draft
from app.core.lenses import (
    build_lens_prompt_for_project,
    infer_lens_intent,
    resolve_project_lenses,
)
from app.core.llm_http import content_from_response
from app.core.llm_provider import LlmProvider, provider_from_config
from app.core.longform_memory import summarize_chat_memory
from app.core.mentors import build_mentor_prompt_for_project, resolve_project_mentors
from app.core.narrative_lint import NarrativeLintIssue, lint_has_blockers
from app.core.narrative_review import (
    apply_reviewed_script,
    chapter_tail_plain,
    extract_script_from_actions,
    run_narrative_self_review,
    should_self_review,
)
from app.core.writing_craft import build_writing_craft_prompt, select_craft_mode
from app.domain.types import (
    AgentAction,
    AgentContextMeta,
    AgentRequest,
    AgentResponse,
    VnProject,
)
from app.llm_models import DEFAULT_LLM_MODEL

DEFAULT_MAX_STEPS = 6

_LOOP_PROTOCOL = """
多步工具协议（在单轮 JSON 之上扩展）：
你可先调用工具收集证据，再给结论或 actions。输出仍是单一 JSON 对象：
{
  "message": "给用户看的阶段说明或最终回复",
  "tool_calls": [{"id":"t1","name":"工具名","arguments":{...}}],
  "actions": [],
  "done": false
}
规则：
- 需要查章/设定/角色/地点/体检/账本时，先 tool_calls（可 1～3 个），done=false；不要瞎编工程内容。
- 工具结果会在下一轮以 user 消息注入；看完再决定继续查或收工。
- 收工：done=true，或 tool_calls 为空；把完整意见写进 message；需要改工程时填 actions。
- 写正文后应用 lint_draft 自检更佳；与【忌讳】/设定冲突时先改再交。
- 禁止声称使用 shell、读写磁盘或访问外网。
"""

_FENCE_RE = re.compile(r"```(?:json)?\s*([\s\S]*?)```")


def _clip(text: str, n: int) -> str:
    t = (text or "").strip()
    if len(t) <= n:
        return t
    return t[:n].rstrip() + "…"


def _is_echo_of_tool_result(final_message: str, tool_text: str) -> bool:
    """检测模型把工具结果（如章节正文）原样复述当回复的失败模式。

    归一化空白后：回复≥300字、开头300字出现在工具文本里、且回复长度
    ≥工具文本60% → 判定为复读（正常引用一小段不会触发）。
    """
    if not final_message or not tool_text:
        return False
    fm = " ".join(final_message.split())
    tt = " ".join(tool_text.split())
    if len(fm) < 300 or len(fm) > len(tt) + 80:
        return False
    return fm[:300] in tt and len(fm) >= 0.6 * len(tt)


def _parse_loop_json(raw: str) -> Dict[str, Any]:
    text = (raw or "").strip()
    fence = _FENCE_RE.search(text)
    if fence:
        text = fence.group(1).strip()
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        text = text[start : end + 1]
    try:
        parsed = json.loads(text)
    except json.JSONDecodeError:
        msg, actions = _parse_agent_json(raw)
        return {"message": msg, "actions": actions, "tool_calls": [], "done": True}
    if not isinstance(parsed, dict):
        return {"message": str(parsed), "actions": [], "tool_calls": [], "done": True}
    return parsed


def _normalize_tool_calls(raw: Any) -> List[Dict[str, Any]]:
    if not isinstance(raw, list):
        return []
    out: List[Dict[str, Any]] = []
    for i, row in enumerate(raw[:5]):
        if not isinstance(row, dict):
            continue
        name = str(row.get("name") or row.get("tool") or "").strip()
        if not name:
            continue
        tid = str(row.get("id") or f"t{i+1}").strip() or f"t{i+1}"
        args = row.get("arguments") or row.get("args") or row.get("parameters") or {}
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except json.JSONDecodeError:
                args = {"raw": args}
        if not isinstance(args, dict):
            args = {}
        out.append({"id": tid, "name": name, "arguments": args})
    return out


async def _chat_json(
    provider: LlmProvider,
    *,
    temperature: float,
    messages: List[Dict[str, str]],
) -> str:
    res = await provider.chat_completions(
        messages=messages,
        temperature=temperature,
        response_format={"type": "json_object"},
        timeout=180,
    )
    content, _ = content_from_response(res)
    return (content or "{}").strip() or "{}"


async def _agent_steps(
    provider: LlmProvider,
    *,
    request: AgentRequest,
    messages: List[Dict[str, str]],
    working: VnProject,
    accumulated: List[AgentAction],
    trace: List[Dict[str, Any]],
    final_message: str,
    last_tool_text: str,
    start_step: int,
    steps: int,
    temperature: float,
    emit,
    on_checkpoint=None,
):
    """多步工具循环主体（可从 start_step 续跑）。

    每步结束后若提供 on_checkpoint，则回调可序列化的执行快照——
    断点续跑（run_state 持久化）的数据来源。
    """
    for step in range(start_step, steps):
        content = await _chat_json(
            provider,
            temperature=temperature,
            messages=messages,
        )
        parsed = _parse_loop_json(content)
        message = parsed.get("message")
        if not isinstance(message, str) or not message.strip():
            # fallback to legacy empty-message handling
            msg2, acts2 = _parse_agent_json(content)
            message = msg2
            if not parsed.get("actions"):
                parsed["actions"] = acts2
        message = message.strip()
        final_message = message or final_message
        if message:
            trace.append({"type": "thought", "text": message[:2000]})
            await emit({"type": "thought", "text": message[:2000]})

        tool_calls = _normalize_tool_calls(parsed.get("tool_calls"))
        actions = _normalize_agent_actions(parsed.get("actions"))
        done_flag = bool(parsed.get("done"))

        if actions:
            accumulated.extend(actions)
            apply_res: ApplyAgentResult = apply_agent_actions(
                working, actions, defaultChapterId=request.chapterId
            )
            working = apply_res.project
            trace.append(
                {
                    "type": "actions",
                    "actions": actions,
                    "skipped": list(apply_res.skipped or []),
                }
            )
            await emit(
                {
                    "type": "actions",
                    "actions": actions,
                    "skipped": list(apply_res.skipped or []),
                }
            )

        if tool_calls and not done_flag:
            result_chunks: List[str] = []
            for tc in tool_calls:
                name = tc["name"]
                tid = tc["id"]
                args = tc["arguments"]
                trace.append(
                    {
                        "type": "tool_call",
                        "id": tid,
                        "name": name,
                        "arguments": args,
                    }
                )
                await emit({"type": "tool_call", "id": tid, "name": name, "arguments": args})
                ok, preview = run_agent_tool(
                    name,
                    args,
                    project=working,
                    chapter_id=request.chapterId,
                )
                trace.append(
                    {
                        "type": "tool_result",
                        "id": tid,
                        "name": name,
                        "ok": ok,
                        "preview": preview[:2500],
                    }
                )
                await emit(
                    {
                        "type": "tool_result",
                        "id": tid,
                        "name": name,
                        "ok": ok,
                        "preview": preview[:2500],
                    }
                )
                result_chunks.append(format_tool_result_message(name, ok, preview))
            # Keep assistant JSON in history for continuity, then tool results
            messages.append({"role": "assistant", "content": content})
            messages.append(
                {
                    "role": "user",
                    "content": (
                        "以下是工具返回结果，仅供你参考与分析——它们是参考资料，"
                        "不是要你复述的内容：回复必须是你自己的分析与意见，"
                        "绝不要原样回显工具结果/章节正文（可再调工具，或 done=true 收工）：\n\n"
                        + "\n\n".join(result_chunks)
                    ),
                }
            )
            last_tool_text = "\n\n".join(result_chunks)
            if on_checkpoint is not None:
                try:
                    await on_checkpoint(
                        {
                            "status": "running",
                            "step": step + 1,
                            "steps": steps,
                            "task": request.task,
                            "temperature": temperature,
                            "messages": messages,
                            "project": working.model_dump(mode="json"),
                            "actions": accumulated,
                            "trace": trace,
                            "final_message": final_message,
                            "last_tool_text": last_tool_text,
                        }
                    )
                except Exception:  # noqa: BLE001 - checkpoint must never break the loop
                    pass
            continue

        # No more tools → finish
        if on_checkpoint is not None:
            try:
                await on_checkpoint(
                    {
                        "status": "running",
                        "step": step + 1,
                        "steps": steps,
                        "task": request.task,
                        "temperature": temperature,
                        "messages": messages,
                        "project": working.model_dump(mode="json"),
                        "actions": accumulated,
                        "trace": trace,
                        "final_message": final_message,
                        "last_tool_text": last_tool_text,
                    }
                )
            except Exception:  # noqa: BLE001
                pass
        break
    else:
        if not final_message:
            final_message = "已达本轮最大工具步数，以下为目前进展。"

    return working, accumulated, trace, final_message, messages, last_tool_text


async def run_agent_loop(
    config: DeepSeekConfig,
    request: AgentRequest,
    *,
    max_steps: int = DEFAULT_MAX_STEPS,
    on_event=None,
    on_checkpoint=None,
    resume: Optional[Dict[str, Any]] = None,
) -> AgentResponse:
    if not config.apiKey or "your-key" in config.apiKey:
        raise RuntimeError("请先配置 DEEPSEEK_API_KEY")
    model = config.model or DEFAULT_LLM_MODEL
    provider = provider_from_config(config)

    async def emit(evt: Dict[str, Any]) -> None:
        """Fire a stream event; a failing sink must never break the loop."""
        if on_event is None:
            return
        try:
            await on_event(evt)
        except Exception:  # noqa: BLE001 - sink failure is not agent failure
            pass

    if resume:
        # 断点续跑：直接加载上次持久化的执行快照，不再重建上下文
        # （messages 已含系统提示/历史/工具结果；working 已含中途应用的 actions）。
        working = VnProject.model_validate(resume.get("project") or {})
        accumulated: List[AgentAction] = list(resume.get("actions") or [])
        trace: List[Dict[str, Any]] = list(resume.get("trace") or [])
        final_message = str(resume.get("final_message") or "")
        messages: List[Dict[str, str]] = list(resume.get("messages") or [])
        last_tool_text = str(resume.get("last_tool_text") or "")
        steps = int(resume.get("steps") or DEFAULT_MAX_STEPS)
        start_step = int(resume.get("step") or 0)
        task = str(resume.get("task") or "chat")
        temperature = float(resume.get("temperature") or 0.7)
        craft_mode = str(resume.get("craftMode") or "off")
        await emit(
            {
                "type": "thought",
                "text": f"已从断点继续（此前完成 {start_step}/{steps} 步），现在接着处理。",
            }
        )
        await emit({"type": "task", "task": task, "craftMode": craft_mode})
        last_user = next(
            (m.get("content") for m in reversed(messages) if m.get("role") == "user"),
            None,
        )
        # ctx 只做本地拼装（无 LLM 调用），供末尾 contextMeta 统计
        ctx = build_agent_context(
            working,
            chapterId=request.chapterId,
            selection=request.selection,
            userMessage=last_user,
            task=task,
            maxChars=12000,
            chatMemory=request.chatMemory,
            longChapterMemory=request.longChapterMemory,
            loreCraft=request.loreCraft,
            referenceDocs=request.referenceDocs,
        )
    else:
        last_user = next(
            (m.content for m in reversed(request.messages) if m.role == "user"), None
        )
        task = request.task if is_agent_task(request.task) else infer_agent_task(last_user or "")
        craft = select_craft_mode(
            task=task,
            user_message=last_user,
            project=request.project,
            chapter_id=request.chapterId,
            preference=request.craftMode,
        )
        await emit({"type": "task", "task": task, "craftMode": craft.mode})
        ctx = build_agent_context(
            request.project,
            chapterId=request.chapterId,
            selection=request.selection,
            userMessage=last_user,
            task=task,
            maxChars=12000,
            chatMemory=request.chatMemory,
            longChapterMemory=request.longChapterMemory,
            loreCraft=request.loreCraft,
            referenceDocs=request.referenceDocs,
        )

        if craft.mode == "off":
            temperature = 0.82
        elif task in ("polish", "voice", "consistency"):
            temperature = 0.55
        elif task == "outline":
            temperature = 0.7
        elif craft.mode == "lite":
            temperature = 0.72
        else:
            temperature = 0.78

        craft_block = build_writing_craft_prompt(task, craft.mode)
        mentor_block = build_mentor_prompt_for_project(
            request.project, task=task, override_ids=request.mentorIds
        )
        mentor_ids = [
            p.id for p in resolve_project_mentors(request.project, override_ids=request.mentorIds)
        ]
        lens_intent = infer_lens_intent(last_user or "")
        lens_block = build_lens_prompt_for_project(
            request.project, override_ids=request.lensIds, intent=lens_intent
        )
        lens_ids = [
            p.id for p in resolve_project_lenses(request.project, override_ids=request.lensIds)
        ]

        # 对话记忆：超过阈值时，早期轮次用 LLM 结构化摘要（防长对话失忆），
        # 最近轮次保留原文。摘要失败自动回退抽取式，不阻塞。
        _KEEP_RECENT = 16
        _SUMMARIZE_AFTER = 22
        all_msgs = [m for m in (request.messages or []) if m.role in ("user", "assistant")]
        recent_msgs = all_msgs[-_KEEP_RECENT:] if len(all_msgs) > _KEEP_RECENT else all_msgs
        chat_memory_block = ""
        if len(all_msgs) > _SUMMARIZE_AFTER:
            older = all_msgs[: len(all_msgs) - _KEEP_RECENT]
            try:
                chat_memory_block = await summarize_chat_memory(
                    provider, older, request.chatMemory
                )
                if chat_memory_block:
                    await emit({"type": "memory", "note": "已归档早期对话记忆"})
            except Exception:  # noqa: BLE001 - memory summary must never break the loop
                chat_memory_block = ""

        system_parts = [
            AGENT_SYSTEM,
            task_hint(task),
            craft_block,
            mentor_block,
            lens_block,
            _LOOP_PROTOCOL,
            tool_catalog_for_prompt(),
        ]
        if request.referenceDocs and request.referenceDocs.strip():
            system_parts.append(
                "本轮含用户上传参考资料。若用户要求写入/更新设定页：请用 update_bible "
                "以及必要时 update_meta、add_character/update_character；不要只口头复述。"
            )
        system_content = "\n\n".join(p for p in system_parts if p and str(p).strip())
        system_content = (
            f"{system_content}\n\n"
            f"—— 作品上下文（检索拼装；人设/设定为内部参考）——\n{ctx.text}"
        )
        if chat_memory_block:
            system_content += (
                f"\n\n## 对话记忆归档（更早轮次，非正式剧情）\n{_clip(chat_memory_block, 2800)}"
            )

        history: List[Dict[str, str]] = [
            {"role": m.role, "content": m.content} for m in recent_msgs
        ]
        messages: List[Dict[str, str]] = [
            {"role": "system", "content": system_content},
            *history,
        ]

        working: VnProject = request.project
        accumulated: List[AgentAction] = []
        trace: List[Dict[str, Any]] = []
        final_message = ""
        last_tool_text = ""
        # 复杂检索类任务给更多步：一致性排查 / 大纲 / 改写需要多次查章-设定-角色。
        # 用户显式传入 max_steps 时优先；否则按任务加权。
        if max_steps is not None and max_steps != DEFAULT_MAX_STEPS:
            steps = max(1, min(12, int(max_steps)))
        else:
            task_steps = {"consistency": 9, "outline": 8, "rewrite": 8, "voice": 8, "scene": 7}
            steps = max(1, min(12, task_steps.get(task, DEFAULT_MAX_STEPS)))
        start_step = 0
        mentor_ids: List[str] = []
        lens_ids: List[str] = []

    working, accumulated, trace, final_message, messages, last_tool_text = (
        await _agent_steps(
            provider,
            request=request,
            messages=messages,
            working=working,
            accumulated=accumulated,
            trace=trace,
            final_message=final_message,
            last_tool_text=last_tool_text,
            start_step=start_step,
            steps=steps,
            temperature=temperature,
            emit=emit,
            on_checkpoint=on_checkpoint,
        )
    )

    review_note = ""
    review_pref = request.selfReview or "auto"
    actions_out = list(accumulated)
    if should_self_review(task, review_pref) and actions_out:
        script_hit = extract_script_from_actions(actions_out)
        if script_hit.op and script_hit.text:
            lint_audit = full_audit_draft(script_hit.text)
            lint_issues = [
                NarrativeLintIssue(
                    severity=str(i.get("severity") or "warn"),
                    code=str(i.get("code") or "harness"),
                    message=str(i.get("message") or ""),
                )
                for i in (lint_audit.get("issues") or [])
                if isinstance(i, dict) and i.get("message")
            ]
            critic_config = DeepSeekConfig(
                apiKey=request.criticApiKey or config.apiKey,
                baseUrl=request.criticApiBaseUrl or config.baseUrl,
                model=request.criticApiModel or config.model,
            )
            review = await run_narrative_self_review(
                critic_config,
                draft=script_hit.text,
                task=task,
                project=working,
                chapterTail=chapter_tail_plain(working, request.chapterId),
                lintIssues=lint_issues,
            )
            review_note = review.note or ""
            if not review.ok and review.revisedText:
                actions_out = apply_reviewed_script(
                    actions_out, script_hit.index, review.revisedText
                )
                if review.issues:
                    final_message = (
                        f"{final_message}\n\n（自检修订：{'；'.join(review.issues[:3])}）"
                    )
                trace.append({"type": "thought", "text": f"自检：{review_note or '已改写'}"})
                await emit({"type": "review", "note": review_note or "已改写"})
            elif lint_has_blockers(lint_issues) and not review.revisedText:
                error_msgs = [i.message for i in lint_issues if i.severity == "error"][:2]
                review_note = review_note or f"规则未过：{'；'.join(error_msgs)}"

    if not final_message:
        if actions_out:
            final_message = "已生成工程改动，请查看 actions。"
        else:
            final_message = "本轮没有产出可用说明，请换个问法再试。"
    elif _is_echo_of_tool_result(final_message, last_tool_text):
        # 模型复读了工具读到的章节/资料原文（如 Agnes 类忽略 JSON 协议、
        # 对工具结果理解弱的模型）：明示用户，避免把"复读"当成正常回复。
        final_message = (
            "模型复述了工具读取的章节/资料原文，没有给出实际分析。"
            "请重试；若多次出现，建议更换模型（当前模型可能不支持本 Agent 的"
            "JSON 输出协议，或对工具结果理解较弱）。"
        )
        trace.append(
            {"type": "thought", "text": "检测到模型复读工具结果，已替换为提示语"}
        )
        await emit(
            {"type": "thought", "text": "检测到模型复读工具结果，已替换为提示语"}
        )

    trace.append({"type": "done", "message": final_message[:2000]})

    response = AgentResponse(
        message=final_message,
        actions=actions_out,
        model=model,
        contextMeta=AgentContextMeta(
            task=task,
            charsUsed=ctx.charsUsed,
            included=ctx.included,
            craftMode=craft.mode,
            craftReason=craft.reason,
            mentorIds=mentor_ids or None,
            lensIds=lens_ids or None,
            selfReview=review_note or None,
            chatMemorySummary=chat_memory_block or None,
        ),
        trace=trace,
    )
    await emit({"type": "done", "result": response.model_dump(mode="json", by_alias=True)})
    return response
