"""Canonical LLM model IDs and DeepSeek V4 alias rewriting.

Official DeepSeek IDs（2026-09-10 起）：``deepseek-flash`` 为 DeepSeek-V4.1-Flash
的正式模型名；``deepseek-v4-pro`` 在 V4.1 Pro 发布前仍可用（2026-09-14 12:00 起
其请求会路由到 V4.1 Flash 并按 V4.1 计费）。旧名 ``deepseek-v4-flash`` /
``deepseek-v4-flash-vision-exp`` 已被官方保留为兼容别名（实际由 V4.1 Flash 承接），
更老的 ``deepseek-chat`` / ``deepseek-reasoner`` 已下线——这些历史名字都在这里
改写，保证用户早先存下的设置继续可用。

V4 默认 thinking-on；本工作室显式下发 ``thinking`` 字段：默认档位（含 ``deepseek-flash``）
是 **disabled**，只有选了 *-think / reasoner 别名才 enabled。所以"同一份材料网页版写得更好"
里有一层就是**我们自己把思考关了**——写作通道用 `resolve_write_model` 把它开回来（见下）。
"""
from __future__ import annotations

from typing import Dict, Optional, Tuple

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


#: 非思考档 → 同族思考档。**只列我们自己的档位**：写作通道拿它做"自动开思考"，
#: 别的厂商 / 自建端点不在表里，也就永远不会被替作者换掉。
_THINK_SIBLINGS: Dict[str, str] = {
    "deepseek-flash": "deepseek-flash-think",
    "deepseek-v4-flash": "deepseek-v4-flash-think",
    "deepseek-v4-pro": "deepseek-v4-pro-think",
    "deepseek-chat": "deepseek-reasoner",
}


def resolve_write_model(name: Optional[str], mode: str = "auto") -> str:
    """写作通道（writer 条件）该用哪一档模型。

    为什么单独一个函数（2026-09-30 与网页版的正面对比）：同一份材料、同一个底座，
    网页版是**开着深度思考**写出来的（首轮思考 11.6k 字，然后 3052 字成稿），
    而我们下发的是 ``thinking: disabled``——"Agent 不如网页版"里有相当一部分就是这个差。
    写作通道是自由文本、不需要 JSON，思考档在这里没有互斥问题（见 `model_presets`：
    ``*-think`` 的 ``json_mode`` 是 False，所以聊天那条路用不了它）。

    ``mode``：
    - ``auto``（默认）/ ``on``：配置的是上面那张表里的档位时，换成同族思考档；
    - ``off``：完全按作者选的档位走（改动前的行为）。
    不在表里的模型（其它厂商、自建端点、自定义名字）**一律原样返回**——替作者换别人家的
    模型是越权，而且我们并不知道那一档支不支持思考。
    """
    raw = (name or "").strip() or DEFAULT_LLM_MODEL
    if (mode or "auto").strip().lower() == "off":
        return raw
    return _THINK_SIBLINGS.get(raw, raw)
