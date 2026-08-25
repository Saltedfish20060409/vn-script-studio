"""Shared OpenAI-compatible chat/completions client with retry + backoff."""
from __future__ import annotations

import asyncio
import json
import random
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from app.core.ai import DeepSeekConfig
from app.llm_models import DEFAULT_LLM_MODEL, resolve_chat_model

# Retry these transient upstream statuses
_RETRY_STATUSES = {408, 429, 500, 502, 503, 504}

# Stream 重连只覆盖这些状态（无 Retry-After 时等 1s，最多重试 1 次）
_STREAM_RETRY_STATUSES = {429, 500, 502, 503, 504}

# 进程内并发闸：限制同时进行的上游 LLM 请求数（共享服务器 key 防打爆）。
_LLM_SEMAPHORE = asyncio.Semaphore(16)


class _StreamUpstreamError(Exception):
    """Carry upstream status/body/headers so the generator can decide retry."""

    def __init__(self, status: int, body: str, headers) -> None:
        super().__init__(f"status {status}: {body[:200]}")
        self.status = status
        self.body = body
        self.headers = headers


def _stream_retry_delay(headers) -> Optional[float]:
    """Retry-After 秒数（封顶 5s）；无则 None（由调用方用默认 1s）。"""
    ra = headers.get("Retry-After") if headers is not None else None
    if ra and ra.isdigit():
        return min(5.0, float(ra))
    return None


async def chat_completions(
    config: DeepSeekConfig,
    *,
    messages: List[Dict[str, str]],
    temperature: float = 0.7,
    response_format: Optional[Dict[str, Any]] = None,
    max_tokens: Optional[int] = None,
    timeout: float = 120.0,
    max_retries: int = 3,
    stream: bool = False,
) -> httpx.Response:
    """
    POST /v1/chat/completions with exponential backoff on 429/5xx.
    Returns the successful Response (caller parses JSON).
    """
    if not config.apiKey or "your-key" in config.apiKey:
        raise RuntimeError("请先配置 DEEPSEEK_API_KEY")
    base_url = (config.baseUrl or "https://api.deepseek.com").rstrip("/")
    model, body = _chat_body(
        config,
        messages=messages,
        temperature=temperature,
        response_format=response_format,
        max_tokens=max_tokens,
        stream=stream,
    )
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config.apiKey}",
    }

    last_exc: Optional[Exception] = None
    async with _LLM_SEMAPHORE:
        async with httpx.AsyncClient(timeout=timeout) as client:
            for attempt in range(max(1, max_retries)):
                try:
                    res = await client.post(
                        f"{base_url}/v1/chat/completions",
                        headers=headers,
                        json=body,
                    )
                except (httpx.TimeoutException, httpx.TransportError) as exc:
                    last_exc = exc
                    if attempt + 1 >= max_retries:
                        raise RuntimeError(f"LLM 网络失败：{exc}") from exc
                    await asyncio.sleep(_backoff_seconds(attempt))
                    continue

                if res.status_code < 400:
                    # Best-effort per-user usage accounting (fire-and-forget).
                    try:
                        from app.core.usage import current_usage_user, record_usage_later

                        uid = current_usage_user()
                        if uid:
                            record_usage_later(
                                user_id=uid,
                                kind="llm",
                                model=model,
                                usage=usage_from_response(res),
                            )
                    except Exception:  # noqa: BLE001 - accounting never breaks calls
                        pass
                    return res

                if res.status_code in _RETRY_STATUSES and attempt + 1 < max_retries:
                    # Honor Retry-After when present
                    ra = res.headers.get("Retry-After")
                    if ra and ra.isdigit():
                        delay = min(30.0, float(ra))
                    else:
                        delay = _backoff_seconds(attempt)
                    await asyncio.sleep(delay)
                    continue

                raise RuntimeError(
                    f"DeepSeek API {res.status_code}: {res.text[:400]}"
                )

    if last_exc:
        raise RuntimeError(f"LLM 网络失败：{last_exc}") from last_exc
    raise RuntimeError("LLM 请求失败")


def _chat_body(
    config: DeepSeekConfig,
    *,
    messages: List[Dict[str, str]],
    temperature: float,
    response_format: Optional[Dict[str, Any]],
    max_tokens: Optional[int],
    stream: bool,
) -> tuple[str, Dict[str, Any]]:
    model, thinking = resolve_chat_model(config.model or DEFAULT_LLM_MODEL)
    body: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": stream,
    }
    if thinking:
        body["thinking"] = {"type": thinking}
    if response_format is not None:
        body["response_format"] = response_format
    if max_tokens:
        body["max_tokens"] = max_tokens
    return model, body


def _backoff_seconds(attempt: int) -> float:
    # 0.6, 1.2, 2.4 … + jitter
    base = 0.6 * (2**attempt)
    return min(20.0, base + random.uniform(0, 0.35))


async def stream_chat_completions(
    config: DeepSeekConfig,
    *,
    messages: List[Dict[str, str]],
    temperature: float = 0.7,
    response_format: Optional[Dict[str, Any]] = None,
    max_tokens: Optional[int] = None,
    timeout: float = 180.0,
) -> AsyncIterator[str]:
    """Stream an OpenAI-compatible chat completion; yields text deltas.

    Errors surface as RuntimeError (raised from the generator). Caller is
    responsible for accumulating the full text.
    """
    if not config.apiKey or "your-key" in config.apiKey:
        raise RuntimeError("请先配置 DEEPSEEK_API_KEY")
    base_url = (config.baseUrl or "https://api.deepseek.com").rstrip("/")
    _model, body = _chat_body(
        config,
        messages=messages,
        temperature=temperature,
        response_format=response_format,
        max_tokens=max_tokens,
        stream=True,
    )
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config.apiKey}",
    }

    received_any = False
    attempts = 0

    async def _stream_once() -> AsyncIterator[str]:
        nonlocal received_any
        async with _LLM_SEMAPHORE:
            async with httpx.AsyncClient(timeout=timeout) as client:
                async with client.stream(
                    "POST", f"{base_url}/v1/chat/completions", headers=headers, json=body
                ) as res:
                    if res.status_code >= 400:
                        err = (await res.aread()).decode("utf-8", "replace")
                        raise _StreamUpstreamError(res.status_code, err, res.headers)
                    async for line in res.aiter_lines():
                        if not line or not line.startswith("data:"):
                            continue
                        payload = line[5:].strip()
                        if not payload or payload == "[DONE]":
                            continue
                        try:
                            data = json.loads(payload)
                        except json.JSONDecodeError:
                            continue
                        choices = data.get("choices") or []
                        if not choices:
                            continue
                        delta = ((choices[0] or {}).get("delta") or {}).get("content")
                        if delta:
                            received_any = True
                            yield str(delta)

    # 最多重连 1 次：仅当 429/5xx 且尚未产出任何内容增量时，等
    # Retry-After（封顶 5s）或 1s 后重试；与 chat_completions 的
    # 重试语义对齐（此前流式接口对 429/5xx 直接抛错，不对称）。
    while True:
        try:
            async for delta in _stream_once():
                yield delta
            return
        except _StreamUpstreamError as exc:
            if (
                attempts >= 1
                or received_any
                or exc.status not in _STREAM_RETRY_STATUSES
            ):
                raise RuntimeError(
                    f"DeepSeek API {exc.status}: {exc.body[:400]}"
                ) from exc
            attempts += 1
            delay = _stream_retry_delay(exc.headers)
            if delay is None:
                delay = 1.0
            await asyncio.sleep(delay)


def content_from_response(res: httpx.Response) -> tuple[str, str]:
    """Return (content, model)."""
    data = res.json()
    choices = data.get("choices") or []
    content = ""
    if choices:
        content = ((choices[0] or {}).get("message") or {}).get("content", "") or ""
        content = content.strip()
    model = data.get("model") or ""
    return content, model


def usage_from_response(res: httpx.Response) -> Dict[str, int]:
    data = res.json()
    usage = data.get("usage") or {}
    return {
        "prompt": int(usage.get("prompt_tokens") or 0),
        "completion": int(usage.get("completion_tokens") or 0),
        "total": int(usage.get("total_tokens") or 0),
    }
