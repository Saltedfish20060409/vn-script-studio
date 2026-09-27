"""Multi-step editor agent loop with project-scoped tools + trajectory."""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from app.core import llm_budget
from app.core.agent import (
    AGENT_SYSTEM,
    ApplyAgentResult,
    _normalize_agent_actions,
    _parse_agent_json,
    agent_identity_block,
    apply_agent_actions,
)
from app.core.agent_context import (
    build_agent_context,
    context_budget_for_model,
    infer_agent_task,
    is_agent_task,
    task_hint,
)
from app.core.agent_retrieve import PrefetchReport, run_write_prefetch, should_prefetch
from app.core.agent_tools import (
    ASYNC_TOOL_NAMES,
    format_tool_result_message,
    run_agent_tool,
    run_agent_tool_async,
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
from app.core.llm_params import task_temperature
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
from app.core.write_gate import WriteGateResult, gate_continue_draft, should_write_gate
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
- 上下文末尾若有「篇幅说明 / 长上下文提醒」，表示某些资料这次**没带来**（不是作者没写）：
  需要时用工具取回（get_chapter / search_script / search_lore），取不到就说明不确定，
  不要凭印象补写设定或前情。
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


def _step_message(parsed: Dict[str, Any]) -> str:
    """这一步模型写给用户的文字说明；**没有就是空串**。

    刻意**不**调 `_parse_agent_json` 的空消息兜底来"补一句"：那句
    「我这一轮没产出可用的文字说明。请换个问法再试…」是给单轮老路径用的**失败提示**，
    在这里当 message 用会撞上两件事（用户反馈刚好两件都撞了）：
    1. **工具步本来就不写 message**（协议只要求 `done=false`，见 `_LOOP_PROTOCOL`），
       于是每个工具步都被"补"上这句道歉，混进思考流，作者看到一句莫名其妙的话；
    2. 最后一步若同样没有 message，它会**直接变成给作者的最终答复**——而这一轮明明
       已经取回了工具证据、本该给出审查意见。

    真正的收尾由 `_agent_steps` 末尾的 `_force_final_message` 负责：那才是"再问一次"，
    而不是"编一句"。
    """
    msg = parsed.get("message")
    if isinstance(msg, str) and msg.strip():
        return msg.strip()
    return ""


#: 收尾补写时追加的那条指令。它只做一件事：要文字，不要工具。
#: 单列成常量是为了能被测试直接断言（这段文案是"用户反馈的修复"的一部分）。
_FORCE_FINAL_NUDGE = (
    "你上一轮没有在 message 里写给作者任何文字。现在**不要再调用任何工具**，"
    "直接基于以上已有信息给出你的分析与结论：说清你依据了什么，并给出可执行的下一步。"
    '只输出 JSON：{"message":"…","tool_calls":[],"actions":[],"done":true}'
)


async def _force_final_message(
    provider: LlmProvider,
    *,
    messages: List[Dict[str, str]],
    temperature: float,
    trace: List[Dict[str, Any]],
) -> str:
    """再要一次最终答复；只在模型一个字的分析都没给时调用。

    为什么需要它：工具步不写 message 是**正常**的（协议只要求 `done=false`），但最后
    一步不写就是失败——过去那种情况作者只会收到一句"请换个问法"，而这一轮明明已经取回
    了工具证据。所以这里不是"编一句"（那正是被修掉的 bug），而是"再问一次"。

    刻意自己解析、**不**经过 `_parse_agent_json`：那条路径的空消息兜底会返回一句
    "给用户看的失败提示"，拿它当答复就等于把这次补写也白白浪费掉。
    解析失败或模型又没给 message 时返回空串——调用方会回落到一句准确的话。
    """
    nudge = list(messages) + [{"role": "user", "content": _FORCE_FINAL_NUDGE}]
    try:
        content = await _chat_json(provider, temperature=temperature, messages=nudge)
    except Exception:  # noqa: BLE001 — 收尾失败不该把整轮变成异常
        return ""

    text = (content or "").strip()
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
        # 补写这轮模型直接说了人话（没给 JSON）：那就是它的答复，照收——
        # 与正常路径"纯文本当回复"同一口径，绝不把 JSONDecodeError 抛给作者。
        from app.core.llm_text import normalize_model_text

        return normalize_model_text(text).strip()
    if not isinstance(parsed, dict):
        return ""
    msg = _step_message(parsed)
    if msg:
        trace.append({"type": "thought", "text": f"收尾补写：{msg[:200]}"})
    return msg


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
        timeout=llm_budget.WRITE,
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
    hit_step_cap = False
    for step in range(start_step, steps):
        content = await _chat_json(
            provider,
            temperature=temperature,
            messages=messages,
        )
        parsed = _parse_loop_json(content)
        # 这一步的文字说明：没有就是空（工具步正常就不写 message）。
        # 绝不能拿 `_parse_agent_json` 的空消息兜底来填——见 `_step_message` 的说明。
        message = _step_message(parsed)
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

        if tool_calls:
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
                if name in ASYNC_TOOL_NAMES:
                    # 会调模型的工具（如 polish_prose）：走 async 通道。
                    # config 从 provider 上取（两种 provider 都把 DeepSeekConfig 存在 .config）。
                    ok, preview = await run_agent_tool_async(
                        name,
                        args,
                        project=working,
                        chapter_id=request.chapterId,
                        config=getattr(provider, "config", None),
                    )
                else:
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
            if done_flag:
                # 模型自相矛盾：done=true 又给了 tool_calls。**不能静默丢掉工具调用**——
                # 作者会只收到一句"没产出可用说明"，而要读的那章根本没读（用户反馈里
                # 的症状之一）。证据已经取回并写进 messages 了，按 done 收工；这一步没有
                # message 时由循环末尾的 `_force_final_message` 补写。
                break
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
        hit_step_cap = True

    # 收尾补写：模型跑了工具（或干脆什么都不说）却没给作者一个字的分析。
    # 工具步不写 message 是正常的，**最后一步**不写就是失败——用户反馈在这里只收到一句
    # "请换个问法"。有证据时再明确要一次收尾，一次调用的代价换掉一句道歉。
    if not final_message:
        final_message = await _force_final_message(
            provider,
            messages=messages,
            temperature=temperature,
            trace=trace,
        )
    if not final_message:
        # 补写也没拿到：给一句**准确**的话，而不是把失败说成"换个问法就好"。
        final_message = (
            "已达本轮最大工具步数，以下为目前进展。"
            if hit_step_cap
            else "本轮没有产出可用说明，请换个问法再试。"
        )

    return working, accumulated, trace, final_message, messages, last_tool_text


def record_context_stats(ctx) -> None:  # noqa: ANN001
    """把这次拼装的上下文体积与"是否被裁"记进统计（`/admin/llm-latency` 的 context 系列）。

    它是"要不要为更大上下文放开预算（甚至换架构）"的判据：拼装量长期远低于天花板，
    调大预算就是白花钱；反过来如果 `truncationRate` 高、`promptChars` 贴着顶，
    那就说明真的被卡住了。统计失败绝不影响主链路（`latency_stats` 内部吞异常）。
    """
    try:
        from app.core import latency_stats

        latency_stats.record_context(
            int(getattr(ctx, "charsUsed", 0) or 0),
            task=str(getattr(ctx, "task", "") or ""),
            truncated=bool(getattr(ctx, "truncated", False)),
            dropped_sections=len(getattr(ctx, "excluded", None) or []),
        )
    except Exception:  # noqa: BLE001 - 统计不该打断写作
        return


def compose_agent_system(
    *,
    identity_block: str,
    task: str,
    craft_block: str = "",
    mentor_block: str = "",
    lens_block: str = "",
    has_reference_docs: bool = False,
    context_text: str = "",
    chat_memory_block: str = "",
) -> str:
    """拼装 Agent 的 system 提示（顺序即优先级）。

    单独抽出来是因为"谁的身份在最前面"曾经出过线上问题：界面选中了作家透镜，
    而 system 里只有固定身份、没有说明本轮借了谁的视角，于是问「你是谁」时
    模型答的和界面显示的完全对不上。这里保证 `AGENT_SYSTEM` 之后**紧跟**
    `identity_block`，并且测试/探针可以复用同一个函数来验证真实顺序。
    """
    parts = [
        AGENT_SYSTEM,
        identity_block,
        task_hint(task),
        craft_block,
        mentor_block,
        lens_block,
        _LOOP_PROTOCOL,
        tool_catalog_for_prompt(),
    ]
    if has_reference_docs:
        parts.append(
            "本轮含用户上传参考资料。若用户要求写入/更新设定页：请用 update_bible "
            "以及必要时 update_meta、add_character/update_character；不要只口头复述。"
        )
    text = "\n\n".join(p for p in parts if p and str(p).strip())
    text = f"{text}\n\n—— 作品上下文（检索拼装；人设/设定为内部参考）——\n{context_text}"
    if chat_memory_block:
        text += (
            f"\n\n## 对话记忆归档（更早轮次，非正式剧情）\n{_clip(chat_memory_block, 2800)}"
        )
    return text


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
    # 本次上下文预算（字符）：按模型窗口与执行档夹过，后面两个分支共用，
    # 也会随 contextMeta 返回给界面（"这次它读了多少、够不够"）。
    ctx_budget = context_budget_for_model(model)

    mentor_ids: List[str] = []
    lens_ids: List[str] = []
    chat_memory_block = ""
    craft = select_craft_mode(
        task="chat",
        user_message="",
        project=request.project,
        chapter_id=request.chapterId,
        preference=request.craftMode,
    )

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
        # 预算按**当前生效的模型**与**执行档**再夹一次：预设里有 32k 窗口的本地模型，
        # 硬塞 48k 字符会被上游直接拒答；流式路径（SSE + 心跳）可以用更高的天花板。
        ctx = build_agent_context(
            working,
            chapterId=request.chapterId,
            selection=request.selection,
            userMessage=last_user,
            task=task,
            maxChars=ctx_budget,
            chatMemory=request.chatMemory,
            longChapterMemory=request.longChapterMemory,
            globalMemory=request.globalMemory,
            loreCraft=request.loreCraft,
            referenceDocs=request.referenceDocs,
            exclude=request.excludeSections,
        )
        record_context_stats(ctx)
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
            maxChars=ctx_budget,
            chatMemory=request.chatMemory,
            longChapterMemory=request.longChapterMemory,
            globalMemory=request.globalMemory,
            loreCraft=request.loreCraft,
            referenceDocs=request.referenceDocs,
            exclude=request.excludeSections,
        )
        record_context_stats(ctx)

        # 采样参数按任务分档（集中在一处，见 core/llm_params）：连续创作偏高、改稿/检查偏低
        temperature = task_temperature(task, craft.mode)

        craft_block = build_writing_craft_prompt(task, craft.mode)
        # 解析出来的**包对象**要留着：身份块要按真实生效的名字拼，不能只拿 id。
        mentor_packs = resolve_project_mentors(
            request.project, override_ids=request.mentorIds
        )
        mentor_block = build_mentor_prompt_for_project(
            request.project, task=task, override_ids=request.mentorIds
        )
        mentor_ids = [p.id for p in mentor_packs]
        lens_intent = infer_lens_intent(last_user or "")
        lens_packs = resolve_project_lenses(
            request.project, override_ids=request.lensIds
        )
        lens_block = build_lens_prompt_for_project(
            request.project, override_ids=request.lensIds, intent=lens_intent
        )
        lens_ids = [p.id for p in lens_packs]
        # 界面上选了哪几位透镜，模型就得知道是哪几位（否则问「你是谁」会答不上来）
        identity_block = agent_identity_block(mentor_packs, lens_packs)

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

        system_content = compose_agent_system(
            identity_block=identity_block,
            task=task,
            craft_block=craft_block,
            mentor_block=mentor_block,
            lens_block=lens_block,
            has_reference_docs=bool(
                request.referenceDocs and request.referenceDocs.strip()
            ),
            context_text=ctx.text,
            chat_memory_block=chat_memory_block,
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

    prefetch_report: Optional[PrefetchReport] = None
    if should_prefetch(task, ctx):
        prefetch_report = run_write_prefetch(
            working,
            ctx,
            task=task,
            chapter_id=request.chapterId,
            user_message=last_user or "",
        )
        for msg in prefetch_report.as_messages():
            messages.append(msg)
        if prefetch_report.calls:
            note = "；".join(c.reason for c in prefetch_report.calls[:2])
            trace.append({"type": "thought", "text": f"材料预取：{note}"})
            await emit(
                {
                    "type": "retrieve_prefetch",
                    "calls": [
                        {"name": c.name, "reason": c.reason} for c in prefetch_report.calls
                    ],
                }
            )

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
    write_gate: Optional[WriteGateResult] = None
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

    # 写后廉价闸：自检开/关都跑；失败只标警告，不挡落地（责编改写是可选下一层）。
    # 失败时给出标记批改 hint（只改失败段，不全章重写）。
    # 通过但仍有 warn（如声线 drift）同样给出 tip + markHints，避免「过」掩盖跑偏。
    if should_write_gate(task) and actions_out:
        gated = extract_script_from_actions(actions_out)
        if gated.op and gated.text:
            write_gate = gate_continue_draft(
                gated.text,
                project=working,
                chapter_id=request.chapterId,
            )
            has_soft = bool(write_gate.warnings or write_gate.markHints)
            if not write_gate.passed or has_soft:
                tip = "；".join(write_gate.warnings[:2]) or (
                    "确定性规则未过" if not write_gate.passed else "有提醒"
                )
                if not write_gate.passed:
                    review_note = review_note or f"写后闸：{tip}"
                    trace.append({"type": "thought", "text": f"写后闸未通过：{tip}"})
                elif has_soft:
                    trace.append({"type": "thought", "text": f"写后闸提醒：{tip}"})
                await emit(
                    {
                        "type": "write_gate",
                        "passed": write_gate.passed,
                        "warnings": write_gate.warnings,
                        "markHints": write_gate.markHints,
                    }
                )
                mark_tip = ""
                if write_gate.markHints:
                    q0 = str(write_gate.markHints[0].get("quote") or "")[:40]
                    mark_tip = (
                        f"；可用「标记批改」处理：「{q0}…」"
                        if q0
                        else "；可用「标记批改」只改提示段"
                    )
                if "写后闸" not in (final_message or ""):
                    final_message = (
                        f"{final_message}\n\n（写后闸提醒：{tip}{mark_tip}）"
                        if final_message
                        else f"写后闸提醒：{tip}{mark_tip}"
                    )

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
            # 界面上要能回答"这次它读了多少、够不够、有没有被截"——
            # 这是"失忆"最容易被作者发现的一处（AI 没读到整章时会写出前后矛盾的东西）
            budgetChars=ctx_budget,
            truncated=ctx.truncated,
            # 「没装下的是什么、怎么取回来」：界面上列清单用，不必解析中文标记
            budgetReport=ctx.budgetReport or None,
            included=ctx.included,
            # 「证明它记得」：实际依据的资料与摘录（前端默认摆出来，可展开看）
            includedDetails=ctx.includedDetails,
            excludedSections=ctx.excluded,
            # 用的是谁的钱：前端据此在免费档下提示"长任务建议填自己的 Key"
            credentialsMode=request.credentialsMode,
            craftMode=craft.mode,
            craftReason=craft.reason,
            mentorIds=mentor_ids or None,
            lensIds=lens_ids or None,
            selfReview=review_note or None,
            writeGate=write_gate.as_meta() if write_gate is not None else None,
            retrievePrefetch=prefetch_report.as_meta() if prefetch_report is not None else None,
            chatMemorySummary=chat_memory_block or None,
        ),
        trace=trace,
    )
    await emit({"type": "done", "result": response.model_dump(mode="json", by_alias=True)})
    return response
