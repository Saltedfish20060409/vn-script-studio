"""上下文分块的位置策略（依据 Lost in the Middle, arXiv:2307.03172）。

为什么这件事值得专门测：位置不只是"读起来顺不顺"。

1. 论文的结论：长上下文里模型对**开头与结尾**的信息利用最好，夹在中间的最容易被忽略。
2. 我们自己的裁剪是**保头保尾、压中段**（见 `build_agent_context` 末尾）——
   放在头部的块会被逐字保留，放在中段的块最先被压掉。

两者叠加之后，"哪一段排在哪"直接决定了**哪些事实会被模型看到**。所以这里断言的是结构性
不变量，而不是文案：

- 位置表与代码里的 key 完全一致（漏登记会被排到最后，静默失效）；
- 硬规则在最前（且首尾各出现一次）；
- 角色/关系/设定条目这类"绝不能写错"的块在**头部**（会被原样保留）；
- 参考文档这类"量大但不决定这一步怎么写"的块在**中段**（超预算时被压的就是它）；
- 当前章正文与用户选区在**尾部**（最近优先，紧接硬规则与输出契约）。
"""

from __future__ import annotations

from app.core.agent_context import (
    _SECTION_ORDER,
    build_agent_context,
)
from app.core.project import normalize_project


def _project(*, focus_chars: int = 200):
    """最小作品。参考文档不在作品字段里——`referenceDocs` 是**调用方传进来的字符串**
    （见 api/v1/projects.py 组装 Agent 请求的地方），所以测试直接当 kwarg 传。"""
    return normalize_project(
        {
            "id": "p-order",
            "title": "顺序",
            "logline": "一句话简介",
            "bible": {"world": "沿海小镇，一年有两百天在下雨。", "outline": "1. 相遇\n2. 分别"},
            "characters": [
                {
                    "id": "c1",
                    "displayName": "雨宫澪",
                    "defineName": "mio",
                    "voice": "短句、少形容词",
                    "bio": "转学生",
                }
            ],
            "locations": [{"id": "l1", "name": "失物招领处", "note": "钟楼下面"}],
            "loreEntries": [
                {
                    "id": "e1",
                    "title": "第二次钟声的规矩",
                    "body": "钟声一天只会响两次。",
                    "keywords": ["钟声", "规矩"],
                }
            ],
            "chapters": [
                {
                    "id": "ch1",
                    "title": "第一章",
                    "prose": "雨停了。" * max(1, focus_chars // 4),
                },
                {"id": "ch2", "title": "第二章", "prose": "第二天，他又来了。"},
            ],
        }
    )


def _context(project, **kw):
    """`maxChars` 是这条链路的真实参数名（驼峰），别写成 max_chars。"""
    return build_agent_context(
        project,
        chapterId="ch1",
        userMessage="接着写钟声那一段",
        task=kw.pop("task", "continue"),
        **kw,
    )


#: referenceDocs 块没有自己的小标题（内容是作者上传的原始资料），
#: 所以用内容特征定位它：这块正文里只有我们灌进去的「参」字串。
_REF_DOC_MARK = "参参参参"


# ---- 结构性不变量 --------------------------------------------------------------


def test_section_order_table_covers_exactly_the_sections_in_code():
    """位置表漏登记 = 该块被静默排到最后。这里把两张名单钉在一起。"""
    import pathlib
    import re

    src = pathlib.Path(__file__).resolve().parent.parent / "app" / "core" / "agent_context.py"
    text = src.read_text(encoding="utf-8")
    literal = text.split("keyed_sections: List[Tuple[str, str]] = [", 1)[1].split("\n    ]", 1)[0]
    # 形如 ("meta", ...) 或 (\n            "rules", ...
    keys = set(re.findall(r'\(\s*"([a-zA-Z]+)"', literal)) | set(
        re.findall(r'^\s{12}"([a-zA-Z]+)",', literal, flags=re.MULTILINE)
    )
    assert keys, "没有解析到任何分块 key，源码结构可能变了"
    assert keys == set(_SECTION_ORDER), (
        f"位置表与代码不一致：缺 {sorted(keys - set(_SECTION_ORDER))}，"
        f"多 {sorted(set(_SECTION_ORDER) - keys)}"
    )
    assert len(_SECTION_ORDER) == len(set(_SECTION_ORDER)), "位置表里有重复 key"


def test_hard_rules_come_first_and_are_repeated_at_the_end():
    ctx = _context(_project())
    body = ctx.text
    # 头部：第一条硬规则在前 800 字内（既有约定：先读一遍）
    assert "本次硬规则" in body[:800]
    # 末尾：硬规则再出现一次（长上下文里中间的要求最容易被忽略）
    assert "本次硬规则" in body[-800:]
    assert "输出契约" in body[-800:]


def test_stakes_first_bulk_in_middle_query_last():
    """三段的相对位置：地基 → 参考资料 → 贴着本次请求。"""
    ctx = _context(_project(), referenceDocs=_REF_DOC_MARK + "料" * 3000)
    body = ctx.text
    idx = lambda s: body.index(s)  # noqa: E731 — 测试里可读性优先

    # 头部：身份与"绝不能说错"的事实
    assert idx("## Characters") < idx("## Locations")
    assert idx("## 设定条目") < idx("## 章节目录（含本地摘要）")
    # 中段：参考文档在角色/设定之后、当前章之前
    assert idx("## Characters") < idx(_REF_DOC_MARK)
    assert idx(_REF_DOC_MARK) < idx("## 当前章节")
    # 尾部：当前章正文与输出契约在最后
    assert body.rfind("## 当前章节") > len(body) * 0.5


def test_current_chapter_body_sits_in_the_recency_window():
    """当前章正文必须落在尾部窗口里——模型要"紧接着末尾续写"。"""
    ctx = _context(_project(focus_chars=2000))
    body = ctx.text
    at = body.rfind("## 当前章节")
    assert at > 0
    assert at > len(body) - 2000, "当前章正文被挤出了尾部窗口"


# ---- 与裁剪的交互：这才是位置策略真正的后果 ------------------------------------


def test_big_reference_doc_does_not_squeeze_out_the_high_stakes_blocks():
    """回归：参考文档很大时，角色/关系/设定必须仍在（过去它们在参考文档之后被挤掉）。"""
    project = _project(focus_chars=3000)
    ctx = _context(project, referenceDocs="参" * 40000, maxChars=6000)
    body = ctx.text
    for must in ("## Characters", "## 设定条目", "## 当前章节"):
        assert must in body, f"{must} 被挤掉了：高价值块不该为参考文档让位"


def test_over_budget_context_reports_what_it_did():
    """压了就说压了：作者要能看到这次上下文被怎么处理过。"""
    project = _project(focus_chars=3000)
    ctx = _context(project, referenceDocs="参" * 40000, maxChars=6000)
    assert any("压缩" in item for item in ctx.included), ctx.included
    assert ctx.charsUsed <= 6000 + 200  # 允许压缩标记本身的少量开销


def test_small_project_is_not_compressed_and_keeps_both_ends():
    ctx = _context(_project())
    assert not any("压缩" in item for item in ctx.included), ctx.included
    assert "本次硬规则" in ctx.text[:800]
    assert "输出契约" in ctx.text[-800:]
