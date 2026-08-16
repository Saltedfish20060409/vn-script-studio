"""Shared OpenAI-compatible chat/completions client with retry + backoff."""
from __future__ import annotations

import asyncio
import json
import random
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from app.core.ai import DeepSeekConfig

# Retry these transient upstream statuses
_RETRY_STATUSES = {408, 429, 500, 502, 503, 504}


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
    model = config.model or "deepseek-chat"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config.apiKey}",
    }
    body: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": stream,
    }
    if response_format is not None:
        body["response_format"] = response_format
    if max_tokens:
        body["max_tokens"] = max_tokens

    last_exc: Optional[Exception] = None
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
    model = config.model or "deepseek-chat"
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config.apiKey}",
    }
    body: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": True,
    }
    if response_format is not None:
        body["response_format"] = response_format
    if max_tokens:
        body["max_tokens"] = max_tokens

    async with httpx.AsyncClient(timeout=timeout) as client:
        async with client.stream(
            "POST", f"{base_url}/v1/chat/completions", headers=headers, json=body
        ) as res:
            if res.status_code >= 400:
                err = (await res.aread()).decode("utf-8", "replace")
                raise RuntimeError(f"DeepSeek API {res.status_code}: {err[:400]}")
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
                    yield str(delta)


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
