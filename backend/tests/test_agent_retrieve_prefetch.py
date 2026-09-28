"""预取的"补料"必须补到续写要用的那一段。

症状（代码级，2026-09-27 发现）：上下文被裁时才触发的预取，把取回的材料切进提示词时
只留**前 4000 字**（`agent_retrieve.py` 旧实现）。而 `get_chapter` 内部是头部截断
（`agent_tools._clip` 取前 12000 字），于是这条链路两头都朝"章首"偏——续写最需要的
**章末**恰好被切掉，补料补成了"上下文里本来就有的一段"。

改法：章节类材料（get_chapter / search_script）两头都留（前 2000 + 后 2000，
中间标注省略），其余材料保持头部切片（它们的相关信息集中在最相关的头几条）。
"""
from __future__ import annotations

from types import SimpleNamespace

from app.core.agent_retrieve import (
    PrefetchReport,
    _preview_for_prompt,
    should_prefetch,
)


def _long_preview() -> str:
    return "【章首标记】" + ("雨敲在铁棚上。" * 800) + "【章末标记】" + ("她把伞收了。" * 100)


def test_chapter_material_keeps_both_ends():
    text = _preview_for_prompt("get_chapter", _long_preview())
    assert "【章首标记】" in text
    assert "【章末标记】" in text, "章末被切掉了——续写要用的正是这一段"
    assert "中间省略" in text
    # 注入预算不因为两头留而变大
    assert len(text) <= 4000 + 40


def test_non_chapter_material_keeps_the_old_head_slice():
    """设定/条目检索保持原样：相关条目在最前面，没必要留尾巴。"""
    text = _preview_for_prompt("search_lore", _long_preview())
    assert "【章首标记】" in text
    assert "【章末标记】" not in text
    assert len(text) <= 4000


def test_short_material_is_untouched():
    short = "车站（夜雨）。"
    for tool in ("get_chapter", "search_lore"):
        assert _preview_for_prompt(tool, short) == short
    assert _preview_for_prompt("get_chapter", None) == ""


def test_report_injects_both_ends_for_chapter_prefetch():
    report = PrefetchReport(
        results=[
            {"name": "get_chapter", "ok": True, "preview": _long_preview()},
            {"name": "search_lore", "ok": True, "preview": "设定条目一。"},
        ]
    )
    msgs = report.as_messages()
    assert len(msgs) == 1 and msgs[0]["role"] == "user"
    body = msgs[0]["content"]
    assert "本轮上下文因篇幅裁过" in body
    assert "【章末标记】" in body
    assert "设定条目一。" in body
    # 每条材料各自的预算（4000）+ 分节标题，别整段失控
    assert len(body) <= 4000 * 2 + 400


def test_should_prefetch_only_for_write_tasks_and_when_context_was_cut():
    """预取只在"写任务 + 上下文确实被裁"时触发（这条以前没测试钉住）。"""
    def ctx(**kw):
        return SimpleNamespace(**kw)

    assert should_prefetch("chat", ctx(truncated=True)) is False, "讨论任务不需要补料"
    assert should_prefetch("continue", ctx(truncated=False)) is False, "没被裁就不用补"
    assert should_prefetch("continue", ctx(truncated=True)) is True
    assert (
        should_prefetch(
            "scene",
            ctx(truncated=False, budgetReport={"droppedSections": [{"key": "lore"}]}),
        )
        is True
    )
    assert (
        should_prefetch(
            "rewrite",
            ctx(truncated=False, budgetReport={"trimmedParts": [{"kind": "focus"}]}),
        )
        is True
    )
