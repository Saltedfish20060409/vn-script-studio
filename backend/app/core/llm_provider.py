"""Injectable LLM provider — DeepSeek is the default implementation."""
from __future__ import annotations

from typing import Any, Dict, List, Optional, Protocol, runtime_checkable

import httpx

from app.core.ai import DeepSeekConfig
from app.core import llm_http


@runtime_checkable
class LlmProvider(Protocol):
    async def chat_completions(
        self,
        *,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        response_format: Optional[Dict[str, Any]] = None,
        max_tokens: Optional[int] = None,
        timeout: float = 120.0,
        max_retries: int = 3,
        stream: bool = False,
    ) -> httpx.Response: ...


class DeepSeekProvider:
    """Default OpenAI-compatible provider backed by llm_http retry/backoff."""

    def __init__(self, config: DeepSeekConfig):
        self.config = config

    async def chat_completions(
        self,
        *,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        response_format: Optional[Dict[str, Any]] = None,
        max_tokens: Optional[int] = None,
        timeout: float = 120.0,
        max_retries: int = 3,
        stream: bool = False,
    ) -> httpx.Response:
        return await llm_http.chat_completions(
            self.config,
            messages=messages,
            temperature=temperature,
            response_format=response_format,
            max_tokens=max_tokens,
            timeout=timeout,
            max_retries=max_retries,
            stream=stream,
        )


def provider_from_config(config: DeepSeekConfig) -> LlmProvider:
    return DeepSeekProvider(config)
