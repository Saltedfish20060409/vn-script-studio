"""专注模式的"纸面"约定：与主题无关的暖白纸，且纸色与字色必须成对。

为什么值得一个文件：
1. 专注模式全屏只留稿子——作者一盯就是几十分钟，底色与字色的搭配在这里最要紧。
   夜间主题的 `--paper` 是 `#0a0507` 纯黑，全屏一大片黑既刺眼也不像"稿纸"，
   所以专注模式**不复用主题纸色**，而是自己定义一套暖白纸 token。
2. 这类改动最容易只做一半：把编辑器底色刷成米白，却忘了夜间主题的 `--ink`
   是 `#ffe8ec`（浅粉）——于是字直接看不见。所以这里不仅断言"有纸色"，
   还**直接解析 CSS 里的取值算 WCAG 对比度**：数字比"看起来还行"可靠。
3. 顺带钉住"专注模式不渲染写作辅助"：那条是边写边看读数用的，与专注的意图相反
   （本场字数由专注计时条的「+N 字」显示）。

路径口径与 `test_rule_basis.py` 等跨语言守卫一致：容器里前端源码被拷到
`/tmp/frontend/src`，所以用 `parents[2]` 定位（本地就是仓库根）。
"""

from __future__ import annotations

import re
from pathlib import Path

FRONTEND_SRC = Path(__file__).resolve().parents[2] / "frontend" / "src"
APP_CSS = FRONTEND_SRC / "components" / "StudioApp.module.css"
APP_TSX = FRONTEND_SRC / "components" / "StudioApp.tsx"

#: 夜间主题的纸色。专注模式若取到这个值，说明"暖白纸面"这层覆盖被删掉了。
NIGHT_PAPER = "#0a0507"

#: 十六进制色值。**六位必须排在三位前面**：正则的交替取第一个能匹配的分支，
#: 先写三位就会把 `#f6f1e6` 截成 `#f6f`（第一次跑就是这么错的，对比度算出 1.26）。
_HEX = r"#(?:[0-9a-fA-F]{6}|[0-9a-fA-F]{3})(?![0-9a-fA-F])"


def _focus_token_block() -> str:
    """取出 `.focusMode { ... }` 这个自定义属性块（token 定义处）。"""
    text = APP_CSS.read_text(encoding="utf-8")
    match = re.search(r"\n\.focusMode\s*\{([^}]*)\}", text)
    assert match, "StudioApp.module.css 里找不到 `.focusMode {` 规则块"
    return match.group(1)


def _token(block: str, name: str) -> str:
    match = re.search(rf"--{re.escape(name)}\s*:\s*({_HEX})", block)
    assert match, f"`.focusMode` 里没有定义 --{name} 的十六进制取值"
    return match.group(1).lower()


def _channel(value: int) -> float:
    c = value / 255
    return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4


def _luminance(hex_color: str) -> float:
    h = hex_color.lstrip("#")
    if len(h) == 3:
        h = "".join(ch * 2 for ch in h)
    r, g, b = (int(h[i : i + 2], 16) for i in (0, 2, 4))
    return 0.2126 * _channel(r) + 0.7152 * _channel(g) + 0.0722 * _channel(b)


def _contrast(fg: str, bg: str) -> float:
    a, b = _luminance(fg), _luminance(bg)
    lo, hi = sorted((a, b))
    return (hi + 0.05) / (lo + 0.05)


def test_focus_mode_defines_its_own_paper_and_ink():
    """专注模式的纸色与字色都要自己定义，且纸色不能等于夜间主题的纯黑。"""
    block = _focus_token_block()
    paper = _token(block, "paper")
    ink = _token(block, "ink")
    assert paper != NIGHT_PAPER, "专注模式又用回了夜间纯黑纸面"
    assert ink != "#ffe8ec", "浅粉字色是给黑底用的，配暖白纸会看不见"


def test_focus_paper_and_ink_have_enough_contrast():
    """正文对比度 ≥ 7:1（WCAG AAA 正文级）；次要文字 ≥ 4.5:1。"""
    block = _focus_token_block()
    paper = _token(block, "paper")
    ink = _token(block, "ink")
    ink_soft = _token(block, "ink-soft")
    assert _contrast(ink, paper) >= 7.0, (
        f"正文对比度只有 {_contrast(ink, paper):.2f}:1（{ink} on {paper}）"
    )
    assert _contrast(ink_soft, paper) >= 4.5, (
        f"次要文字对比度只有 {_contrast(ink_soft, paper):.2f}:1"
    )


def test_focus_accent_stays_readable_on_paper():
    """强调色（专注计时条的读数、主按钮）在纸面上也要够对比。"""
    block = _focus_token_block()
    assert _contrast(_token(block, "accent"), _token(block, "paper")) >= 4.5
    assert _contrast(_token(block, "on-accent"), _token(block, "accent")) >= 4.5


def test_focus_shell_paints_the_paper_not_a_transparent_surface():
    """shell 自己要有纸色底：透明的话露出来的是 body 的夜间 `--page-bg`（近黑）。

    全屏时更明显——浏览器给全屏元素铺的是黑色 backdrop，元素透明就等于一片黑，
    而作者看到的解释会是"专注模式还是黑的"。
    """
    block = _focus_token_block()
    assert re.search(r"background\s*:\s*var\(--paper\)", block), (
        "`.focusMode` 自己没铺纸色底（只有编辑器白、周围仍黑）"
    )


def test_focus_editor_and_top_bar_use_the_paper_tokens():
    """编辑器与顶栏走 token，而不是写死颜色（写死就没法跟着纸面走）。"""
    text = APP_CSS.read_text(encoding="utf-8")
    assert re.search(
        r"\.focusMode\s+\.editor,\s*\n\.focusMode\s+\.scriptEditor\s*\{[^}]*background:\s*var\(--paper\)",
        text,
    ), "专注模式的编辑器底色不再走 --paper"
    top = re.search(r"\.focusMode\s+\.top\s*\{([^}]*)\}", text)
    assert top, "找不到 `.focusMode .top` 规则"
    assert re.search(r"background\s*:\s*var\(--paper-deep\)", top.group(1)), (
        "专注模式顶栏要用 paper-deep 实色，不能用半透明 panel 混色（会把正文透上来）"
    )


def test_fullscreen_backdrop_matches_the_paper_token():
    """`::backdrop` 用的是字面量（它不保证继承 token），所以必须与 `--paper` 一致。

    两处颜色一旦分叉，全屏边缘会露出一圈不同色的边——很难查，也很难看。
    """
    text = APP_CSS.read_text(encoding="utf-8")
    backdrop = re.search(r"\.focusMode:fullscreen::backdrop[^{]*\{([^}]*)\}", text)
    assert backdrop, "找不到全屏 backdrop 的纸色规则"
    literal = re.search(_HEX, backdrop.group(1))
    assert literal, "backdrop 规则里没有十六进制色值"
    assert literal.group(0).lower() == _token(_focus_token_block(), "paper"), (
        "backdrop 颜色与 --paper 不一致——全屏边缘会露出一圈异色"
    )


def test_write_aids_are_not_rendered_in_focus_mode():
    """专注模式**不渲染**写作辅助条（不是靠 CSS 藏）。

    用"不渲染"而不是 `display:none`：那样它的 30 秒统计轮询还会继续跑。

    **守卫要守语义，不要守某一种写法。** 第一版把条件写死成 `focusMode ? null`，
    后来一次 UI 重构把它改成 `!focusMode && (…) ?`（语义完全一样：专注时不渲染），
    守卫就红了——红的原因不是行为回归，而是"写法变了"。这类假红最消耗信任：
    下次真回归时，人会先怀疑是守卫过时。所以这里只要求
    **包住 `<WriteAids>` 的那个条件里出现 focusMode 的否定**，
    `focusMode ? null` 与 `!focusMode && …` 都算通过。
    """
    text = APP_TSX.read_text(encoding="utf-8")
    at = text.index("<WriteAids")
    # 往前找最近的 `{`：那应当就是包住这个元素的 JSX 表达式容器起点
    brace = text.rfind("{", 0, at)
    assert brace != -1, "找不到包住 <WriteAids> 的条件表达式"
    guard = text[brace:at]
    assert "focusMode" in guard, (
        "`<WriteAids>` 没有被 focusMode 条件包住——专注模式里它又会出现"
    )
    assert re.search(r"!\s*focusMode|focusMode\s*\?\s*null", guard), (
        f"包住 <WriteAids> 的条件不是 focusMode 的否定：{guard[-160:]!r}"
    )
    # 条件必须真的包住它：中间不能先闭合
    assert ")}" not in guard, "条件表达式在 WriteAids 之前就闭合了，实际没包住"
