"""Unit tests: cross-chapter consistency audit.

All LLM calls are mocked — no network, no real key. Covers message shape,
issue parsing/sorting/dedup, graceful degradation on missing key, and the
happy path returning a structured report.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import httpx

from app.core.ai import DeepSeekConfig
from app.core.consistency_audit import (
    _build_messages,
    _parse_issues,
    run_consistency_audit,
)
from app.core.demo import create_demo_project


def _cfg(**kw) -> DeepSeekConfig:
    return DeepSeekConfig(apiKey="sk-test-not-real", model="mock", **kw)


def _response(payload: dict) -> httpx.Response:
    content = json.dumps(payload, ensure_ascii=False)
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": content}}], "model": "mock"},
    )


def test_messages_contain_authority_and_chapters():
    p = create_demo_project()
    msgs = _build_messages(p, focus="检查时间线")
    assert len(msgs) == 2
    assert msgs[0]["role"] == "system"
    assert "一致性" in msgs[0]["content"]
    user = json.loads(msgs[1]["content"])
    assert user["focus"] == "检查时间线"
    assert isinstance(user["authority"]["characters"], list)
    assert isinstance(user["authority"]["locations"], list)
    assert isinstance(user["authority"]["timeline"], list)
    assert isinstance(user["chapters"], list)
    assert user["chapters"], "demo project must have chapter text"
    first = user["chapters"][0]
    assert first["id"] and first["text"]


def test_parse_issues_sorts_and_dedups():
    data = {
        "issues": [
            {
                "category": "character",
                "severity": "medium",
                "chapterIds": ["c1"],
                "quote": "林夏的头发是黑色",
                "description": "第三章写她金发",
                "suggestion": "统一为黑发",
            },
            {
                "category": "timeline",
                "severity": "high",
                "chapterIds": ["c2", "c3"],
                "quote": "昨天才到站",
                "description": "两天前就到站了",
                "suggestion": "改为两天前",
            },
            # duplicate of the first (same category/severity/quote/description)
            {
                "category": "character",
                "severity": "medium",
                "chapterIds": ["c1"],
                "quote": "林夏的头发是黑色",
                "description": "第三章写她金发",
                "suggestion": "统一为黑发",
            },
            # no description → dropped
            {"category": "plot", "severity": "low", "quote": "x", "description": ""},
            # invalid severity → normalized to medium
            {
                "category": "style",
                "severity": "urgent",
                "chapterIds": [],
                "quote": "y",
                "description": "署名不一致",
            },
        ]
    }
    issues = _parse_issues(data)
    assert len(issues) == 3
    # severity order: high first
    assert issues[0].severity == "high"
    assert issues[0].chapterIds == ["c2", "c3"]
    assert issues[1].severity == "medium"  # character first (sorted by category)
    assert issues[2].severity == "medium"  # invalid severity normalized
    assert issues[2].category == "style"


def test_parse_issues_rejects_non_list():
    try:
        _parse_issues({"issues": "oops"})
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_missing_key_returns_error_without_calling_llm():
    p = create_demo_project()
    result = asyncio.run(run_consistency_audit(DeepSeekConfig(apiKey=""), p))
    assert result.error and "DEEPSEEK_API_KEY" in result.error
    assert result.issues == []


def test_happy_path_returns_report():
    p = create_demo_project()
    payload = {
        "summary": "整体一致，但存在两处角色设定冲突。",
        "issues": [
            {
                "category": "character",
                "severity": "high",
                "chapterIds": [p.chapters[0].id],
                "quote": "原文证据",
                "description": "角色名字前后不一致",
                "suggestion": "统一使用 defineName",
            }
        ],
    }

    async def _run():
        with patch(
            "app.core.consistency_audit.chat_completions",
            new_callable=AsyncMock,
            return_value=_response(payload),
        ) as mocked:
            result = await run_consistency_audit(_cfg(), p, focus="名字")
            mocked.assert_awaited_once()
            return result

    result = asyncio.run(_run())
    assert result.error is None
    assert result.summary == "整体一致，但存在两处角色设定冲突。"
    assert len(result.issues) == 1
    issue = result.issues[0]
    assert issue.category == "character"
    assert issue.severity == "high"
    assert issue.chapterIds == [p.chapters[0].id]
    assert issue.suggestion


def test_malformed_llm_output_degrades_gracefully():
    p = create_demo_project()

    async def _run():
        with patch(
            "app.core.consistency_audit.chat_completions",
            new_callable=AsyncMock,
            return_value=_response({"issues": "not-a-list"}),
        ):
            return await run_consistency_audit(_cfg(), p)

    result = asyncio.run(_run())
    assert result.error is not None
    assert result.issues == []
