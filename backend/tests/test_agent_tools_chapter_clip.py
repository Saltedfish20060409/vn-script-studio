"""章节正文的截断必须**两头都留**（续写要接的是章末那一拍）。

2026-09-28 排查：`get_chapter` 用 `_clip` 只留开头，于是长章永远只给"章首 N 字"，
而续写/写戏要接的是**章末**、审稿也要看收束。`_clip_chapter` 改成两头都留，
短章一个字不改（不要为了统一而破坏"能装下就完整给"的语义）。
"""
from __future__ import annotations

from app.core.agent_tools import _clip, _clip_chapter, run_agent_tool
from app.domain.types import VnProject

HEAD = "【章首】"
TAIL = "【章末】"


def _long_text(n: int = 4000) -> str:
    return HEAD + ("雨敲在铁棚上。" * (n // 7)) + TAIL


def test_short_chapter_is_untouched():
    text = f"{HEAD}雨很大。{TAIL}"
    assert _clip_chapter(text, 12000) == text
    assert _clip_chapter(text, 80) == text  # 上限比正文还小也原样返回（不制造半截话）


def test_long_chapter_keeps_both_ends_and_respects_the_budget():
    text = _long_text()
    out = _clip_chapter(text, 1000)
    assert HEAD in out and TAIL in out, "两头都要在"
    assert "中间省略" in out
    assert len(out) <= 1000 + 40, len(out)
    # 与老的 `_clip` 对比：老写法只有头
    old = _clip(text, 1000)
    assert HEAD in old and TAIL not in old


def test_head_tail_split_is_configurable():
    text = _long_text()
    out = _clip_chapter(text, 1000, head_ratio=0.2)
    assert HEAD in out and TAIL in out
    # 头占比更小时，尾部保留得更长
    assert out.rfind(TAIL) > 0

def test_get_chapter_tool_returns_the_chapter_end():
    """端到端：工具层拿到的必须包含章末（模型据此接续写）。"""
    text = _long_text(3000)
    project = VnProject.model_validate(
        {
            "id": "p",
            "title": "示例",
            "updatedAt": "2026-01-01T00:00:00Z",
            "characters": [{"id": "c1", "defineName": "a", "displayName": "甲", "voice": "惜话"}],
            "chapters": [
                {"id": "ch1", "title": "第一章", "blocks": [{"type": "narration", "text": text}]}
            ],
        }
    )

    def _go():
        return run_agent_tool("get_chapter", {"maxChars": 800}, project=project, chapter_id="ch1")

    ok, out = _go()
    assert ok
    assert HEAD in out and TAIL in out
    assert "第一章" in out
