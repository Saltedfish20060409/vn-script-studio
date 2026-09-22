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
