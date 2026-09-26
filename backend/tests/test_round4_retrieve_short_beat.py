"""第四轮：写路径材料预取 + 短拍续写契约。"""
from __future__ import annotations

from app.core.agent_context import build_agent_context, output_contract, task_key_rules
from app.core.agent_retrieve import (
    plan_write_prefetch,
    run_write_prefetch,
    should_prefetch,
)
from app.core.project import normalize_project


def _long_chapter_project(*, prose_chars: int = 25000, lore_body: str = ""):
    prose = ("雨停了。月台上只剩他自己。" * 200)[:prose_chars]
    lore = lore_body or ("钟声一天只会响两次。" * 80)
    return normalize_project(
        {
            "id": "p-r4",
            "title": "预取",
            "characters": [
                {"id": "c1", "displayName": "澪", "defineName": "mio", "voice": "短句"}
            ],
            "loreEntries": [
                {
                    "id": "e1",
                    "title": "第二次钟声的规矩",
                    "body": lore,
                    "keywords": ["钟声", "规矩"],
                }
            ],
            "chapters": [
                {"id": "ch1", "title": "第一章", "prose": prose},
                {
                    "id": "ch2",
                    "title": "第二章",
                    "prose": "第二天他又来了，听见钟声。" * 40,
                },
            ],
        }
    )


def test_should_prefetch_when_focus_truncated():
    p = _long_chapter_project()
    # 极紧预算：逼出当前章截断
    ctx = build_agent_context(
        p,
        chapterId="ch1",
        userMessage="接着写",
        task="continue",
        maxChars=4000,
    )
    assert should_prefetch("continue", ctx)
    planned = plan_write_prefetch(
        ctx, task="continue", chapter_id="ch1", user_message="接着写"
    )
    names = {c.name for c in planned}
    assert "get_chapter" in names


def test_prefetch_runs_get_chapter_and_returns_messages():
    p = _long_chapter_project()
    ctx = build_agent_context(
        p,
        chapterId="ch1",
        userMessage="接着写钟声",
        task="continue",
        maxChars=3500,
        referenceDocs="参" * 5000,
    )
    report = run_write_prefetch(
        p, ctx, task="continue", chapter_id="ch1", user_message="接着写钟声"
    )
    assert report.calls
    assert report.as_meta()["callCount"] >= 1
    msgs = report.as_messages()
    assert msgs and "系统预取" in msgs[0]["content"]
    assert any(r.get("ok") for r in report.results)


def test_chat_task_does_not_prefetch():
    p = _long_chapter_project()
    ctx = build_agent_context(
        p, chapterId="ch1", userMessage="聊聊设定", task="chat", maxChars=3000
    )
    assert not should_prefetch("chat", ctx)
    assert plan_write_prefetch(ctx, task="chat", chapter_id="ch1") == []


def test_continue_contract_is_short_beat():
    contract = output_contract("continue")
    assert "180" in contract or "450" in contract
    assert "一小段" in contract or "短" in contract
    rules = task_key_rules("continue")
    assert any("一小段" in r or "180" in r for r in rules)


def test_novel_continue_contract_short_beat():
    p = normalize_project(
        {
            "id": "n",
            "title": "n",
            "writingGenre": "novel",
            "chapters": [{"id": "ch1", "title": "一", "prose": "雨。"}],
        }
    )
    contract = output_contract("continue", p)
    assert "180" in contract or "450" in contract
