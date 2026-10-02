"""正文档（writing_surface=prose）引擎语法硬拒。

规则版本与 ``shared/test-fixtures/engine_syntax_cases.json`` 对齐。
关 ``Settings.enforce_prose_engine_syntax_reject`` 时整段 P4.5 护栏（含前端）应一并关掉。
"""

from __future__ import annotations

import re
from typing import List, Optional, Tuple

# 固定文案（方案写死；测试断言子串）
PROSE_ENGINE_REJECT_MSG = (
    "这段含引擎语法（如 label / $ / with fade），正文档只接受自然语言。"
    "若要生成 Ren'Py 脚本，请切到 RPY 面或使用「根据剧本生成」。"
)

PROSE_ENGINE_PATCH_MSG = (
    "第 {n} 条改写含引擎语法（如 label / $ / with fade），正文档只接受自然语言。"
    "若要生成 Ren'Py 脚本，请切到 RPY 面或使用「根据剧本生成」。"
    "该条未写入；其余条目仍按定点规则处理。"
)

PASTE_ENGINE_HINT = "这段内容含引擎语法，是否要粘贴到 RPY 面？"

# L1–L11：行级；关键字小写字面量（Scene/SHOW 不命中）
_L1 = re.compile(r"^\s*label\s+[A-Za-z_][A-Za-z0-9_]*\s*:")
_L2 = re.compile(r"^\s*menu(\s+[A-Za-z_][A-Za-z0-9_]*)?\s*:")
_L3 = re.compile(r"^\s*define\s+[A-Za-z_][A-Za-z0-9_]*\s*=")
_L4 = re.compile(r"^\s*jump\s+[A-Za-z_][A-Za-z0-9_]*\s*(#.*)?$")
_L5 = re.compile(
    r"^\s*(scene|show|hide)\s+[A-Za-z_][A-Za-z0-9_.]*"
    r"(?:\s+at\s+\S+)?(?:\s+with\s+\S+)?\s*$"
)
_L6 = re.compile(r"^\s*with\s+(fade|dissolve|None|vpunch|hpunch)\b")
_L7 = re.compile(r"^\s*\$\s*(?:[A-Za-z_]\w*|renpy\.)")
_L8 = re.compile(r"^\s*if\s+(?:not\s+)?[A-Za-z_]\w*\s*:")
_L9 = re.compile(r"^\s*\[label\s+[^\]]+\]")
_L10 = re.compile(r"^\s*\[(场景|出现|消失)(\s*[:：]\s*[^\]]*|\s+[^\]]+)\]")
_L11 = re.compile(r"renpy\.input\s*\(")

_LINE_RULES: List[Tuple[str, re.Pattern[str]]] = [
    ("L1", _L1),
    ("L2", _L2),
    ("L3", _L3),
    ("L4", _L4),
    ("L5", _L5),
    ("L6", _L6),
    ("L7", _L7),
    ("L8", _L8),
    ("L9", _L9),
    ("L10", _L10),
]


def line_has_engine_syntax(line: str) -> Optional[str]:
    """单行命中则返回规则 id（L1–L11），否则 None。"""
    raw = line.replace("\r\n", "\n").replace("\r", "\n")
    # 去掉行尾 # 注释再配 L8 等（Ren'Py 常见）
    stripped = raw.split("#", 1)[0] if "#" in raw else raw
    for rid, pat in _LINE_RULES:
        if pat.search(stripped):
            return rid
    if _L11.search(raw):
        return "L11"
    return None


def text_has_engine_syntax(text: str) -> Optional[str]:
    """全文任一行命中 → 规则 id；否则 None。"""
    if not text:
        return None
    for line in text.replace("\r\n", "\n").replace("\r", "\n").split("\n"):
        hit = line_has_engine_syntax(line)
        if hit:
            return hit
    return None


def prose_engine_reject_enabled() -> bool:
    from app.config import get_settings

    return bool(getattr(get_settings(), "enforce_prose_engine_syntax_reject", True))
