"""P1: shared LLM HTTP client retry / backoff."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.core.ai import DeepSeekConfig
from app.core.llm_http import chat_completions, content_from_response


def _cfg() -> DeepSeekConfig:
    return DeepSeekConfig(
        apiKey="sk-test",
        baseUrl="https://api.example.com",
        model="test-model",
    )


def _ok_response(content: str = "hello") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": "test-model",
            "choices": [{"message": {"content": content}}],
            "usage": {"prompt_tokens": 1, "completion_tokens": 2, "total_tokens": 3},
        },
        request=httpx.Request("POST", "https://api.example.com/v1/chat/completions"),
    )


def _status_response(code: int) -> httpx.Response:
    return httpx.Response(
        code,
        text=f"err {code}",
        request=httpx.Request("POST", "https://api.example.com/v1/chat/completions"),
    )


def test_chat_completions_retries_429_then_ok():
    posts = AsyncMock(side_effect=[_status_response(429), _ok_response("ok")])

    mock_client = MagicMock()
    mock_client.post = posts
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    async def _run():
        with patch("app.core.llm_http.httpx.AsyncClient", return_value=mock_client):
            with patch("app.core.llm_http.asyncio.sleep", new_callable=AsyncMock):
                res = await chat_completions(
                    _cfg(),
                    messages=[{"role": "user", "content": "hi"}],
                    max_retries=3,
                )
        return res

    res = asyncio.run(_run())
    assert res.status_code == 200
    assert posts.await_count == 2
    text, model = content_from_response(res)
    assert text == "ok"
    assert model == "test-model"


def test_chat_completions_gives_up_on_400():
    posts = AsyncMock(return_value=_status_response(400))
    mock_client = MagicMock()
    mock_client.post = posts
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    async def _run():
        with patch("app.core.llm_http.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(RuntimeError, match="400"):
                await chat_completions(
                    _cfg(),
                    messages=[{"role": "user", "content": "hi"}],
                    max_retries=3,
                )

    asyncio.run(_run())
    assert posts.await_count == 1


def test_chat_completions_requires_api_key():
    async def _run():
        with pytest.raises(RuntimeError, match="API_KEY"):
            await chat_completions(
                DeepSeekConfig(apiKey="", baseUrl="", model=""),
                messages=[{"role": "user", "content": "hi"}],
            )

    asyncio.run(_run())
