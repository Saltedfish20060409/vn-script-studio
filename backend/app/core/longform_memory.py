"""Ported from packages/core/src/longformMemory.ts"""
from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import List, Optional

from app.core import llm_budget
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

#: 作者改口、禁令、明确决定。只认用户原话，不认模型复述。
_DECISION_RE = re.compile(
    r"(不要|别再|不准|禁止|不能|改成|改为|换成|更正|必须|记住|定一下|就按|确认|禁用|算了)"
)
_OVERRIDE_RE = re.compile(r"(改成|改为|换成|更正|不要再用|算了)")
_ACK_RE = re.compile(
    r"^(好的?|收到|明白了?|嗯+|可以|ok|okay|知道了|行)[。.!！…]*$",
    re.IGNORECASE,
)
DECISION_HEADING = "## 对话决定（作者确认，不得自行推翻）"
_MAX_PINNED = 12


def _plain(text: str) -> str:
    return " ".join((text or "").split()).strip()


def extract_chat_decisions(
    messages: List[AgentChatMessage],
) -> tuple[List[str], List[str]]:
    """返回 (仍有效的决定原文, 已被后续改口覆盖的短行)。

    覆盖规则只看作者后来是否明确改口，不看模型重复了几次。
    """
    last_override = -1
    for i, message in enumerate(messages):
        if message.role == "user" and _OVERRIDE_RE.search(message.content or ""):
            last_override = i
    pinned: List[str] = []
    superseded: List[str] = []
    for i, message in enumerate(messages):
        if message.role != "user":
            continue
        text = _plain(message.content)
        if not text or _ACK_RE.match(text) or not _DECISION_RE.search(text):
            continue
        if last_override >= 0 and i < last_override:
            superseded.append(text[:80])
        else:
            pinned.append(text[:400])
    return pinned[:_MAX_PINNED], superseded[:6]


def render_decision_block(pinned: List[str], superseded: List[str]) -> str:
    if not pinned and not superseded:
        return ""
    lines = [DECISION_HEADING]
    for item in pinned:
        lines.append(f"- {item}")
    for item in superseded:
        lines.append(f"- （已被后续决定覆盖）{item}")
    lines.append("需要更早原话时用 search_chat 检索本会话。")
    return "\n".join(lines)


def split_chat_memory(block: str) -> tuple[str, str]:
    """把「对话决定」从滚动节选里拆出来。决定块单独钉住，节选可以让位。"""
    text = (block or "").strip()
    if not text or DECISION_HEADING not in text:
        return "", text
    start = text.find(DECISION_HEADING)
    rest_after = text[start + len(DECISION_HEADING) :]
    next_heading = rest_after.find("\n## ")
    if next_heading >= 0:
        decision = (DECISION_HEADING + rest_after[:next_heading]).strip()
        tail = (text[:start] + rest_after[next_heading + 1 :]).strip()
    else:
        decision = text[start:].strip()
        tail = text[:start].strip()
    return decision, tail


def _older_bullets(
    messages: List[AgentChatMessage],
    decision_source: Optional[List[AgentChatMessage]] = None,
) -> tuple[str, str]:
    pinned, superseded = extract_chat_decisions(decision_source or messages)
    pinned_norm = {_plain(item) for item in pinned}
    superseded_norm = {_plain(item) for item in superseded}
    bullets: List[str] = []
    for message in messages:
        text = _plain(message.content)
        if not text or _ACK_RE.match(text):
            continue
        if message.role == "user" and (
            text[:400] in pinned_norm or text[:80] in superseded_norm or _DECISION_RE.search(text)
        ):
            continue
        role = "作者" if message.role == "user" else "编辑"
        bullets.append(f"- [{role}] {text[:80]}")
    decision = render_decision_block(pinned, superseded)
    excerpt = ""
    if bullets:
        excerpt = f"## 更早对话节选 ×{len(bullets)}\n" + "\n".join(bullets)
    return decision, excerpt


def _merge_decision_blocks(fresh: str, prior: str) -> str:
    """合并两段决定。后写的原文在前；既有决定里还没出现的行附在后面。"""
    if not prior:
        return fresh
    if not fresh:
        return prior
    extra = [
        line
        for line in prior.splitlines()
        if line.startswith("- ") and line not in fresh
    ]
    if not extra:
        return fresh
    return fresh.rstrip() + "\n" + "\n".join(extra)


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

    if len(usable) <= threshold and keep > 0:
        return ChatMemoryBundle(
            memoryBlock=(prior_memory or "").strip(),
            recentMessages=usable[-keep:] if keep > 0 else [],
            summarizedCount=0,
        )

    older = usable[: max(0, len(usable) - keep)]
    recent = usable[-keep:] if keep > 0 else []
    decision, excerpt = _older_bullets(older, usable)
    prior_decision, prior_rest = split_chat_memory(prior_memory or "")
    decision = _merge_decision_blocks(decision, prior_decision)
    prior_rest = prior_rest.strip()
    memory_block = "\n\n".join(
        p
        for p in [
            decision,
            f"（既有记忆）\n{prior_rest}" if prior_rest else "",
            excerpt,
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

    pinned, superseded = extract_chat_decisions(older_messages)
    prior_decision, prior_rest = split_chat_memory(prior_memory or "")
    local_decisions = _merge_decision_blocks(
        render_decision_block(pinned, superseded), prior_decision
    )

    def _with_decisions(body: str) -> str:
        text = (body or "").strip()
        if not local_decisions:
            return text[:max_chars]
        if DECISION_HEADING in text:
            return text[:max_chars]
        return f"{local_decisions}\n\n{text}".strip()[:max_chars]

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
                        (f"既有记忆：\n{prior_rest}\n\n" if prior_rest.strip() else "")
                        + f"待整理对话：\n{transcript[:6000]}"
                    ),
                },
            ],
            temperature=0.2,
            timeout=llm_budget.MEDIUM,
            max_tokens=700,
        )
        from app.core.llm_http import content_from_response

        content, _ = content_from_response(res)
        summary = (content or "").strip()
        if len(summary) >= 20:
            return _with_decisions(summary)
    except Exception:  # noqa: BLE001 - degrade to extractive on any failure
        pass

    # Fallback: extractive bullets (existing behaviour) — or plain squeeze for
    # very short histories where bullet extraction has nothing to extract.
    if len(older_messages) <= 8:
        lines = []
        pinned_norm = {_plain(item) for item in pinned}
        for message in older_messages:
            if message.role not in ("user", "assistant"):
                continue
            text = _plain(message.content)
            if not text or _ACK_RE.match(text) or text[:400] in pinned_norm:
                continue
            role = "作者" if message.role == "user" else "编辑"
            lines.append(f"- [{role}] {text[:120]}")
        return _with_decisions("\n".join(p for p in [prior_rest.strip(), *lines] if p))
    return compress_chat_history(
        older_messages, keep_recent=0, prior_memory=prior_memory
    ).memoryBlock[:max_chars]
