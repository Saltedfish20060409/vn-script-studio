"""Injectable LLM provider — OpenAI-compatible remote (default) + local Ollama."""

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


class OllamaProvider:
    """Local Ollama via its OpenAI-compatible /v1/chat/completions endpoint.

    Same wire protocol as DeepSeekProvider — only defaults differ (base URL
    http://localhost:11434, apiKey ignored). Works offline with local models.
    """

    def __init__(self, config: DeepSeekConfig):
        self.config = config

    async def chat_completions(
        self,
        *,
        messages: List[Dict[str, str]],
        temperature: float = 0.7,
        response_format: Optional[Dict[str, Any]] = None,
        max_tokens: Optional[int] = None,
        timeout: float = 180.0,
        max_retries: int = 2,
        stream: bool = False,
    ) -> httpx.Response:
        cfg = DeepSeekConfig(
            apiKey=self.config.apiKey or "ollama-local",
            baseUrl=self.config.baseUrl or "http://localhost:11434",
            model=self.config.model or "qwen2.5:7b",
            provider="openai",
        )
        return await llm_http.chat_completions(
            cfg,
            messages=messages,
            temperature=temperature,
            response_format=response_format,
            max_tokens=max_tokens,
            timeout=timeout,
            max_retries=max_retries,
            stream=stream,
        )


def provider_from_config(config: DeepSeekConfig) -> LlmProvider:
    base = (config.baseUrl or "").lower()
    explicit = (config.provider or "").lower()
    # Ollama if explicitly requested, or if the base URL points at Ollama's
    # OpenAI-compatible endpoint (localhost:11434). Zero-config for local runs.
    if explicit == "ollama" or ":11434" in base:
        return OllamaProvider(config)
    return DeepSeekProvider(config)
