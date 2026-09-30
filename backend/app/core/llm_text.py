"""模型输出的「格式自愈」。

为什么需要：模型偶尔会把**整段回复当成转义字符串或代码块**吐出来，例如

    renpy\\n周屿 \\"末班车还有四分钟。\\"\\n\\n他没看表，看的是她。\\n

这是实测撞到的（对照测试里同一句任务，一次干净、一次全篇字面 `\\n`）：
JSON 里 `\\n` 是换行，可模型写成了 `\\\\n`（双重转义），我们 `json.loads` 一次之后
拿到的是**字面的反斜杠 n**，于是界面上就显示成 `renpy\\n周屿 ...` 这种垃圾。

这里做两件保守的事，只在"看起来确实坏了"时才动手：
1. 整段没有一个真换行、却有一堆字面 `\\n` → 反转义（交给 json 解，失败再逐项替换）；
2. 剥掉代码围栏（```renpy ... ```）与开头的裸语言标记行（`renpy`）。

刻意保守：正常文本一律原样返回——宁可偶尔漏救，也不要把好文本改坏。
"""

from __future__ import annotations

import json
import re
from typing import Any, Optional

# 语言标记：只有"整行就一个这类词"才当成围栏标签剥掉
_LANG_TOKENS = {
    "renpy", "rpy", "python", "python3", "py", "json", "javascript", "js",
    "typescript", "ts", "markdown", "md", "yaml", "yml", "text", "txt",
    "bash", "sh", "html", "css",
}

_FENCE_OPEN_RE = re.compile(r"^\s*```[A-Za-z0-9_+-]*[ \t]*\r?\n?")
_FENCE_CLOSE_RE = re.compile(r"\r?\n?[ \t]*```\s*$")


def looks_escaped(text: str) -> bool:
    """整段是不是被当成转义字符串吐出来的。"""
    if not text:
        return False
    literal = text.count("\\n")  # 字面：反斜杠 + n
    real = text.count("\n")      # 真换行
    if literal < 2:
        return False
    # 情况一：完全没有真换行，却有两处以上字面 \n（最常见）
    if real == 0:
        return True
    # 情况二：真换行很少、字面远多于它（半截被转义）
    return literal >= 4 and literal > real * 2


def unescape_model_text(text: str) -> str:
    """把双重转义的文本还原。json 解不动时退回逐项替换。

    注意：这里**不能**先把反斜杠再转义一遍（那样 `\\n` 会变成字面的 `\\\\n`，
    解出来还是坏的）。直接把整段当成一个 JSON 字符串体来解即可：
    正常情况它的转义序列本来就是合法的 JSON 转义（`\\n` / `\\"`）。
    只有模型漏转义了裸引号等非法序列时，才走逐项替换的兜底。
    """
    try:
        decoded = json.loads('"' + text + '"')
        if isinstance(decoded, str) and decoded:
            return decoded
    except (json.JSONDecodeError, ValueError):
        pass
    out = text
    out = out.replace("\\r\\n", "\n").replace("\\n", "\n").replace("\\r", "\n")
    out = out.replace("\\t", "\t").replace('\\"', '"').replace("\\'", "'")
    out = out.replace("\\\\", "\\")  # 放最后：别先造出新的 \n
    return out


def strip_code_fence(text: str) -> str:
    """剥掉 ```lang ... ``` 围栏，以及开头的裸语言标记行（`renpy`）。"""
    out = text.strip()
    if "```" in out:
        out = _FENCE_OPEN_RE.sub("", out)
        out = _FENCE_CLOSE_RE.sub("", out).strip()
    lines = out.split("\n")
    if len(lines) >= 2:
        head = lines[0].strip().lower()
        if head in _LANG_TOKENS and len(lines[0].strip()) <= 12:
            rest = "\n".join(lines[1:]).lstrip("\n")
            if rest.strip():
                out = rest
    return out


def normalize_model_text(text: str) -> str:
    """对外唯一入口：需要时反转义 + 剥围栏，否则原样返回。"""
    if not isinstance(text, str) or not text:
        return text
    out = text
    if looks_escaped(out):
        out = unescape_model_text(out)
    if "```" in out or out.split("\n")[0].strip().lower() in _LANG_TOKENS:
        out = strip_code_fence(out)
    return out


# ---------------------------------------------------------------------------
# 抽 JSON：**围栏最后才看**
# ---------------------------------------------------------------------------

#: 只有"整段被一层围栏从头包到尾"才算围栏。
#: 千万不要用 ```` ```(?:json)?\s*([\s\S]*?)``` ```` 去 `search`——那会连**字符串值里**
#: 的围栏一起匹配，把整份回复劫持成一小段示例（见 `extract_json_object` 的说明）。
_WHOLE_FENCE_RE = re.compile(
    r"^\s*```[A-Za-z0-9_+.-]*[ \t]*\r?\n(?P<body>[\s\S]*?)\r?\n?[ \t]*```\s*$"
)


def _balanced_json_container(text: str) -> Optional[str]:
    """从第一个 `{` / `[` 起配平括号切出这一段；字符串里的括号不算数。"""
    braces = [i for i in (text.find("{"), text.find("[")) if i >= 0]
    if not braces:
        return None
    start = min(braces)
    pairs = {"{": "}", "[": "]"}
    stack: list[str] = []
    in_string = False
    escaped = False
    for i in range(start, len(text)):
        ch = text[i]
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in pairs:
            stack.append(pairs[ch])
        elif ch in ("}", "]"):
            if not stack or stack.pop() != ch:
                return None
            if not stack:
                return text[start : i + 1]
    return None


def _json_candidates(text: str):
    """按优先级给出"可能就是那段 JSON"的候选片段（顺序即优先级）。"""
    raw = (text or "").strip()
    if not raw:
        return
    yield raw
    sliced = _balanced_json_container(raw)
    if sliced and sliced != raw:
        yield sliced
    match = _WHOLE_FENCE_RE.match(raw)
    body = match.group("body").strip() if match else ""
    if body:
        yield body
        inner = _balanced_json_container(body)
        if inner and inner != body:
            yield inner


def extract_json_value(text: str) -> Optional[Any]:
    """取出模型输出里的 JSON 值（对象或数组都认）；取不到返回 None。"""
    for candidate in _json_candidates(text):
        try:
            return json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
    return None


def extract_json_object(text: str) -> Optional[dict]:
    r"""取出模型输出里的 JSON 对象；取不到返回 None（兜底由调用方决定）。

    为什么需要它（2026-09-27 线上实盘）：作者附上第一章问「帮我审查一下第一章……应该怎么改
    合适？」，拿到的回复只有 214 字的一段示例对白，两千多字的审稿分析不见了。模型**答对了**
    ——同一条 messages、同一个模型重跑一次，一次调用就返回 2427 字的完整意见。

    丢在解析上：模型的 `message` 里嵌了一段 ```` ```renpy ```` 示例对白（提示词本来就写着
    "可摘改写示例对白"），而各处解析器都是同一个顺序——

        fence = _FENCE_RE.search(text)     # 先找围栏
        if fence: text = fence.group(1)    # 把围栏内容当成 JSON
        text = text[text.find("{"): text.rfind("}") + 1]

    `_FENCE_RE` 用 `[\s\S]*?` 非贪婪地从**第一个**围栏取到第二个，于是字符串值里那段示例被
    当成了整份输出；它当然不是合法 JSON，于是落到"纯文本当回复"的兜底——作者就只看到那段示例，
    JSON 里真正的回复被静默丢掉，症状看起来像"模型理解不了指令"。

    顺序即优先级，围栏只做最后一招：
    1. 整段就是 JSON（开了 `response_format` 时最常见）；
    2. 配平括号切出对象（前后夹着解释文字也能救回来）；
    3. **整段被一层围栏包着**才剥围栏，再按 1/2 试一次。
    """
    for candidate in _json_candidates(text):
        try:
            parsed = json.loads(candidate)
        except (json.JSONDecodeError, ValueError):
            continue
        if isinstance(parsed, dict):
            return parsed
    return None


# ---------------------------------------------------------------------------
# 从**写坏/被截断**的 JSON 里抢救 message
#
# 为什么需要（2026-09-30 线上实盘）：作者两次让 Agent「写完整的第一章」，模型把整章正文塞进
# JSON 的 `message` 里返回，输出一断（长字符串/撞上限），`extract_json_object` 全部候选都失败，
# 于是 message 与 actions 一起丢——屏幕上只剩一段被截到 2000 字的裸 JSON（看起来像"模型胡说"），
# 而稿子里**一个字都没写进去**，撤回栈也是空的。两条独立损失叠在一起才让这件事看起来像"续写很差"。
#
# 这里的原则：**只救文本**。`actions` 一律丢弃——动作可能正好切在半路（比如 append_script 的正文
# 只写到一半），把它落盘比不落盘更糟。要写入就让作者看到提示后重来一次。
# ---------------------------------------------------------------------------

#: `"message"\s*:\s*"` 之后的第一个字符就是内容的起点
_MESSAGE_KEY_RE = re.compile(r'"message"\s*:\s*"')


def _repair_unterminated_json(text: str) -> Optional[str]:
    """把"被截断在半路"的 JSON 补上收尾（只补字符串与括号，不改内容）；补不出来返回 None。

    只在**确实没闭合**时返回值（已闭合的不归它管，避免把 `{...}garbage` 也当成功）。
    """
    raw = text or ""
    starts = [i for i in (raw.find("{"), raw.find("[")) if i >= 0]
    if not starts:
        return None
    start = min(starts)
    pairs = {"{": "}", "[": "]"}
    stack: list[str] = []
    in_string = False
    escaped = False
    for ch in raw[start:]:
        if in_string:
            if escaped:
                escaped = False
            elif ch == "\\":
                escaped = True
            elif ch == '"':
                in_string = False
            continue
        if ch == '"':
            in_string = True
        elif ch in pairs:
            stack.append(pairs[ch])
        elif ch in ("}", "]"):
            if not stack or stack.pop() != ch:
                return None
            if not stack:
                return None  # 已经闭合了：不归这个函数管
    if not stack:
        return None
    tail = '"' if in_string else ""
    return raw[start:] + tail + "".join(reversed(stack))


def _scan_message_literal(text: str) -> Optional[str]:
    """按 `"message":"…"` 的字面量扫描取内容；字符串被截断时就交付已读到的部分。"""
    match = _MESSAGE_KEY_RE.search(text or "")
    if not match:
        return None
    out: list[str] = []
    escaped = False
    i = match.end()
    while i < len(text):
        ch = text[i]
        if escaped:
            out.append("\\" + ch)
            escaped = False
        elif ch == "\\":
            escaped = True
        elif ch == '"':
            break
        else:
            out.append(ch)
        i += 1
    body = "".join(out)
    if not body.strip():
        return None
    # 正常收尾（扫到了闭合引号）就走 json 反转义；被截断在半路时退回手工替换常见转义
    try:
        unescaped = json.loads('"' + body + '"')
    except (json.JSONDecodeError, ValueError):
        unescaped = (
            body.replace("\\n", "\n").replace('\\"', '"').replace("\\t", "\t").rstrip("\\")
        )
    text_out = normalize_model_text(str(unescaped).strip())
    return text_out or None


def salvage_message_from_broken_json(text: str) -> Optional[str]:
    """从**解析失败**的输出里尽量把 `message` 救回来（救不到返回 None，动作一律不带回）。

    两条路：先把缺的引号/括号补齐再解析；补不出来（例如正切在转义字符中间）就按
    `"message"` 的字面量扫描，把已经写出来的那部分交出去——宁可给作者半章，也不要给一坨 JSON。
    """
    raw = (text or "").strip()
    if not raw:
        return None
    repaired = _repair_unterminated_json(raw)
    if repaired:
        try:
            parsed = json.loads(repaired)
        except (json.JSONDecodeError, ValueError):
            parsed = None
        if isinstance(parsed, dict):
            msg = parsed.get("message")
            if isinstance(msg, str) and msg.strip():
                return normalize_model_text(msg.strip())
    return _scan_message_literal(raw)
