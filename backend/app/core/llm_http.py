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

# 敏感字段模式：上游错误体里若混入 key/token 一类内容，回显前剥掉。
_SECRET_PATTERNS = (
    "sk-",
    "api_key",
    "apikey",
    "authorization",
    "bearer ",
)


def _summarize_upstream_error(body: str) -> str:
    """Extract a short, safe error summary from an upstream provider response.

    Providers return JSON like {"error": {"message": "..."}}; we keep only a
    bounded message and never echo raw bodies that may embed secrets or
    internal debugging info (SECURITY: error-reflect convergence).
    """
    text = (body or "").strip()
    if not text:
        return "（无详情）"
    if text.startswith("{"):
        try:
            parsed = json.loads(text)
            err = parsed.get("error") if isinstance(parsed, dict) else None
            if isinstance(err, dict):
                msg = err.get("message")
            elif isinstance(err, str):
                msg = err
            else:
                msg = None
            if isinstance(msg, str) and msg.strip():
                text = msg.strip()
        except json.JSONDecodeError:
            pass
    # Never echo anything that looks like a credential.
    low = text.lower()
    for pat in _SECRET_PATTERNS:
        if pat in low:
            return "（上游返回了疑似敏感内容，已隐藏详情）"
    return text[:200]


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


def _chat_url(base_url: str) -> str:
    """OpenAI 兼容端点 URL 归一化。

    厂商路径分三种：
    - 裸根（DeepSeek/Moonshot/OpenAI）：base + /v1/chat/completions
    - 带 /v1 版本前缀（dashscope compatible-mode/v1、用户按文档填的 .../v1）：
      base 已是版本前缀，直接 + /chat/completions（曾拼出 /v1/v1 → 404）
    - 带 /v4 版本前缀（智谱 open.bigmodel.cn/api/paas/v4）：
      同样直接 + /chat/completions（曾拼出 /v4/v1 → 404）
    - 已是完整 .../chat/completions：原样使用
    """
    base = (base_url or "https://api.deepseek.com").rstrip("/")
    if base.endswith("/chat/completions"):
        return base
    if base.endswith("/v1") or base.endswith("/v4"):
        return f"{base}/chat/completions"
    return f"{base}/v1/chat/completions"


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
                        _chat_url(base_url),
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
                    f"上游模型服务返回错误（HTTP {res.status_code}）："
                    f"{_summarize_upstream_error(res.text)}"
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
                    "POST", _chat_url(base_url), headers=headers, json=body
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
