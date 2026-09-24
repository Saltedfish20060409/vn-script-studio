"""LLM 超时预算与重试策略：慢思考模型不再必超时、超时文案不再甩锅后端。

背景（用户报障）：用 `*-think` 档时前端弹「请确认后端服务已启动」。
真因是前端按「一个 HTTP 请求」计时（180s），后端按「一次 LLM 调用 × 默认 3 次
重试」计时（最坏 360s+），而思考档在 reasoning 期间一个字节都不发——非流式请求
的 read timeout 覆盖整段生成，所以同一个预算在思考档上必然提前击中。
"""
from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.core import llm_budget
from app.core.ai import DeepSeekConfig
from app.core.llm_http import chat_completions


def _cfg(model: str = "deepseek-flash") -> DeepSeekConfig:
    return DeepSeekConfig(apiKey="sk-test", baseUrl="https://api.example.com", model=model)


def _ok_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "model": "deepseek-flash",
            "choices": [{"message": {"content": "ok"}}],
        },
        request=httpx.Request("POST", "https://api.example.com/v1/chat/completions"),
    )


def _client(posts: AsyncMock) -> MagicMock:
    mock_client = MagicMock()
    mock_client.post = posts
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)
    return mock_client


def _read_timeout() -> httpx.ReadTimeout:
    return httpx.ReadTimeout(
        "timed out",
        request=httpx.Request("POST", "https://api.example.com/v1/chat/completions"),
    )


# --- 纯函数：预算换算 -------------------------------------------------------


def test_thinking_factor_doubles_effective_timeout():
    assert llm_budget.effective_timeout(120, thinking=False) == 120
    assert llm_budget.effective_timeout(120, thinking=True, factor=2.0) == 240
    # 非思考档不受系数影响
    assert llm_budget.effective_timeout(180, thinking=False, factor=2.0) == 180


def test_thinking_factor_is_clamped():
    """配错的环境变量不能把预算变成 0 或无穷大。"""
    assert llm_budget.effective_timeout(100, thinking=True, factor=0) == 100
    assert llm_budget.effective_timeout(100, thinking=True, factor=-3) == 100
    assert llm_budget.effective_timeout(100, thinking=True, factor=999) == 500


def test_worst_case_counts_every_attempt_plus_backoff():
    """最坏耗时 = 尝试次数 × 实际预算 + 退避总和（前端预算要对齐这个口径）。"""
    one = llm_budget.worst_case_seconds(120, attempts=1)
    three = llm_budget.worst_case_seconds(120, attempts=3)
    assert one == 120
    assert three > 360  # 3 次预算 + 退避
    assert three == 360 + llm_budget.max_backoff_total(3)
    assert llm_budget.worst_case_seconds(120, attempts=3, thinking=True) > 720


def test_describe_names_both_base_and_effective_budget():
    assert llm_budget.describe(120) == "120s"
    text = llm_budget.describe(120, thinking=True)
    assert "240s" in text and "120s" in text


# --- 出站超时：思考档自动加时 -----------------------------------------------


def _read_timeout_sent(model: str, **kwargs) -> float:  # noqa: ANN003
    posts = AsyncMock(return_value=_ok_response())
    mock_client = _client(posts)

    async def _run():
        with patch("app.core.llm_http.httpx.AsyncClient", return_value=mock_client) as ctor:
            await chat_completions(_cfg(model), messages=[{"role": "user", "content": "hi"}], **kwargs)
        return ctor.call_args.kwargs["timeout"]

    return asyncio.run(_run())


def _read_timeout_for(messages, **kwargs) -> float:  # noqa: ANN001
    """出站 read 预算（按给定 messages），用于验证"提示词越长、预算越大"。"""
    posts = AsyncMock(return_value=_ok_response())
    mock_client = _client(posts)

    async def _run():
        with patch("app.core.llm_http.httpx.AsyncClient", return_value=mock_client) as ctor:
            await chat_completions(_cfg(), messages=messages, **kwargs)
        return ctor.call_args.kwargs["timeout"]

    return asyncio.run(_run())


def test_thinking_model_gets_multiplied_outbound_timeout():
    """慢思考档必须拿到更长的 read 预算 —— 否则 reasoning 期间就被判超时。"""
    normal = _read_timeout_sent("deepseek-flash", timeout=120)
    thinking = _read_timeout_sent("deepseek-flash-think", timeout=120)
    assert normal.read == 120
    assert thinking.read == 120 * llm_budget.thinking_factor()
    assert thinking.read > normal.read


def test_connect_phase_is_capped_short():
    """连接阶段不该等满整个生成预算（否则一次连不上就白等 2 分钟）。"""
    timeout = _read_timeout_sent("deepseek-flash", timeout=120)
    assert timeout.connect <= 10
    assert timeout.read == 120


# --- 预填充加时：长提示词必须拿到更长的 read 预算 ---------------------------
#
# 背景（同一次政策调整）：上下文预算放大到能装整章正文，而 read timeout 覆盖的是
# "预填充 + 整段生成"。若不按提示词长度加时，放大上下文就会重新制造
# "后端明明活着，前端却说它挂了"——这正是用户报障过的那个 bug。


def test_small_prompt_keeps_the_old_budget_exactly():
    """小提示词逐字保持旧行为：加时只对长上下文生效。"""
    timeout = _read_timeout_for([{"role": "user", "content": "hi"}], timeout=120)
    assert timeout.read == 120
    assert llm_budget.prefill_allowance(len("hi")) == 0


def test_long_prompt_gets_prefill_allowance():
    prompt = "雨" * 48000
    timeout = _read_timeout_for([{"role": "user", "content": prompt}], timeout=120)
    expected = 120 + llm_budget.prefill_allowance(48000)
    assert expected > 120
    assert timeout.read == pytest.approx(expected)


def test_prompt_size_is_summed_over_all_messages():
    """system + user 都算进预填充（只数 user 会低估一半）。"""
    msgs = [
        {"role": "system", "content": "雨" * 30000},
        {"role": "user", "content": "雨" * 18000},
    ]
    timeout = _read_timeout_for(msgs, timeout=120)
    assert timeout.read == pytest.approx(120 + llm_budget.prefill_allowance(48000))


def test_thinking_factor_and_prefill_stack():
    """思考档 ×2 与预填充**叠加**，不是二选一。"""
    props = llm_budget.effective_timeout(
        120, thinking=True, factor=2.0, prompt_chars=48000
    )
    assert props == pytest.approx(240 + llm_budget.prefill_allowance(48000))
    assert llm_budget.worst_case_seconds(
        120, attempts=2, thinking=True, prompt_chars=48000
    ) > 2 * props


def test_timeout_message_names_the_long_context_term():
    """文案要把"多出来的时间是长提示词预填充"说出来，用户才知道缩范围就能变快。"""
    posts = AsyncMock(side_effect=_read_timeout())
    mock_client = _client(posts)

    async def _run():
        with patch("app.core.llm_http.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(RuntimeError) as err:
                await chat_completions(
                    _cfg(),
                    messages=[{"role": "user", "content": "雨" * 48000}],
                    timeout=120,
                )
            return err.value

    err = asyncio.run(_run())
    assert "模型响应超时" in str(err)
    assert "长上下文预填充" in str(err)


def test_stream_idle_budget_also_counts_prefill():
    """流式的"多久没有新字节"里包含等第一个字节的时间，也就是预填充。"""
    from app.core.llm_http import stream_chat_completions

    class _FakeStream:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        @property
        def status_code(self):
            return 200

        async def aiter_lines(self):
            raise httpx.ReadTimeout(
                "stalled",
                request=httpx.Request("POST", "https://api.example.com/v1/chat/completions"),
            )
            yield  # pragma: no cover - 让它是异步生成器

    mock_client = MagicMock()
    mock_client.stream = MagicMock(return_value=_FakeStream())
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    async def _run():
        with patch("app.core.llm_http.httpx.AsyncClient", return_value=mock_client) as ctor:
            with pytest.raises(RuntimeError):
                async for _ in stream_chat_completions(
                    _cfg(),
                    messages=[{"role": "user", "content": "雨" * 48000}],
                    timeout=180,
                ):
                    pass
        return ctor.call_args.kwargs["timeout"]

    timeout = asyncio.run(_run())
    assert timeout.read == pytest.approx(180 + llm_budget.prefill_allowance(48000))


# --- 重试策略：读超时不重试 -------------------------------------------------


def test_read_timeout_is_not_retried():
    """同一请求同一预算重试必然再超时，只会多烧一次 token。"""
    posts = AsyncMock(side_effect=_read_timeout())
    mock_client = _client(posts)

    async def _run():
        with patch("app.core.llm_http.httpx.AsyncClient", return_value=mock_client):
            with patch("app.core.llm_http.asyncio.sleep", new_callable=AsyncMock) as slept:
                with pytest.raises(RuntimeError) as err:
                    await chat_completions(
                        _cfg(), messages=[{"role": "user", "content": "hi"}], max_retries=3
                    )
                return err.value, slept

    err, slept = asyncio.run(_run())
    assert posts.await_count == 1, "读超时被重试了"
    assert slept.await_count == 0
    # 文案要指向真因（模型慢），不能是"网络失败"这种会被前端翻译成"后端没启动"的话
    assert "模型响应超时" in str(err)
    assert "网络失败" not in str(err)
    assert "deepseek-flash" in str(err)


def test_timeout_message_mentions_thinking_budget():
    posts = AsyncMock(side_effect=_read_timeout())
    mock_client = _client(posts)

    async def _run():
        with patch("app.core.llm_http.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(RuntimeError) as err:
                await chat_completions(
                    _cfg("deepseek-flash-think"),
                    messages=[{"role": "user", "content": "hi"}],
                    timeout=120,
                )
            return err.value

    err = asyncio.run(_run())
    assert "思考模式" in str(err)
    assert "240s" in str(err)


def test_connect_error_is_still_retried():
    """连接类错误是真的抖动，照旧重试（且连接超时很短，重试便宜）。"""
    posts = AsyncMock(
        side_effect=httpx.ConnectError(
            "boom", request=httpx.Request("POST", "https://api.example.com/v1/chat/completions")
        )
    )
    mock_client = _client(posts)

    async def _run():
        with patch("app.core.llm_http.httpx.AsyncClient", return_value=mock_client):
            with patch("app.core.llm_http.asyncio.sleep", new_callable=AsyncMock):
                with pytest.raises(RuntimeError, match="网络失败"):
                    await chat_completions(
                        _cfg(), messages=[{"role": "user", "content": "hi"}], max_retries=3
                    )

    asyncio.run(_run())
    assert posts.await_count == 3


def test_connect_timeout_counts_as_connect_class():
    """连接阶段超时要走"可重试"分支——它和读超时是两回事。

    这里曾经踩过坑：httpx 0.28 里 `ConnectTimeout` 与 `ReadTimeout` 一样直接继承
    `TimeoutException`，**不是** `ConnectError` 的子类，只写 ConnectError 会漏掉它。
    """
    posts = AsyncMock(
        side_effect=httpx.ConnectTimeout(
            "slow connect",
            request=httpx.Request("POST", "https://api.example.com/v1/chat/completions"),
        )
    )
    mock_client = _client(posts)

    async def _run():
        with patch("app.core.llm_http.httpx.AsyncClient", return_value=mock_client):
            with patch("app.core.llm_http.asyncio.sleep", new_callable=AsyncMock):
                with pytest.raises(RuntimeError, match="网络失败"):
                    await chat_completions(
                        _cfg(), messages=[{"role": "user", "content": "hi"}], max_retries=2
                    )

    asyncio.run(_run())
    assert posts.await_count == 2


def test_connect_timeout_is_not_confused_with_read_timeout():
    """两者都叫 TimeoutException，但一个重试、一个不重试——这条把区别钉住。"""
    assert issubclass(httpx.ConnectTimeout, httpx.TimeoutException)
    assert issubclass(httpx.ReadTimeout, httpx.TimeoutException)
    assert not issubclass(httpx.ConnectTimeout, httpx.ReadTimeout)
    from app.core.llm_http import _RETRYABLE_TRANSPORT

    assert issubclass(httpx.ConnectTimeout, _RETRYABLE_TRANSPORT)
    assert not issubclass(httpx.ReadTimeout, _RETRYABLE_TRANSPORT)
    assert not issubclass(httpx.WriteTimeout, _RETRYABLE_TRANSPORT)


def test_status_retry_policy_unchanged():
    """429/5xx 依旧重试：上游明确说"稍后再来"，与读超时不是一回事。"""
    def _429() -> httpx.Response:
        return httpx.Response(
            429,
            text="rate limited",
            request=httpx.Request("POST", "https://api.example.com/v1/chat/completions"),
        )

    posts = AsyncMock(side_effect=[_429(), _ok_response()])
    mock_client = _client(posts)

    async def _run():
        with patch("app.core.llm_http.httpx.AsyncClient", return_value=mock_client):
            with patch("app.core.llm_http.asyncio.sleep", new_callable=AsyncMock):
                return await chat_completions(
                    _cfg(), messages=[{"role": "user", "content": "hi"}], max_retries=3
                )

    assert asyncio.run(_run()).status_code == 200
    assert posts.await_count == 2


# --- 源码级约束：不许再出现裸数字 -------------------------------------------


def test_llm_call_sites_use_named_budgets_only():
    """凡是调用 chat_completions 的模块，超时必须是 llm_budget 命名常量。

    裸数字会让前端的预算表（`frontend/src/api/timeouts.test.ts`）失去核对依据：
    前端只能"猜"后端等了多久，而这次故障的根因正是两边各写各的数字。

    两类明确排除（都会在下面注释里说明为什么不是"单次模型调用预算"）：
    - `asyncio.wait_for(..., timeout=20)`：SSE 心跳间隔；
    - `httpx.AsyncClient(timeout=...)`：第三方客户端级超时（音乐/百科等）。
    """
    import re
    from pathlib import Path

    app_dir = Path(__file__).resolve().parent.parent / "app"
    raw = re.compile(r"(?<![_\w])timeout\s*=\s*[0-9]")
    offenders: list[str] = []
    for path in sorted(app_dir.rglob("*.py")):
        src = path.read_text(encoding="utf-8")
        if "chat_completions(" not in src and "stream_chat_completions(" not in src:
            continue
        for lineno, line in enumerate(src.splitlines(), 1):
            code = line.split("#", 1)[0]  # 注释里的举例不算
            if "timeout:" in code:  # 带类型标注的默认值是签名，不是调用点
                continue
            if "wait_for(" in code or "AsyncClient(" in code:
                continue  # 心跳间隔 / 第三方客户端超时，不属于本预算体系
            if raw.search(code):
                offenders.append(f"{path.name}:{lineno}: {line.strip()}")
    assert not offenders, "LLM 调用点出现裸数字超时：\n" + "\n".join(offenders)


def test_non_llm_http_clients_keep_their_own_timeouts():
    """非 LLM 的外部服务超时（百科 / 邮件 / 语义检索）不属于本预算体系，保持原样。

    这条不是"必须这样"，而是把边界写下来：它们没有"思考档加时"的概念，
    也不该被 frontend 的 LLM 预算表拿去核对。
    """
    from pathlib import Path

    app_dir = Path(__file__).resolve().parent.parent / "app"
    keep = {
        "core/lore/moegirl_client.py": "timeout=25",
        "core/email_send.py": "timeout=30.0",
        "core/semantic_search.py": "timeout=60",
    }
    for rel, needle in keep.items():
        src = (app_dir / rel).read_text(encoding="utf-8")
        assert needle in src, f"{rel} 的外部服务超时被改动，请确认是有意的"
        assert "llm_budget" not in src, f"{rel} 不是 LLM 调用点，不该引入 llm_budget"



def test_stream_idle_timeout_reports_model_stall():
    from app.core.llm_http import stream_chat_completions

    class _FakeStream:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return None

        @property
        def status_code(self):
            return 200

        async def aiter_lines(self):
            raise httpx.ReadTimeout(
                "stalled",
                request=httpx.Request("POST", "https://api.example.com/v1/chat/completions"),
            )
            yield  # pragma: no cover - 让它是异步生成器

    mock_client = MagicMock()
    mock_client.stream = MagicMock(return_value=_FakeStream())
    mock_client.__aenter__ = AsyncMock(return_value=mock_client)
    mock_client.__aexit__ = AsyncMock(return_value=None)

    async def _run():
        with patch("app.core.llm_http.httpx.AsyncClient", return_value=mock_client):
            with pytest.raises(RuntimeError) as err:
                async for _ in stream_chat_completions(
                    _cfg("deepseek-flash-think"),
                    messages=[{"role": "user", "content": "hi"}],
                    timeout=180,
                ):
                    pass
            return err.value

    err = asyncio.run(_run())
    assert "模型响应超时" in str(err)
    assert "中途停止输出" in str(err)
