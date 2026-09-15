"""条件表达式的解析 / 求值 / 导出（分支与旗标的地基）。

设计取舍：**不做完整表达式语言，只支持受控的小语法**。

为什么：条件要同时满足三件事——① 前端试玩器能求值；② 导出成 Ren'Py 时不能被注入
任意 Python；③ 作者一眼能看懂。所以限定为「比较 + and 连接」：

    cond   := term (('and' | '&&' | '并且') term)*
    term   := ident (op value)?
    op     := == | != | >= | <= | > | <
    value  := 数字 | "字符串" | true | false
    ident  := [A-Za-z_][A-Za-z0-9_]*

例：`affection >= 3`、`flag == "true"`、`affection >= 3 and saw_umbrella`、`seen_bad_end`

Ren'Py 表达式就是 Python，上面这些写法原样合法；导出时 repl 保证只剩白名单字符，
不会把作者输入的奇怪内容带进脚本。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Tuple

_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_OPS = ("==", "!=", ">=", "<=", ">", "<")
_AND_RE = re.compile(r"\s*(?:&&|\band\b|并且)\s*", re.IGNORECASE)
_NUMBER_RE = re.compile(r"^-?\d+(?:\.\d+)?$")
_QUOTED_RE = re.compile(r'^"((?:\\.|[^"\\])*)"$')


@dataclass(frozen=True)
class Comparison:
    """`key op value`，或只有 key（真值判断）。"""

    key: str
    op: Optional[str] = None
    value: Any = None


Condition = Tuple[Comparison, ...]  # 空元组 = 恒真（无条件）


class ConditionError(ValueError):
    """语法不合法。作者写错时应当看到明确报错，而不是静默当作恒真。"""


def _parse_value(raw: str) -> Any:
    t = raw.strip()
    if not t:
        raise ConditionError("缺少比较值")
    low = t.lower()
    if low == "true":
        return True
    if low == "false":
        return False
    if _NUMBER_RE.match(t):
        return float(t) if "." in t else int(t)
    m = _QUOTED_RE.match(t)
    if m:
        return m.group(1).replace('\\"', '"').replace("\\\\", "\\")
    # 允许裸词当字符串（作者常写 flag == yes 这种）；但必须像标识符，避免塞表达式
    if _IDENT_RE.match(t):
        return t
    raise ConditionError(f"无法识别的比较值：{t[:40]}")


def _parse_term(raw: str) -> Comparison:
    t = raw.strip()
    if not t:
        raise ConditionError("条件里有空的比较项")
    for op in _OPS:
        idx = t.find(op)
        if idx > 0:
            key = t[:idx].strip()
            if not _IDENT_RE.match(key):
                raise ConditionError(f"变量名不合法：{key[:40]}")
            return Comparison(key=key, op=op, value=_parse_value(t[idx + len(op) :]))
    if not _IDENT_RE.match(t):
        raise ConditionError(f"条件写法不支持：{t[:40]}（示例：affection >= 3）")
    return Comparison(key=t)


def parse_condition(text: Optional[str]) -> Condition:
    """解析条件字符串；空字符串 → 无条件（恒真）。语法错误抛 ConditionError。"""
    raw = (text or "").strip()
    if not raw:
        return ()
    return tuple(_parse_term(part) for part in _AND_RE.split(raw) if part.strip())


def condition_keys(cond: Condition) -> List[str]:
    """条件里引用到的变量名（用于"变量未定义"检查）。"""
    seen: List[str] = []
    for c in cond:
        if c.key not in seen:
            seen.append(c.key)
    return seen


def _coerce_compare(left: Any, right: Any) -> Tuple[Any, Any, bool]:
    """数字与字符串混用时做一次温和转换；转不了就按不等处理。"""
    if isinstance(left, bool) or isinstance(right, bool):
        return left, right, True
    if isinstance(left, (int, float)) and isinstance(right, str):
        try:
            return left, float(right), True
        except ValueError:
            return left, right, False
    if isinstance(left, str) and isinstance(right, (int, float)):
        try:
            return float(left), right, True
        except ValueError:
            return left, right, False
    return left, right, True


def evaluate_condition(cond: Condition, variables: Dict[str, Any]) -> bool:
    """按给定变量值求值。未定义的变量视为 0/false（与 Ren'Py 的 undefined 行为不同，
    但试玩器里"没定义=假"最不容易吓到作者；真正的一致性问题由变量检查报告提示）。"""
    for c in cond:
        left = variables.get(c.key)
        if left is None:
            left = False if c.op in (None, "==", "!=") else 0
        if c.op is None:
            if not bool(left):
                return False
            continue
        right = c.value
        lhs, rhs, comparable = _coerce_compare(left, right)
        if c.op in ("==", "!="):
            equal = lhs == rhs if comparable else False
            if (c.op == "==") != bool(equal):
                return False
            continue
        if not comparable:
            return False
        try:
            if c.op == ">=":
                ok = lhs >= rhs
            elif c.op == "<=":
                ok = lhs <= rhs
            elif c.op == ">":
                ok = lhs > rhs
            else:
                ok = lhs < rhs
        except TypeError:
            return False
        if not ok:
            return False
    return True


def _render_value(value: Any) -> str:
    if isinstance(value, bool):
        return "True" if value else "False"
    if isinstance(value, str):
        if _IDENT_RE.match(value) and value.lower() not in ("true", "false"):
            # 裸词当作变量名（作者写 flag == yes 时，yes 在 Ren'Py 里通常也是变量）
            return value
        return '"' + value.replace("\\", "\\\\").replace('"', '\\"') + '"'
    return str(value)


def render_condition(cond: Condition) -> str:
    """生成 Ren'Py 条件表达式（仅白名单字符，天然不可注入）。"""
    parts: List[str] = []
    for c in cond:
        if c.op is None:
            parts.append(c.key)
        else:
            parts.append(f"{c.key} {c.op} {_render_value(c.value)}")
    return " and ".join(parts) if parts else "True"


def condition_source(text: Optional[str]) -> str:
    """便利函数：把作者写的条件规范化成 Ren'Py 表达式（空 → True）。"""
    return render_condition(parse_condition(text))
