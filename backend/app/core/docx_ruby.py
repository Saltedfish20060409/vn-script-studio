"""把带注音的文本写进 Word 段落：优先 **Word 原生注音**（`w:ruby`），关掉时回退 rp。

## 依据

ECMA-376（WordprocessingML）的 `CT_Ruby`：`w:ruby` 依次包含

```xml
<w:ruby>
  <w:rubyPr>            <!-- rubyAlign / hps / hpsRaise / hpsBaseText / lid，顺序固定 -->
  </w:rubyPr>
  <w:rt>…</w:rt>        <!-- 注音，里面是 run -->
  <w:rubyBase>…</w:rubyBase>  <!-- 基准词，里面是 run -->
</w:ruby>
```

`w:rt` 与 `w:rubyBase` 里放的是**run**（`w:r`），不是裸文本——这一点照抄 schema，
不然 Word 会认为文档损坏。

## 为什么此前判"不做"，现在做

旧理由写在 `export_text.project_to_docx` 的注释里："python-docx 不支持、我们也无法验证
Word 能打开"。现在两点都变了：

- XML 直接按 `CT_Ruby` 组装，测试断言**元素、顺序、属性**（结构可验证）；
- 生成的文件会用 python-docx 重新打开（解析失败会抛），所以"整份坏掉"能被测出来。

**仍然无法验证的**（如实写在这里）：Word 客户端渲染的字号比例好不好看——
所以字号都是参数，默认取 Word 常见组合（基准 10pt / 注音 5pt / 抬升 9pt），
并且保留"关掉就回退 rp"的开关。

## 用在哪、不用在哪

- **投稿稿**（`export_submission`）默认开：编辑用 Word 打开时注音是真的注音。
- **阅读导出**（`export_text.project_to_docx`）仍走 rp：原生注音的基础词只存在于
  `w:rubyBase` 里，**简单取文本的工具（含本项目的 docx 导入）会漏掉它**，
  而阅读导出的用途是"把作品读出来/再导回工作台"，保文本完整性更重要。
  （本项目的导入侧已经认得 `w:ruby`，见 `core/file_text.py`；但别的工具不一定。）
"""

from __future__ import annotations

from typing import Any, Dict
from xml.sax.saxutils import escape as _xml_escape

from app.core.ruby_render import RP_CLOSE, RP_OPEN, segments

#: Word 常见组合（半磅值：20 = 10pt）：基准 10pt、注音 5pt、抬升 9pt。
DEFAULT_BASE_HPS = 20
DEFAULT_RUBY_HPS = 10
DEFAULT_RAISE_HPS = 18
#: 注音语言。中文稿子（拼音/中文注音）用 zh-CN；日文用 ja-JP（可传参）。
DEFAULT_LID = "zh-CN"

_RUBY_TEMPLATE = (
    '<w:ruby xmlns:w="http://schemas.openxmlformats.org/wordprocessingml/2006/main">'
    "<w:rubyPr>"
    '<w:rubyAlign w:val="distributeSpace"/>'
    '<w:hps w:val="{ruby_hps}"/>'
    '<w:hpsRaise w:val="{raise_hps}"/>'
    '<w:hpsBaseText w:val="{base_hps}"/>'
    '<w:lid w:val="{lid}"/>'
    "</w:rubyPr>"
    "<w:rt><w:r><w:rPr><w:sz w:val=\"{ruby_hps}\"/><w:szCs w:val=\"{ruby_hps}\"/></w:rPr>"
    '<w:t xml:space="preserve">{reading}</w:t></w:r></w:rt>'
    "<w:rubyBase><w:r><w:rPr><w:sz w:val=\"{base_hps}\"/><w:szCs w:val=\"{base_hps}\"/></w:rPr>"
    '<w:t xml:space="preserve">{base}</w:t></w:r></w:rubyBase>'
    "</w:ruby>"
)


def ruby_xml(
    base: str,
    reading: str,
    *,
    base_hps: int = DEFAULT_BASE_HPS,
    ruby_hps: int = DEFAULT_RUBY_HPS,
    raise_hps: int = DEFAULT_RAISE_HPS,
    lid: str = DEFAULT_LID,
) -> str:
    """组装一个 `w:ruby` 元素的 XML 字符串（纯函数，便于测试结构）。"""
    return _RUBY_TEMPLATE.format(
        base=_xml_escape(base),
        reading=_xml_escape(reading),
        base_hps=int(base_hps),
        ruby_hps=int(ruby_hps),
        raise_hps=int(raise_hps),
        lid=_xml_escape(lid, {'"': "&quot;"}),
    )


def add_text(
    paragraph: Any,
    text: str,
    *,
    native: bool = True,
    **sizes: Any,
) -> None:
    """把一段文本写进段落：注音段用原生 `w:ruby`（`native=True`）或 rp 回退。

    顺序必须保持：python-docx 的 `add_run` 与直接 append 的元素都追加在段落末尾，
    所以按 `segments()` 的顺序写就不会错位。
    """
    if not text:
        return
    if not native:
        paragraph.add_run(_rp_fallback(text))
        return

    from docx.oxml.parser import parse_xml

    for kind, first, second in segments(text):
        if kind == "ruby":
            paragraph._p.append(parse_xml(ruby_xml(first, second, **sizes)))  # noqa: SLF001
        else:
            paragraph.add_run(first)


def _rp_fallback(text: str) -> str:
    """关掉原生注音时的回退形态（等价于 `<rp>`）：`漢字（かんじ）`。"""
    from app.core.ruby_render import render_ruby

    return render_ruby(text, "rp")


def describe_sizes() -> Dict[str, int]:
    """当前默认字号（半磅值），给测试与文档引用同一份数字。"""
    return {
        "baseHps": DEFAULT_BASE_HPS,
        "rubyHps": DEFAULT_RUBY_HPS,
        "raiseHps": DEFAULT_RAISE_HPS,
    }


__all__ = [
    "DEFAULT_BASE_HPS",
    "DEFAULT_LID",
    "DEFAULT_RAISE_HPS",
    "DEFAULT_RUBY_HPS",
    "RP_CLOSE",
    "RP_OPEN",
    "add_text",
    "describe_sizes",
    "ruby_xml",
]
