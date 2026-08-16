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
