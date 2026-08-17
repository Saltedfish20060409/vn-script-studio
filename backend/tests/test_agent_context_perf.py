"""Perf regression: build_agent_context converts each chapter's blocks to
plain text at most once (memoized), not once per character scoring pass."""

from __future__ import annotations

from unittest.mock import patch

from app.core.agent_context import build_agent_context
from app.core.demo import create_demo_project


def test_plain_conversion_memoized_per_chapter():
    p = create_demo_project()
    with patch(
        "app.core.agent_context._blocks_to_plain",
        wraps=__import__(
            "app.core.agent_context", fromlist=["_blocks_to_plain"]
        )._blocks_to_plain,
    ) as mocked:
        ctx = build_agent_context(
            p,
            userMessage="继续写下一段雨夜场景",
            task="continue",
            maxChars=12000,
        )
    assert ctx.text
    calls = mocked.call_count
    chapter_count = len(p.chapters)
    # Before memoization this was ~chapters + characters×1 (focus chapter
    # re-converted inside the character scoring loop). Now ≤ chapters.
    assert calls <= chapter_count, (
        f"expected ≤{chapter_count} conversions, got {calls}"
    )


def test_agent_context_includes_focus_chapter():
    p = create_demo_project()
    focus_id = p.chapters[0].id
    ctx = build_agent_context(p, chapterId=focus_id, task="continue")
    assert f"当前章节：{p.chapters[0].title}" in ctx.text
