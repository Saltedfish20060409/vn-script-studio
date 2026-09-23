"""Agent 工具 `polish_prose`：原 `/harness/run` 的"编辑润色"能力搬到 Agent 里。

为什么要有这个测试：删掉 `/harness/run` 的前提是**能力不丢**——它必须真的能被 Agent 用到，
而且"体检全过就不调模型"这条省钱性质必须还在（否则每次润色都会白烧一次调用）。
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

from app.core import agent_tools
from app.core.agent_tools import (
    ASYNC_TOOL_NAMES,
    run_agent_tool,
    run_agent_tool_async,
    tool_catalog_for_prompt,
)
from app.core.project import normalize_project

CFG = object()  # 占位：真正的 harness_editor_pass 被 mock，不需要真配置


def _project():
    return normalize_project(
        {
            "id": "p1",
            "title": "测试",
            "chapters": [
                {
                    "id": "c1",
                    "title": "第一章",
                    "blocks": [
                        {"type": "narration", "text": "雨夜的车站，她抬头看了看天。"},
                        {"type": "dialogue", "characterId": "ch1", "text": "「你等很久了？」"},
                    ],
                }
            ],
            "characters": [
                {"id": "ch1", "name": "林夏", "defineName": "linxia", "displayName": "林夏"}
            ],
        }
    )


def test_spec_is_registered_and_in_prompt_catalog():
    names = [s["name"] for s in agent_tools.TOOL_SPECS]
    assert "polish_prose" in names
    assert "polish_prose" in ASYNC_TOOL_NAMES
    # 目录是拼给模型看的：模型得知道有这个工具
    assert "polish_prose" in tool_catalog_for_prompt()


def test_sync_dispatcher_points_to_the_async_channel():
    """"异步工具"不能伪装成"未知工具"——否则模型会以为没有这个能力。"""
    ok, msg = run_agent_tool("polish_prose", {}, project=_project())
    assert ok is False
    assert "异步" in msg


def test_polish_returns_rewritten_text_and_notes():
    fake = {
        "issues": [{"severity": "warn", "code": "x", "message": "第二段有 AI 腔"}],
        "content": "雨夜的车站，她抬头看了看天。",
        "role": "editor",
        "model": "m",
        "skippedLlm": False,
        "flavor": "prose",
    }
    with patch(
        "app.core.harness.pipeline.harness_editor_pass", new=AsyncMock(return_value=fake)
    ) as fn:
        ok, preview = asyncio.run(
            run_agent_tool_async(
                "polish_prose",
                {"text": "雨夜车站。她看了看天。", "flavor": "prose"},
                project=_project(),
                config=CFG,
            )
        )
    assert ok is True
    assert "雨夜的车站" in preview  # 改写后的正文
    assert "AI 腔" in preview  # 仍须注意的点
    assert "prose" in preview  # 口径写在里面，便于复核
    # flavor 必须真的透传下去（否则小说稿会被按剧本口径改写）
    assert fn.await_args.kwargs.get("flavor") == "prose"


def test_clean_draft_skips_the_model():
    """确定性体检全过时不该调模型——这是这个工具省钱的关键。"""
    fake = {
        "issues": [],
        "content": "",
        "role": "editor",
        "skippedLlm": True,
        "message": "确定性体检通过，无需责编改写",
    }
    with patch(
        "app.core.harness.pipeline.harness_editor_pass", new=AsyncMock(return_value=fake)
    ):
        ok, preview = asyncio.run(
            run_agent_tool_async(
                "polish_prose", {"text": "干净的稿子。"}, project=_project(), config=CFG
            )
        )
    assert ok is True
    assert "未调用模型" in preview


def test_chapter_fallback_when_text_missing():
    """不传 text 时取当前章（Agent 常常只说"润色这一章"）。"""
    fake = {"issues": [], "content": "改写结果", "skippedLlm": False, "flavor": "prose"}
    with patch(
        "app.core.harness.pipeline.harness_editor_pass", new=AsyncMock(return_value=fake)
    ) as fn:
        ok, preview = asyncio.run(
            run_agent_tool_async(
                "polish_prose", {}, project=_project(), chapter_id="c1", config=CFG
            )
        )
    assert ok is True
    assert "改写结果" in preview
    # 传下去的应当是这一章的正文（含对白），而不是空字符串
    passed_text = fn.await_args.args[1]
    assert "雨夜的车站" in passed_text


def test_missing_config_is_reported_not_crashed():
    ok, msg = asyncio.run(
        run_agent_tool_async("polish_prose", {"text": "x"}, project=_project(), config=None)
    )
    assert ok is False
    assert "模型" in msg


def test_project_without_real_prose_is_reported():
    """空工程会**自动补一章**，而那一章的内容只是 `[label start]` 结构标记。

    不判这一条的话，工具会拿着结构标记去"润色"、体检还通过——作者会以为工具坏了。
    这里断言的是"能识别出那不是正文"。
    """
    empty = normalize_project({"id": "p2", "title": "空工程", "chapters": [], "characters": []})
    ok, msg = asyncio.run(
        run_agent_tool_async("polish_prose", {}, project=empty, config=CFG)
    )
    assert ok is False
    assert "结构标记" in msg or "没有正文" in msg


def test_chapter_without_text_is_reported():
    """章节存在但没有正文（还没写）时，也要给出可读的原因。"""
    blank = normalize_project(
        {
            "id": "p3",
            "title": "空章",
            "chapters": [{"id": "c9", "title": "第一章", "blocks": []}],
            "characters": [],
        }
    )
    ok, msg = asyncio.run(
        run_agent_tool_async("polish_prose", {}, project=blank, chapter_id="c9", config=CFG)
    )
    assert ok is False
    assert "没有正文" in msg


def test_unknown_async_tool_is_rejected():
    ok, msg = asyncio.run(
        run_agent_tool_async("nope", {}, project=_project(), config=CFG)
    )
    assert ok is False
    assert "未知" in msg
