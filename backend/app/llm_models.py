"""Canonical LLM model IDs and DeepSeek V4 alias rewriting.

Official DeepSeek IDs (after 2026-07-24) are ``deepseek-v4-flash`` and
``deepseek-v4-pro``. Legacy ``deepseek-chat`` / ``deepseek-reasoner`` are
rewritten here so stored settings keep working. V4 defaults to thinking-on;
this studio sends an explicit ``thinking`` flag so writing stays non-thinking
unless the user picks a *-think / reasoner alias.
"""
from __future__ import annotations

from typing import Optional, Tuple

DEFAULT_LLM_MODEL = "deepseek-v4-flash"

# Requested name → (upstream model, thinking type or None to omit the field)
_ALIASES: dict[str, Tuple[str, Optional[str]]] = {
    "deepseek-chat": ("deepseek-v4-flash", "disabled"),
    "deepseek-reasoner": ("deepseek-v4-flash", "enabled"),
    "deepseek-v4-flash": ("deepseek-v4-flash", "disabled"),
    "deepseek-v4-flash-think": ("deepseek-v4-flash", "enabled"),
    "deepseek-v4-pro": ("deepseek-v4-pro", "disabled"),
    "deepseek-v4-pro-think": ("deepseek-v4-pro", "enabled"),
}


def resolve_chat_model(name: Optional[str]) -> Tuple[str, Optional[str]]:
    """Return (upstream_model, thinking_type).

    ``thinking_type`` is ``enabled`` / ``disabled`` for DeepSeek V4, else None
    so other vendors never see a ``thinking`` body field.
    """
    raw = (name or "").strip() or DEFAULT_LLM_MODEL
    if raw in _ALIASES:
        return _ALIASES[raw]
    if raw.startswith("deepseek-v4-"):
        return raw, "disabled"
    return raw, None
