"""Shared OpenAI-compatible chat/completions client with retry + backoff."""
from __future__ import annotations

import asyncio
import json
import random
import time
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from app.core import latency_stats, llm_budget
from app.core.ai import DeepSeekConfig
from app.core.disconnect import model_call_watch
from app.core.model_presets import supports_json_mode, supports_logprobs
from app.llm_models import DEFAULT_LLM_MODEL, resolve_chat_model

#: 默认取前几个候选分布（`top_logprobs`）。5 是"够算峰度、响应体不至于膨胀"的折中：
#: 每个 token 多 5 条记录，一次局部改写（几百 token）大约多几十 KB。
DEFAULT_TOP_LOGPROBS = 5

# Retry these transient upstream statuses
_RETRY_STATUSES = {408, 429, 500, 502, 503, 504}

# 只重试"连不上/连接被掐断"这一类——它们更可能是抖动，且单次只花掉很短的连接超时。
# 读/写超时**不在**这里：那表示上游太慢，同样的预算重试必然再超时，只会多烧一次
# token 并把用户多晾一整个超时窗口。见 app/core/llm_budget.py 的模块说明。
#
# 注意 httpx 的层级（0.28 实测）：ConnectTimeout 与 ReadTimeout / WriteTimeout 一样
# 直接继承 TimeoutException，**不是** ConnectError 的子类，所以必须单独列出；
# NetworkError 覆盖 ConnectError / ReadError / WriteError。
_RETRYABLE_TRANSPORT = (
    httpx.ConnectTimeout,
    httpx.PoolTimeout,
    httpx.NetworkError,
    httpx.RemoteProtocolError,
)

# 连接阶段单独封顶：连不上时不该等满整个生成预算。
_CONNECT_TIMEOUT_CAP = 10.0

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
    logprobs: bool = False,
    top_logprobs: int = DEFAULT_TOP_LOGPROBS,
) -> httpx.Response:
    """
    POST /v1/chat/completions with exponential backoff on 429/5xx.
    Returns the successful Response (caller parses JSON).

    `logprobs=True` 时请求逐 token 的对数概率（供多变体取舍用，见
    `core/variant_select.py`）；只在模型被确认支持时才会真的写进请求体，
    所以调用方不必自己判断能力（见 `model_presets.supports_logprobs`）。
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
        logprobs=logprobs,
        top_logprobs=top_logprobs,
    )
    headers = {
        "Content-Type": "application/json",
        "Authorization": f"Bearer {config.apiKey}",
    }
    # 思考模式档自动加时：reasoning 期间上游不产出，非流式的 read timeout 覆盖整段
    # 生成，同一个预算在 *-think 档上会提前击中（慢思考模型必超时的根因之一）。
    # 预填充也占这个预算：read timeout 覆盖"预填充 + 整段生成"，长上下文必须加时。
    thinking = _is_thinking_body(body)
    prompt_chars = _prompt_chars(messages)
    budget = llm_budget.effective_timeout(timeout, thinking=thinking, prompt_chars=prompt_chars)
    started = time.monotonic()

    last_exc: Optional[Exception] = None
    async with _LLM_SEMAPHORE:
        async with httpx.AsyncClient(timeout=_client_timeout(budget)) as client:
            for attempt in range(max(1, max_retries)):
                try:
                    # 客户端断开就立刻停手：思考档一次生成几十秒到几分钟，
                    # 白跑完既烧 token 又占着并发闸。见 app/core/disconnect.py。
                    async with model_call_watch():
                        res = await client.post(
                            _chat_url(base_url),
                            headers=headers,
                            json=body,
                        )
                except asyncio.CancelledError:
                    raise
                except (httpx.ReadTimeout, httpx.WriteTimeout) as exc:
                    # 不重试：同一请求同一预算必然再超时，重试只会多烧一次 token。
                    # 超时是**尾部事件**，如实记一笔（见 core/latency_stats.py）：
                    # 没有这条，p99 会被"成功的那些请求"稀释掉。
                    latency_stats.record_latency(
                        time.monotonic() - started,
                        model=model,
                        thinking=thinking,
                        kind=latency_stats_kind(),
                        timed_out=True,
                    )
                    raise _timeout_error(
                        model=model,
                        base=timeout,
                        thinking=thinking,
                        stage="",
                        prompt_chars=prompt_chars,
                    ) from exc
                except _RETRYABLE_TRANSPORT as exc:
                    last_exc = exc
                    if attempt + 1 >= max_retries:
                        raise RuntimeError(f"LLM 网络失败：{exc}") from exc
                    await asyncio.sleep(_backoff_seconds(attempt))
                    continue

                if res.status_code < 400:
                    # Best-effort per-user usage accounting (fire-and-forget).
                    # kind 取当前上下文（中间件按路径判定），这样报表能区分
                    # "审稿/回炉/一致性检查/地图抽取"各花了多少——此前写死 "llm"。
                    try:
                        from app.core.usage import (
                            current_usage_kind,
                            current_usage_user,
                            record_usage_later,
                        )

                        uid = current_usage_user()
                        if uid:
                            record_usage_later(
                                user_id=uid,
                                kind=current_usage_kind(),
                                model=model,
                                usage=usage_from_response(res),
                            )
                    except Exception:  # noqa: BLE001 - accounting never breaks calls
                        pass
                    # 成功的调用也要记耗时：p50/p95/p99 是"要不要 hedge / 要不要加预算"
                    # 的唯一依据（The Tail at Scale 的操作结论，见 core/latency_stats.py）
                    latency_stats.record_latency(
                        time.monotonic() - started,
                        model=model,
                        thinking=thinking,
                        kind=latency_stats_kind(),
                    )
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
    logprobs: bool = False,
    top_logprobs: int = DEFAULT_TOP_LOGPROBS,
) -> tuple[str, Dict[str, Any]]:
    raw_model = (config.model or "").strip()
    model, thinking = resolve_chat_model(config.model or DEFAULT_LLM_MODEL)
    body: Dict[str, Any] = {
        "model": model,
        "messages": messages,
        "temperature": temperature,
        "stream": stream,
    }
    if thinking:
        body["thinking"] = {"type": thinking}
    # 有些档位不支持结构化输出，硬发 response_format 会被对方直接拒绝
    # （Anthropic 的 OpenAI 兼容层就会报错）。判断统一放在这里，调用方不用各自小心：
    # 提示词里本来就写着"只输出 JSON"，所以拿掉这个参数只是少了服务端约束。
    #
    # 两个名字都要看：*-think 这类别名会被 resolve_chat_model 改写成正式名
    # （deepseek-flash-think → deepseek-flash），只看改写后的名字就会漏掉
    # "思考模式不支持 JSON 模式"这一条。
    if (
        response_format is not None
        and supports_json_mode(model)
        and supports_json_mode(raw_model)
    ):
        body["response_format"] = response_format
    # logprobs 的开关方向与 response_format **相反**：未知模型默认不发。
    # 理由：response_format 不被支持时只是少一条服务端约束（提示词里已经写明要 JSON），
    # 而未知参数会把整个请求打成 400——那等于"为了一个可选信号把主功能弄挂"。
    if logprobs and supports_logprobs(model) and supports_logprobs(raw_model) and not stream:
        body["logprobs"] = True
        body["top_logprobs"] = max(2, min(20, int(top_logprobs)))
    if max_tokens:
        body["max_tokens"] = max_tokens
    return model, body


def _backoff_seconds(attempt: int) -> float:
    # 0.6, 1.2, 2.4 … + jitter
    base = 0.6 * (2**attempt)
    return min(20.0, base + random.uniform(0, 0.35))


def _client_timeout(total: float) -> httpx.Timeout:
    """把总预算用作 read/write/pool，连接阶段另设较短的封顶。

    连接不上时不该等满 120s 才第一次重试：连接阶段只花几秒，重试才便宜。
    """
    return httpx.Timeout(total, connect=min(_CONNECT_TIMEOUT_CAP, total))


def _is_thinking_body(body: Dict[str, Any]) -> bool:
    """出站 body 是否带着 `thinking: enabled`（思考模式档）。"""
    t = body.get("thinking")
    return isinstance(t, dict) and t.get("type") == "enabled"


def latency_stats_kind() -> str:
    """当前请求属于哪种 AI 能力（耗时统计按它分桶；拿不到就用 "llm"）。

    单独包一层是因为 `core/usage` 是可选的上下文（单测里没有中间件时不存在），
    统计不该因此失败。
    """
    try:
        from app.core.usage import current_usage_kind

        return current_usage_kind()
    except Exception:  # noqa: BLE001
        return "llm"


def _prompt_chars(messages: List[Dict[str, str]]) -> int:
    """本次出站提示词的总字符数（预填充加时的依据）。

    只数文本长度，不做 token 估算：这里要的是"提示词变长了就得给更多时间"这个
    单调关系，精确 token 数对超时预算没有意义（见 llm_budget.PREFILL_*）。
    """
    total = 0
    for m in messages or []:
        content = m.get("content") if isinstance(m, dict) else None
        if isinstance(content, str):
            total += len(content)
    return total


def _timeout_error(
    *,
    model: str,
    base: float,
    thinking: bool,
    stage: str,
    prompt_chars: int | None = None,
) -> RuntimeError:
    """读超时的如实报错：问题在模型速度/预算，而不是"后端没启动"。

    此前请求超时会被包成 "LLM 网络失败：..."，前端再翻译成"请确认后端服务
    已启动"——后端明明活着。文案必须指向真正的原因，并给出可执行的下一步。
    """
    label = llm_budget.describe(base, thinking=thinking, prompt_chars=prompt_chars)
    mode = "（思考模式）" if thinking else ""
    return RuntimeError(
        f"模型响应超时：{label}内没有返回结果{stage}（模型 {model}{mode}）。"
        "常见原因是当前档位偏慢、上下文过长或上游波动——"
        "可换成非思考档、缩短本次范围，或改用会持续输出进度的流式入口后重试。"
    )


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
    model, body = _chat_body(
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
    thinking = _is_thinking_body(body)
    # 流式：timeout 是"多久没有新字节"的空闲上限，不是整段生成的预算，
    # 所以慢模型不会因为总时长而失败；思考档仍要加时（reasoning 期间无增量），
    # 长上下文的**预填充**同样在这条空闲线之内（第一个字节要等预填充跑完）。
    budget = llm_budget.effective_timeout(
        timeout, thinking=thinking, prompt_chars=_prompt_chars(messages)
    )
    # 流式最该被量的是**第一个字节**（= 预填充 + 排队），它决定了用户盯着空白等多久；
    # 总时长反而被"一直在出字"掩盖着（见 core/latency_stats.py）。
    started = time.monotonic()
    first_token_at: Optional[float] = None

    async def _stream_once() -> AsyncIterator[str]:
        nonlocal received_any, first_token_at
        async with _LLM_SEMAPHORE:
            async with httpx.AsyncClient(timeout=_client_timeout(budget)) as client:
                # 整个流式请求都在"客户端还在吗"的窗口内：断开就把当前任务取消掉，
                # 免得一边没人看一边继续生成。
                async with model_call_watch():
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
                                if first_token_at is None:
                                    first_token_at = time.monotonic() - started
                                received_any = True
                                yield str(delta)

    # 最多重连 1 次：仅当 429/5xx 且尚未产出任何内容增量时，等
    # Retry-After（封顶 5s）或 1s 后重试；与 chat_completions 的
    # 重试语义对齐（此前流式接口对 429/5xx 直接抛错，不对称）。
    while True:
        try:
            async for delta in _stream_once():
                yield delta
            latency_stats.record_latency(
                time.monotonic() - started,
                model=model,
                thinking=thinking,
                kind=latency_stats_kind(),
                first_token=first_token_at,
            )
            return
        except (httpx.ReadTimeout, httpx.WriteTimeout) as exc:
            # 流式中途空闲超时：不再重连（已产出的内容无法回滚），如实报"模型卡住"。
            # 这也是尾部事件，照记一笔（含"有没有等到第一个字"）。
            latency_stats.record_latency(
                time.monotonic() - started,
                model=model,
                thinking=thinking,
                kind=latency_stats_kind(),
                first_token=first_token_at,
                timed_out=True,
            )
            raise _timeout_error(
                model=model,
                base=timeout,
                thinking=thinking,
                stage="，且中途停止输出",
                prompt_chars=_prompt_chars(messages),
            ) from exc
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


def response_logprobs(res: httpx.Response) -> Any:
    """取出 `choices[0].logprobs`（没有就返回 None，由调用方显示"未测量"）。

    单独一个函数是为了把"读响应字段"这件事收在一处：调用方（多变体取舍）只需要
    `certainty_from_logprobs(response_logprobs(res))`。
    """
    try:
        data = res.json()
    except Exception:  # noqa: BLE001 - 响应体不是 JSON 时不能因此炸掉
        return None
    choices = data.get("choices") or []
    if not choices:
        return None
    return (choices[0] or {}).get("logprobs")


def usage_from_response(res: httpx.Response) -> Dict[str, int]:
    data = res.json()
    usage = data.get("usage") or {}
    return {
        "prompt": int(usage.get("prompt_tokens") or 0),
        "completion": int(usage.get("completion_tokens") or 0),
        "total": int(usage.get("total_tokens") or 0),
    }
