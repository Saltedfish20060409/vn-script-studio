"""动笔前先问几句（可选步骤）。

为什么要它：对照 WenShape（文枢）时发现，它在写整章前会先问「关键推进点是什么」
「主角这场的动机/状态有变化吗」，答案是写进场景简报留档的。我们原来是拿到一句话
就直接写——快，但写偏了只能重来。

这里的定位是**可选**：作者可以一键跳过。默认给出 2–3 个问题，覆盖
① 本场的关键推进点 ② 每个主要角色的动机/状态变化 ③ 收尾落点。
模型不可用时**不报错**，回退到模板问题——这个功能永远不该成为写作的拦路虎。
"""

from __future__ import annotations

import json
import re
from typing import Any, Dict, List, Optional

from app.core import llm_budget

MAX_QUESTIONS = 3

_SYSTEM = """你是这部作品的驻场责编。作者马上要写一场戏/一章，你要在动笔**之前**
问清最关键的信息，避免他写完才发现方向不对。

要求：
- 只问 2~3 个问题，每个问题一句话，直接可回答，不要客套、不要解释你为什么问。
- 优先问：这一场的关键推进点（谁改变了什么）；每个主要角色在这场里的动机或状态有没有变化；
  结尾要停在哪句台词或哪个画面。
- 结合上面给你的作品设定与角色语气来问，问得具体（例如点出角色名），不要问空泛的"你想写什么"。
- 不要求作者回答你不需要的信息（不要问字数、不要问平台）。

输出唯一 JSON：{"questions": ["问题一", "问题二", "问题三"]}"""


def _fallback_questions(character_names: List[str], goal: str) -> List[str]:
    """模型不可用时的模板问题。不是凑数：这三条正是写作前最该定的东西。"""
    names = [n for n in character_names if n][:2]
    out = ["这一场的关键推进点是什么？（谁改变了什么，一句话）"]
    if names:
        out.append(f"{'、'.join(names)} 在这场里的动机或状态有变化吗？")
    else:
        out.append("主角在这场里的动机或状态有变化吗？")
    goal_bit = (goal or "").strip()
    out.append(
        "结尾停在哪句台词或哪个画面上？"
        if not goal_bit
        else "结尾停在哪句台词或哪个画面上？（上面那句目标里已经点明的部分可以不重复）"
    )
    return out[:MAX_QUESTIONS]


def _clean(questions: Any) -> List[str]:
    if not isinstance(questions, list):
        return []
    out: List[str] = []
    for q in questions:
        if isinstance(q, dict):
            q = q.get("text") or q.get("question") or ""
        text = re.sub(r"\s+", " ", str(q or "")).strip()
        text = text.lstrip("-•0123456789. 、").strip()
        if len(text) < 4 or text in out:
            continue
        out.append(text[:120])
        if len(out) >= MAX_QUESTIONS:
            break
    return out


async def generate_pre_questions(
    config: Any,
    project: Any,
    *,
    goal: str,
    chapter_id: Optional[str] = None,
    user_message: Optional[str] = None,
) -> Dict[str, Any]:
    """返回 {"questions": [...], "source": "llm"|"template"}。永不抛错。"""
    names = [getattr(c, "displayName", "") for c in (getattr(project, "characters", None) or [])]
    names = [n for n in names if n][:6]

    if not config.apiKey or "your-key" in str(config.apiKey):
        return {"questions": _fallback_questions(names, goal), "source": "template"}

    try:
        from app.core.agent_context import build_agent_context
        from app.core.llm_http import chat_completions, content_from_response

        ctx = build_agent_context(
            project,
            chapterId=chapter_id,
            userMessage=user_message or goal,
            task="scene",
        )
        ask = "\n\n".join(
            p
            for p in [
                ctx.text,
                f"【这次的写作目标】{goal}" if goal else "",
                "请按系统提示输出 JSON。",
            ]
            if p
        )
        res = await chat_completions(
            config,
            messages=[
                {"role": "system", "content": _SYSTEM},
                {"role": "user", "content": ask},
            ],
            temperature=0.4,
            response_format={"type": "json_object"},
            timeout=llm_budget.QUICK,
        )
        content, _used = content_from_response(res)
        parsed = json.loads((content or "").strip() or "{}")
        questions = _clean(parsed.get("questions"))
        if questions:
            return {"questions": questions, "source": "llm"}
    except Exception:  # noqa: BLE001 — 问问题这件事失败绝不该拦住写作
        pass
    return {"questions": _fallback_questions(names, goal), "source": "template"}
