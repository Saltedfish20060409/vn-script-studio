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
    # 非 /v1 结尾的厂商路径（如智谱 /api/paas/v4）同样不得拼 /v1（曾拼出 /v4/v1 → 404）
    assert (
        _chat_url("https://open.bigmodel.cn/api/paas/v4")
        == "https://open.bigmodel.cn/api/paas/v4/chat/completions"
    )
    # 已是完整端点时原样使用
    assert (
        _chat_url("https://open.bigmodel.cn/api/paas/v4/chat/completions")
        == "https://open.bigmodel.cn/api/paas/v4/chat/completions"
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
    """官方兼容名 deepseek-v4-flash 出站后落到 V4.1 正式名 deepseek-flash。"""
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
    assert body["model"] == "deepseek-flash"
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
    assert body["model"] == "deepseek-flash"
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


def _post_body_for(model: str, **kwargs):  # noqa: ANN003, ANN202
    """发一次请求，返回出站 body（用假 httpx 客户端拦下来）。"""
    posts = AsyncMock(return_value=_ok_response())
    mock_client = MagicMock()
    mock_client.post = posts
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    async def _run():
        with patch("app.core.llm_http.httpx.AsyncClient", return_value=mock_client):
            await chat_completions(
                DeepSeekConfig(apiKey="sk-test", baseUrl="https://x.example", model=model),
                messages=[{"role": "user", "content": "hi"}],
                **kwargs,
            )

    asyncio.run(_run())
    return posts.await_args.kwargs["json"]


JSON_FMT = {"type": "json_object"}


def test_json_mode_sent_for_supporting_model():
    """支持结构化输出的档位照旧带上 response_format。"""
    body = _post_body_for("deepseek-flash", response_format=JSON_FMT)
    assert body["response_format"] == JSON_FMT


def test_json_mode_dropped_for_unsupporting_model():
    """不支持 JSON 模式的档位不能硬发 response_format —— 对方会直接报错。

    这曾经是个真问题：预设里的 json_mode 只是一个标记，没有任何代码用它，
    选 Claude / 思考模式时照样把参数发出去。
    """
    for model in ("claude-opus-5", "claude-sonnet-4-8", "qwen3:8b"):
        body = _post_body_for(model, response_format=JSON_FMT)
        assert "response_format" not in body, f"{model} 仍然带了 response_format"


def test_json_mode_dropped_for_think_alias():
    """思考模式的别名会被改写成正式名，只看改写后的名字就会漏判。"""
    body = _post_body_for("deepseek-flash-think", response_format=JSON_FMT)
    assert body["model"] == "deepseek-flash"  # 出站名被改写
    assert body["thinking"] == {"type": "enabled"}
    assert "response_format" not in body


def test_json_mode_kept_for_unknown_model():
    """用户手填没收录的模型时保持原行为（不能擅自把参数拿掉）。"""
    body = _post_body_for("some-vendor-model-9", response_format=JSON_FMT)
    assert body["response_format"] == JSON_FMT


def test_no_response_format_requested_stays_absent():
    body = _post_body_for("deepseek-flash")
    assert "response_format" not in body
