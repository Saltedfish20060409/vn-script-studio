"""P1: shared LLM HTTP client retry / backoff."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.core.ai import DeepSeekConfig
from app.core.llm_http import _chat_url, chat_completions, content_from_response


def test_chat_url_normalizes_trailing_v1():
    """base_url 带 /v1（用户按厂商文档填写）不得拼成 /v1/v1/chat/completions。"""
    assert (
        _chat_url("https://api.example.com/v1")
        == "https://api.example.com/v1/chat/completions"
    )
    assert (
        _chat_url("https://api.example.com/v1/")
        == "https://api.example.com/v1/chat/completions"
    )
    assert (
        _chat_url("https://api.example.com")
        == "https://api.example.com/v1/chat/completions"
    )
    assert (
        _chat_url("https://dashscope.aliyuncs.com/compatible-mode/v1")
        == "https://dashscope.aliyuncs.com/compatible-mode/v1/chat/completions"
    )
    # 非 /v1 结尾的厂商路径（如智谱 /api/paas/v4）不受影响
    assert (
        _chat_url("https://open.bigmodel.cn/api/paas/v4")
        == "https://open.bigmodel.cn/api/paas/v4/v1/chat/completions"
    )


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


def test_stream_chat_completions_yields_deltas():
    from app.core.llm_http import stream_chat_completions

    sse_body = (
        'data: {"choices":[{"delta":{"content":"你"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"好"}}]}\n\n'
        "data: [DONE]\n\n"
    )

    # httpx stream: mock the async iterator of lines via a fake stream response.
    class _FakeStream:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        @property
        def status_code(self):
            return 200

        async def aiter_lines(self):
            for line in sse_body.splitlines():
                yield line

    mock_client = MagicMock()
    mock_client.stream = MagicMock(return_value=_FakeStream())
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    async def _run():
        with patch("app.core.llm_http.httpx.AsyncClient", return_value=mock_client):
            chunks = []
            async for delta in stream_chat_completions(
                _cfg(),
                messages=[{"role": "user", "content": "hi"}],
            ):
                chunks.append(delta)
        return chunks

    chunks = asyncio.run(_run())
    assert "".join(chunks) == "你好"


def test_stream_chat_completions_skips_non_content_events():
    from app.core.llm_http import stream_chat_completions

    sse_body = (
        'data: {"choices":[{"delta":{"role":"assistant"}}]}\n\n'
        'data: {"choices":[{"delta":{"content":"A"}}]}\n\n'
        'data: {"choices":[{"delta":{}}]}\n\n'
        "data: [DONE]\n\n"
    )

    class _FakeStream:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        @property
        def status_code(self):
            return 200

        async def aiter_lines(self):
            for line in sse_body.splitlines():
                yield line

    mock_client = MagicMock()
    mock_client.stream = MagicMock(return_value=_FakeStream())
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    async def _run():
        with patch("app.core.llm_http.httpx.AsyncClient", return_value=mock_client):
            return [
                d
                async for d in stream_chat_completions(
                    _cfg(),
                    messages=[{"role": "user", "content": "hi"}],
                )
            ]

    chunks = asyncio.run(_run())
    assert "".join(chunks) == "A"


def test_v4_flash_sends_thinking_disabled():
    posts = AsyncMock(return_value=_ok_response())
    mock_client = MagicMock()
    mock_client.post = posts
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    async def _run():
        with patch("app.core.llm_http.httpx.AsyncClient", return_value=mock_client):
            await chat_completions(
                DeepSeekConfig(
                    apiKey="sk-test",
                    baseUrl="https://api.deepseek.com",
                    model="deepseek-v4-flash",
                ),
                messages=[{"role": "user", "content": "hi"}],
            )

    asyncio.run(_run())
    body = posts.await_args.kwargs["json"]
    assert body["model"] == "deepseek-v4-flash"
    assert body["thinking"] == {"type": "disabled"}


def test_legacy_reasoner_rewrites_to_flash_thinking():
    posts = AsyncMock(return_value=_ok_response())
    mock_client = MagicMock()
    mock_client.post = posts
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    async def _run():
        with patch("app.core.llm_http.httpx.AsyncClient", return_value=mock_client):
            await chat_completions(
                DeepSeekConfig(
                    apiKey="sk-test",
                    baseUrl="https://api.deepseek.com",
                    model="deepseek-reasoner",
                ),
                messages=[{"role": "user", "content": "hi"}],
            )

    asyncio.run(_run())
    body = posts.await_args.kwargs["json"]
    assert body["model"] == "deepseek-v4-flash"
    assert body["thinking"] == {"type": "enabled"}


def test_non_deepseek_omits_thinking_field():
    posts = AsyncMock(return_value=_ok_response())
    mock_client = MagicMock()
    mock_client.post = posts
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    async def _run():
        with patch("app.core.llm_http.httpx.AsyncClient", return_value=mock_client):
            await chat_completions(
                DeepSeekConfig(
                    apiKey="sk-test",
                    baseUrl="https://api.moonshot.cn",
                    model="kimi-k2.6",
                ),
                messages=[{"role": "user", "content": "hi"}],
            )

    asyncio.run(_run())
    body = posts.await_args.kwargs["json"]
    assert body["model"] == "kimi-k2.6"
    assert "thinking" not in body
