"""注音（ruby）渲染：一套源语法 → 三种输出形态。

## 源语法（作者在正文里写的）

本项目用的是久负盛名的两类日式轻小说排版写法（`novel_craft` 负责校验，本模块负责渲染）：

- `｜汉字《注音》`（全角竖线，也接受 ASCII `|`）
- `{汉字|注音}`

## 输出形态（依据 W3C）

**W3C《Ruby Markup Extensions》** 定义的规范形态是：

```html
<ruby>漢字<rp>(</rp><rt>かんじ</rt><rp>)</rp></ruby>
```

`<rt>` 是注音，`<rp>` 是**回退括号**：不支持 ruby 的环境会把 `<rp>` 的内容显示出来，
于是读者看到的是 `漢字(かんじ)` 而不是丢掉注音或看成一串怪字符。这个"回退"正是
本模块三种形态的共同基础：

| 形态 | 长什么样 | 用在哪 |
|---|---|---|
| `html` | `<ruby>漢字<rp>(</rp><rt>かんじ</rt><rp>)</rp></ruby>` | Markdown / HTML 导出 |
| `rp` | `漢字（かんじ）` | 阅读用 docx、无法渲染 ruby 的场合（等价于 `<rp>` 回退） |
| `strip` | `漢字` | 字数统计、纯文本比对（注音不该影响字数） |
| `segments` | `[("ruby", "漢字", "かんじ")]` | 能表达结构注音的格式（Word 原生注音 `w:ruby`，见 `core/docx_ruby.py`） |

**为什么不给 Ren'Py 输出 `{rb}`/`{rt}`**：没能确证 Ren'Py 是否支持内联注音标签
（检索到的只有角色名侧的 `who_ruby`/`what_ruby`）。往用户的脚本里写未经验证的标签，
代价是脚本报错——所以 RPY 走 `rp` 形态，并把这件事写进 docs/references.md 的待办，
等确证后再补。

**Word 原生注音**（`w:ruby`）走 `segments()` 这条支路：它需要把基准词与注音分别放进
`<w:rubyBase>` 与 `<w:rt>`，而不是拼成一句话。取舍与可验证范围见 `core/docx_ruby.py`。

## 顺带修掉的一个真实缺陷

Ren'Py 的文本里 `{` `}` 是标签语法。导出器过去只转义了 `\\` 和 `"`，
于是正文里写了 `{汉字|注音}` 的作者，导出后会得到一个"未知文本标签"的报错脚本。
本模块的 `to_renpy_text` 同时做两件事：先把注音渲染成 `rp` 形态（不再留花括号），
再把剩余的 `{` `}` 转义成 `{{` `}}`（Ren'Py 的转义写法）。
"""

from __future__ import annotations

import re
from typing import Dict, List, Tuple

#: `｜汉字《注音》`：全角竖线或 ASCII 竖线开头，基准词 1..MAX_BASE 个"非标点"字符，后接《注音》。
#: 与 `novel_craft` 的解析保持一致（口径必须一样，否则"体检说没问题、导出却没渲染"）。
RUBY_BAR_RE = re.compile(r"[｜|]([^｜|《》\s]{1,24})《([^《》]*)》")
#: `{汉字|注音}`：花括号里恰好一个竖线。
RUBY_BRACE_RE = re.compile(r"\{([^{}|]{1,24})\|([^{}|]*)\}")

#: 全角括号是中文稿子的常规写法（`漢字（かんじ）`）；用半角在混排时更挤。
RP_OPEN = "（"
RP_CLOSE = "）"


def _is_renderable(base: str, reading: str) -> bool:
    """基准词与注音都非空才算可渲染的注音标记（空的交给 `novel_craft` 报问题）。"""
    return bool(base.strip()) and bool(reading.strip())


def render_ruby(text: str, form: str = "rp") -> str:
    """把文本里的注音标记渲染成指定形态；其余文字原样保留。

    ``form``：``html`` / ``rp`` / ``strip``（见模块说明）。
    不完整的标记（空的基准词或注音）**原样保留**——它们该由体检报出来，
    渲染层悄悄吞掉只会让作者找不到问题。
    """
    if not text:
        return text

    def make(base: str, reading: str) -> str:
        # 标记内的空格从来不是本意（`{ 笑顔|えがお }` 是书写习惯带来的），
        # 渲染时去掉——否则会把空格带进 `<rt>` 与投稿稿。
        base, reading = base.strip(), reading.strip()
        if form == "html":
            return (
                f"<ruby>{base}<rp>{RP_OPEN}</rp><rt>{reading}</rt>"
                f"<rp>{RP_CLOSE}</rp></ruby>"
            )
        if form == "strip":
            return base
        return f"{base}{RP_OPEN}{reading}{RP_CLOSE}"

    def bar_sub(m: "re.Match[str]") -> str:
        base, reading = m.group(1), m.group(2)
        return make(base, reading) if _is_renderable(base, reading) else m.group(0)

    def brace_sub(m: "re.Match[str]") -> str:
        base, reading = m.group(1), m.group(2)
        return make(base, reading) if _is_renderable(base, reading) else m.group(0)

    # 先花括号后竖线：`{...}` 里不可能再含 `｜…《…》`，顺序其实无关，
    # 但固定顺序能让"同一段文本两次渲染结果相同"这件事更容易推理。
    return RUBY_BAR_RE.sub(bar_sub, RUBY_BRACE_RE.sub(brace_sub, text))


def to_html(text: str) -> str:
    """Markdown / HTML 导出用：W3C 规范形态（含 `<rp>` 回退）。"""
    return render_ruby(text, "html")


def to_rp_text(text: str) -> str:
    """无法渲染 ruby 的场合：等价于 `<rp>` 回退的纯文本形态。"""
    return render_ruby(text, "rp")


def to_plain(text: str) -> str:
    """只要汉字（字数统计、纯文本比对）。"""
    return render_ruby(text, "strip")


#: 两类标记的**合并**模式：按出现位置切段（bar 与 brace 各扫一遍会打乱顺序）。
#: 命名组只是为了让下面的取用读起来清楚。
_RUBY_ANY_RE = re.compile(
    r"[｜|](?P<bar_base>[^｜|《》\s]{1,24})《(?P<bar_reading>[^《》]*)》"
    r"|(?P<brace>\{(?P<brace_base>[^{}|]{1,24})\|(?P<brace_reading>[^{}|]*)\})"
)


def segments(text: str) -> List[Tuple[str, str, str]]:
    """把一段文本切成 `("plain", 文本, "")` / `("ruby", 基准词, 注音)` 序列。

    给"能表达结构性注音的输出格式"用（目前是 Word 的原生注音 `w:ruby`：
    它需要把基准词与注音分别放进不同元素，而不像 rp/html 那样拼成一句话）。

    不完整的标记（基准或注音为空）按**普通文本**返回——与 `render_ruby` 同口径：
    该由体检报出来的东西，渲染层不吞。
    """
    out: List[Tuple[str, str, str]] = []
    if not text:
        return out
    cursor = 0
    for m in _RUBY_ANY_RE.finditer(text):
        base = m.group("bar_base") or m.group("brace_base") or ""
        reading = m.group("bar_reading") or m.group("brace_reading") or ""
        if not _is_renderable(base, reading):
            continue  # 当作普通文本，交给下面的尾巴一起带上
        if m.start() > cursor:
            out.append(("plain", text[cursor : m.start()], ""))
        out.append(("ruby", base.strip(), reading.strip()))
        cursor = m.end()
    if cursor < len(text):
        out.append(("plain", text[cursor:], ""))
    return out


def to_renpy_text(text: str) -> str:
    """Ren'Py 文本：注音转 `rp` 形态 + 转义花括号。

    两件事都必须做：注音标记里的 `{` 会变成未知标签；而作者正文里任何其它的 `{`
    （字典、代码、颜文字）同样会让 Ren'Py 报错或吞字。
    """
    rendered = to_rp_text(text or "")
    return rendered.replace("{", "{{").replace("}", "}}")


def ruby_marks(text: str) -> List[Dict[str, str]]:
    """按出现顺序列出可渲染的注音标记（`base` / `reading` / `form`）。"""
    marks: List[Dict[str, str]] = []
    for m in RUBY_BAR_RE.finditer(text or ""):
        if _is_renderable(m.group(1), m.group(2)):
            marks.append({"base": m.group(1), "reading": m.group(2), "form": "bar"})
    for m in RUBY_BRACE_RE.finditer(text or ""):
        if _is_renderable(m.group(1), m.group(2)):
            marks.append({"base": m.group(1), "reading": m.group(2), "form": "brace"})
    return marks
