"""Unit tests: author style memory (LLM mocked)."""

from __future__ import annotations

import asyncio
import json
from unittest.mock import AsyncMock, patch

import httpx

from app.core.agent_context import build_agent_context
from app.core.ai import DeepSeekConfig
from app.core.demo import create_demo_project
from app.core.style_memory import _build_messages, _parse, learn_style_memory


def _cfg(**kw) -> DeepSeekConfig:
    return DeepSeekConfig(apiKey="sk-test-not-real", model="mock", **kw)


def _response(payload: dict) -> httpx.Response:
    content = json.dumps(payload, ensure_ascii=False)
    return httpx.Response(
        200,
        json={"choices": [{"message": {"content": content}}], "model": "mock"},
    )


def test_messages_shape():
    p = create_demo_project()
    msgs = _build_messages(p)
    assert len(msgs) == 2
    assert "风格" in msgs[0]["content"]
    user = json.loads(msgs[1]["content"])
    assert user["chapters"], "demo project must have chapter text"


def test_parse_valid():
    result = _parse(
        json.dumps(
            {
                "guide": "你习惯短句与白描，避免『仿佛』等套话；对白多用省略号制造停顿。",
                "samples": ["雨停的时候，站台已经没人了。", "她顿了顿，没接话。"],
            },
            ensure_ascii=False,
        )
    )
    assert "短句" in result.guide
    assert len(result.samples) == 2
    assert result.error is None


def test_parse_rejects_missing_guide():
    try:
        _parse(json.dumps({"samples": []}))
        assert False, "expected ValueError"
    except ValueError:
        pass


def test_learn_missing_key_returns_error():
    p = create_demo_project()
    result = asyncio.run(learn_style_memory(DeepSeekConfig(apiKey=""), p))
    assert result.error and "DEEPSEEK_API_KEY" in result.error


def test_learn_empty_project_returns_error():
    p = create_demo_project()
    p.chapters = []
    result = asyncio.run(learn_style_memory(_cfg(), p))
    assert result.error and "章节" in result.error


def test_learn_happy_path():
    p = create_demo_project()
    payload = {
        "guide": "你习惯白描短句；对白口语化，多用语气词。",
        "samples": ["她笑了笑，没说话。"],
    }

    async def _run():
        with patch(
            "app.core.style_memory.chat_completions",
            new_callable=AsyncMock,
            return_value=_response(payload),
        ) as mocked:
            result = await learn_style_memory(_cfg(), p)
            mocked.assert_awaited_once()
            return result

    result = asyncio.run(_run())
    assert result.error is None
    assert "白描" in result.guide
    assert result.samples == ["她笑了笑，没说话。"]


def test_learn_upstream_failure_degrades():
    p = create_demo_project()

    async def _run():
        with patch(
            "app.core.style_memory.chat_completions",
            new_callable=AsyncMock,
            side_effect=RuntimeError("upstream down"),
        ):
            return await learn_style_memory(_cfg(), p)

    result = asyncio.run(_run())
    assert result.error is not None
    assert result.guide == ""


def test_agent_context_injects_style_memory():
    p = create_demo_project()
    p.styleMemory = {"guide": "你习惯短句；避免套话。"}
    ctx = build_agent_context(p, userMessage="继续写下一段", task="continue")
    assert "文风记忆" in ctx.included
    assert "你习惯短句" in ctx.text


def test_agent_context_without_style_memory():
    p = create_demo_project()
    ctx = build_agent_context(p, userMessage="继续写下一段", task="continue")
    assert "文风记忆" not in ctx.included
