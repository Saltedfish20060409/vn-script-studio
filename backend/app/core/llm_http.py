"""Shared OpenAI-compatible chat/completions client with retry + backoff."""
from __future__ import annotations

import asyncio
import json
import logging
import random
import time
from typing import Any, AsyncIterator, Dict, List, Optional

import httpx

from app.core import latency_stats, llm_budget
from app.core.ai import DeepSeekConfig
from app.core.disconnect import model_call_watch
from app.core.model_presets import (
    supports_json_mode,
    supports_logprobs,
    supports_stream_usage,
)
from app.llm_models import DEFAULT_LLM_MODEL, resolve_chat_model

logger = logging.getLogger(__name__)

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

#: 上游明确拒绝 `stream_options` 的模型名（进程内记忆）。见 `_stream_rejects_stream_options`
#: 与 `stream_chat_completions` 里的自愈分支：`model_presets.supports_stream_usage` 只是
#: 一张"猜得比较准"的表，猜错时不能让流式整个挂掉，所以留了这条运行时纠错。
_STREAM_OPTIONS_REJECTED: set[str] = set()

#: 上游把"不认识某个参数"时的措辞。只用于 `_looks_like_unknown_param`。
_UNKNOWN_PARAM_HINTS = (
    "stream_options",
    "include_usage",
    "unknown parameter",
    "unrecognized",
    "unsupported parameter",
    "invalid parameter",
    "extra fields not permitted",
    "unexpected keyword",
)

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


def _looks_like_unknown_param(body: str) -> bool:
    """这个 400 是不是"上游不认识我们多发的参数"造成的。

    只在敢确认时返回 True：把别的 400（内容审核拒绝、请求体超限……）误判成参数问题、
    摘掉参数再发一遍，是在错误的路上浪费一次调用，还可能掩盖真实原因。
    """
    text = (body or "").lower()
    return any(hint in text for hint in _UNKNOWN_PARAM_HINTS)


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
                        prompt_chars=prompt_chars,
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
                    _record_usage_best_effort(usage_from_response(res), model)
                    # 输出撞上限时别静默当成正常完成（此前全仓没有 finish_reason 检查）。
                    _warn_if_truncated(
                        finish_reason_from_response(res), model, streamed=False
                    )
                    # 成功的调用也要记耗时：p50/p95/p99 是"要不要 hedge / 要不要加预算"
                    # 的唯一依据（The Tail at Scale 的操作结论，见 core/latency_stats.py）；
                    # promptChars 则回答"上下文预算有没有被用满"（long-context-policy.md）
                    latency_stats.record_latency(
                        time.monotonic() - started,
                        model=model,
                        thinking=thinking,
                        kind=latency_stats_kind(),
                        prompt_chars=prompt_chars,
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
    # 流式用量回传：上游只有收到这个参数才会在最后一块 SSE 里带 usage，
    # 而不带 usage 的流式调用此前是**完全不记账**的（见 `_record_usage_best_effort`）。
    # 与 logprobs 一样"两个名字都要看"：别名会被 resolve_chat_model 改写。
    #
    # 保守方向与 logprobs 相同（未知模型不发），但**后果不同**：不发只是少记账，
    # 生成不受影响；而且真发错了也有兜底——`stream_chat_completions` 遇到上游
    # 400 会摘掉它重试一次，并把该模型记进 `_STREAM_OPTIONS_REJECTED`。
    names = {(model or "").strip().lower(), (raw_model or "").strip().lower()}
    names.discard("")
    if (
        stream
        and names
        and all(n not in _STREAM_OPTIONS_REJECTED for n in names)
        and all(supports_stream_usage(n) for n in names)
    ):
        body["stream_options"] = {"include_usage": True}
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
    #: 这次流式调用上游回传的用量（最后一块 SSE 里的 usage）。None = 上游没给。
    stream_usage: Optional[Dict[str, int]] = None
    #: 流式结束原因（`choices[0].finish_reason`）：撞上限时是 "length"。
    stream_finish_reason = ""
    #: 是否已经因为"上游不认 stream_options"摘掉参数重试过（每个模型只白跑一次）。
    dropped_stream_options = False
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
        nonlocal received_any, first_token_at, stream_usage, stream_finish_reason
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
                                # 最后一块是"只有 usage、choices 为空"的那种；
                                # 之前的实现 `if not choices: continue` 会连它一起跳过，
                                # 于是流式用量永远读不到（即使上游回传了）。
                                got = usage_from_payload(data)
                                if got is not None:
                                    stream_usage = got
                                continue
                            delta = ((choices[0] or {}).get("delta") or {}).get("content")
                            reason = (choices[0] or {}).get("finish_reason")
                            if reason:
                                # 流式的结束原因也在最后一块上；"length" = 撞了输出上限。
                                stream_finish_reason = str(reason)
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
                prompt_chars=_prompt_chars(messages),
            )
            # 用量记账：与非流式走同一个出口（此前流式一条都不记）。
            _warn_if_truncated(stream_finish_reason, model, streamed=True)
            if stream_usage is not None:
                _record_usage_best_effort(stream_usage, model)
            else:
                # 上游没回传用量 → 这次调用不计账。**必须说出来**：静默少记会让
                # 每日额度慢慢失真，而"额度没生效"这种问题平时看不出来。
                # 只对"我们发了参数、上游仍不给"的情况告警（预设没标 stream_usage 的
                # 档位属于已知情形，不发参数自然收不到，不算异常）。
                if "stream_options" in body:
                    logger.warning(
                        "流式调用没有回传 usage，本次不计入额度（model=%s）。"
                        "若该端点确实支持 stream_options.include_usage，请检查上游版本。",
                        model,
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
                timed_out=True,
                first_token=first_token_at,
                prompt_chars=_prompt_chars(messages),
            )
            raise _timeout_error(
                model=model,
                base=timeout,
                thinking=thinking,
                stage="，且中途停止输出",
                prompt_chars=_prompt_chars(messages),
            ) from exc
        except _StreamUpstreamError as exc:
            # 自愈：上游不认 `stream_options` 时报的是 400（不是 429/5xx），原来的
            # 分支会直接抛错——等于"为了一个可选的记账信号把流式弄挂"，绝不可以。
            # 这里摘掉参数重试一次，并把这个模型记进进程内的"不支持"集合，
            # 后续请求不再白跑。`model_presets.supports_stream_usage` 是张猜出来的表，
            # 猜错时靠这条兜住。
            if (
                not dropped_stream_options
                and not received_any
                and "stream_options" in body
                and exc.status == 400
                and _looks_like_unknown_param(exc.body)
            ):
                dropped_stream_options = True
                body.pop("stream_options", None)
                for name in {model.strip().lower(), (config.model or "").strip().lower()}:
                    if name:
                        _STREAM_OPTIONS_REJECTED.add(name)
                logger.warning(
                    "上游拒绝 stream_options，已摘掉它重试（model=%s）：本次仍会生成，"
                    "但该模型的流式调用不计账。",
                    model,
                )
                continue

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


def finish_reason_from_response(res: httpx.Response) -> str:
    """`choices[0].finish_reason`（取不到就返回空串）。

    为什么需要它：此前全仓 grep `finish_reason` 命中 0 次，也就是说**输出被上游
    截断时，我们把它当成正常完成**。对写作工具尤其糟——用户看到的是"AI 只写了一小段"，
    而系统日志里一切正常（commit 历史里"修 Agent 只回一小段正文"就是这个症状）。
    上游用 `finish_reason == "length"` 明确表示"撞到 max_tokens 了"，读一下就知道。
    """
    try:
        data = res.json()
    except Exception:  # noqa: BLE001 - 响应体不是 JSON 时不该因此炸掉
        return ""
    choices = data.get("choices") or []
    if not choices:
        return ""
    return str((choices[0] or {}).get("finish_reason") or "")


def _warn_if_truncated(finish_reason: str, model: str, *, streamed: bool) -> None:
    """撞上输出上限时说一句，不让它静默过去。

    只告警、不改行为：截断的正文**确实**被写进了章节（回滚是另一件事），
    这里要的是"这件事在日志里看得见"，而不是替调用方决定要不要丢弃。
    文案指向可执行的下一步（放宽 max_tokens 或让它继续写）。
    """
    if (finish_reason or "").lower() != "length":
        return
    logger.warning(
        "模型输出撞到上限被截断（model=%s，%s）：调用方若仍按「完整输出」处理，"
        "会得到半截正文或截断的 JSON。可放宽 max_tokens，或让模型继续写完。",
        model,
        "流式" if streamed else "非流式",
    )


def usage_from_response(res: httpx.Response) -> Dict[str, int]:
    data = res.json()
    usage = data.get("usage") or {}
    return {
        "prompt": int(usage.get("prompt_tokens") or 0),
        "completion": int(usage.get("completion_tokens") or 0),
        "total": int(usage.get("total_tokens") or 0),
    }


def usage_from_payload(data: Dict[str, Any]) -> Optional[Dict[str, int]]:
    """从一条 SSE 数据块里取 usage；没有就返回 None。

    流式响应把 usage 放在**最后一块**（choices 为空、usage 有值），所以它不能跟
    delta 一样只看 `choices[0]`。返回 None 而不是零值：调用方靠它区分
    "上游这次没回传用量"与"回传了但确实是 0"，前者要能被发现，不能伪装成后者。
    """
    usage = data.get("usage")
    if not isinstance(usage, dict) or not usage:
        return None
    return {
        "prompt": int(usage.get("prompt_tokens") or 0),
        "completion": int(usage.get("completion_tokens") or 0),
        "total": int(usage.get("total_tokens") or 0),
    }


def _record_usage_best_effort(usage: Optional[Dict[str, int]], model: str) -> None:
    """把一次调用的用量丢进记账队列（fire-and-forget，绝不打断调用）。

    抽成一个函数是因为**两条路径都要用**：非流式的 `chat_completions` 与流式的
    `stream_chat_completions`。此前这段只写在非流式那条分支里，于是走流式的调用
    （AI 责编聊天、流式章节写作）**完全不进账**——而 `ensure_under_quota` 只读
    `llm_usage`，所以每日额度与共享免费档的 cap 只被检查、从不累加，等于形同虚设。
    """
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
                usage=usage,
            )
    except Exception:  # noqa: BLE001 - accounting never breaks calls
        pass
