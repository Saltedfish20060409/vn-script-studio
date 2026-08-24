"""Ported from packages/core/src/longformMemory.ts"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

from app.domain.types import AgentChatMessage

_LEADING_MARKER = re.compile(r"^[\s\-*\d.、)）]+")


def parse_outline_beats(outline: Optional[str]) -> List[str]:
    """Split Story Bible outline into beat lines"""
    if not outline or not outline.strip():
        return []
    lines = outline.replace("\r\n", "\n").split("\n")
    beats = [_LEADING_MARKER.sub("", l).strip() for l in lines]
    return [l for l in beats if len(l) >= 4]


def _score_beat(beat: str, tokens: List[str]) -> int:
    if not tokens:
        return 0
    h = beat.lower()
    s = 0
    for tok in tokens:
        if tok.lower() in h:
            s += 2 if len(tok) >= 2 else 1
    return s


def select_outline_beats(
    outline: Optional[str], tokens: List[str], max_: int = 5
) -> List[str]:
    """Pick outline beats relevant to the user ask / selection"""
    beats = parse_outline_beats(outline or "")
    if not beats:
        return []
    if not tokens:
        return beats[: min(3, max_)]
    scored = [(b, _score_beat(b, tokens)) for b in beats]
    scored = [(b, s) for b, s in scored if s > 0]
    scored.sort(key=lambda pair: pair[1], reverse=True)
    return [b for b, _ in scored[:max_]]


@dataclass
class ChatMemoryBundle:
    # Compressed older turns for system context
    memoryBlock: str
    # Recent turns to send as chat messages
    recentMessages: List[AgentChatMessage] = field(default_factory=list)
    summarizedCount: int = 0


_DEFAULT_KEEP = 16
_SUMMARIZE_AFTER = 22


def compress_chat_history(
    messages: List[AgentChatMessage],
    keep_recent: Optional[int] = None,
    summarize_after: Optional[int] = None,
    prior_memory: Optional[str] = None,
) -> ChatMemoryBundle:
    """Extractive rolling chat memory — no LLM.

    Older turns become short bullets; recent stay verbatim for the API.
    """
    keep = keep_recent if keep_recent is not None else _DEFAULT_KEEP
    threshold = summarize_after if summarize_after is not None else _SUMMARIZE_AFTER
    usable = [m for m in messages if m.role in ("user", "assistant")]

    if len(usable) <= threshold:
        return ChatMemoryBundle(
            memoryBlock=(prior_memory or "").strip(),
            recentMessages=usable[-keep:] if keep > 0 else [],
            summarizedCount=0,
        )

    older = usable[: max(0, len(usable) - keep)]
    recent = usable[-keep:] if keep > 0 else []
    bullets = []
    for i, m in enumerate(older):
        role = "你" if m.role == "user" else "编辑"
        text = " ".join(m.content.split()).strip()[:100]
        bullets.append(f"{i + 1}. [{role}] {text}{'…' if len(m.content) > 100 else ''}")

    prior = (prior_memory or "").strip()
    memory_block = "\n\n".join(
        p
        for p in [
            f"（既有记忆）\n{prior}" if prior else "",
            f"（更早对话节选 ×{len(bullets)}）\n" + "\n".join(bullets),
        ]
        if p
    )

    return ChatMemoryBundle(
        memoryBlock=memory_block[:3500],
        recentMessages=recent,
        summarizedCount=len(older),
    )


_MEMORY_SYSTEM = """你是对话记忆整理器。把用户与编辑 Agent 的早期对话压缩成结构化记忆，供后续轮次继续使用。
只保留会影响后续工作的内容，输出纯文本（非 JSON）：
【关键决定】—— 用户定下的方向、已接受的改写方案、剧情走向共识
【设定共识】—— 本对话中确认的角色/世界观细节（区别于作品档案，是对话新增的）
【待办/未竟】—— 用户要求但尚未完成的事、悬而未决的疑问
【其他】—— 值得记但上述三类之外的（语气偏好、禁用词等）
没有的类别省略。不要复述寒暄；控制在 400 字内。"""


async def summarize_chat_memory(
    provider,
    older_messages: List[AgentChatMessage],
    prior_memory: Optional[str] = None,
    *,
    max_chars: int = 3500,
) -> str:
    """LLM-structured rolling memory for long conversations.

    Summarizes messages older than the recent window into concise memory
    (decisions / setting consensus / todos / misc). Falls back to extractive
    bullets when the LLM call fails, so long chats never lose prior turns
    to a hard truncation.
    """
    if not older_messages:
        return (prior_memory or "").strip()

    transcript = "\n".join(
        f"[{'用户' if m.role == 'user' else '编辑'}] {m.content}"[:300]
        for m in older_messages
        if m.role in ("user", "assistant")
    )
    if not transcript.strip():
        return (prior_memory or "").strip()

    try:
        res = await provider.chat_completions(
            messages=[
                {"role": "system", "content": _MEMORY_SYSTEM},
                {
                    "role": "user",
                    "content": (
                        (f"既有记忆：\n{prior_memory}\n\n" if prior_memory and prior_memory.strip() else "")
                        + f"待整理对话：\n{transcript[:6000]}"
                    ),
                },
            ],
            temperature=0.2,
            timeout=90,
            max_tokens=700,
        )
        from app.core.llm_http import content_from_response

        content, _ = content_from_response(res)
        summary = (content or "").strip()
        if len(summary) >= 20:
            return summary[:max_chars]
    except Exception:  # noqa: BLE001 - degrade to extractive on any failure
        pass

    # Fallback: extractive bullets (existing behaviour) — or plain squeeze for
    # very short histories where bullet extraction has nothing to extract.
    if len(older_messages) <= 8:
        lines = [
            f"- [{'你' if m.role == 'user' else '编辑'}] {' '.join(m.content.split())[:120]}"
            for m in older_messages
            if m.role in ("user", "assistant")
        ]
        prior = (prior_memory or "").strip()
        return "\n".join(p for p in [prior, *lines] if p)[:max_chars]
    return compress_chat_history(
        older_messages, keep_recent=0, prior_memory=prior_memory
    ).memoryBlock[:max_chars]
