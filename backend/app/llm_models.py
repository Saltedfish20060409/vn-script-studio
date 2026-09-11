"""Canonical LLM model IDs and DeepSeek V4 alias rewriting.

Official DeepSeek IDs（2026-09-10 起）：``deepseek-flash`` 为 DeepSeek-V4.1-Flash
的正式模型名；``deepseek-v4-pro`` 在 V4.1 Pro 发布前仍可用（2026-09-14 12:00 起
其请求会路由到 V4.1 Flash 并按 V4.1 计费）。旧名 ``deepseek-v4-flash`` /
``deepseek-v4-flash-vision-exp`` 已被官方保留为兼容别名（实际由 V4.1 Flash 承接），
更老的 ``deepseek-chat`` / ``deepseek-reasoner`` 已下线——这些历史名字都在这里
改写，保证用户早先存下的设置继续可用。

V4 默认 thinking-on；本工作室显式下发 ``thinking`` 字段，除非用户选了
*-think / reasoner 别名，否则写作走非思考模式。
"""
from __future__ import annotations

from typing import Optional, Tuple

# V4.1 Flash 的官方模型名（服务端自 2026-09-10 起即为 V4.1）
DEFAULT_LLM_MODEL = "deepseek-flash"

_V41_FLASH = "deepseek-flash"

# Requested name → (upstream model, thinking type or None to omit the field)
_ALIASES: dict[str, Tuple[str, Optional[str]]] = {
    # 老名字（已下线）→ 现在的 V4.1 Flash
    "deepseek-chat": (_V41_FLASH, "disabled"),
    "deepseek-reasoner": (_V41_FLASH, "enabled"),
    # 官方兼容别名：仍接受，实际由 V4.1 Flash 承接
    "deepseek-v4-flash": (_V41_FLASH, "disabled"),
    "deepseek-v4-flash-think": (_V41_FLASH, "enabled"),
    "deepseek-v4-flash-vision-exp": (_V41_FLASH, "disabled"),
    # 正式名（2026-09-10 起）
    "deepseek-flash": (_V41_FLASH, "disabled"),
    "deepseek-flash-think": (_V41_FLASH, "enabled"),
    # Pro：V4.1 Pro 发布前仍可用，之后官方自动路由到 V4.1 Flash
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
    if raw.startswith("deepseek-"):
        return raw, "disabled"
    return raw, None
