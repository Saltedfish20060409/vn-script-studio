"""P2: LlmProvider wraps llm_http."""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import httpx

from app.core.ai import DeepSeekConfig
from app.core.llm_provider import DeepSeekProvider, provider_from_config


def test_provider_from_config_is_deepseek():
    cfg = DeepSeekConfig(apiKey="sk-x", baseUrl="https://api.example.com", model="m")
    p = provider_from_config(cfg)
    assert isinstance(p, DeepSeekProvider)


def test_deepseek_provider_delegates():
    cfg = DeepSeekConfig(apiKey="sk-x", baseUrl="https://api.example.com", model="m")
    provider = DeepSeekProvider(cfg)
    ok = httpx.Response(
        200,
        json={"choices": [{"message": {"content": "hi"}}]},
        request=httpx.Request("POST", "https://api.example.com/v1/chat/completions"),
    )

    async def _run():
        with patch(
            "app.core.llm_provider.llm_http.chat_completions",
            new_callable=AsyncMock,
            return_value=ok,
        ) as mocked:
            res = await provider.chat_completions(
                messages=[{"role": "user", "content": "x"}],
                temperature=0.1,
            )
            assert res.status_code == 200
            mocked.assert_awaited_once()

    asyncio.run(_run())
