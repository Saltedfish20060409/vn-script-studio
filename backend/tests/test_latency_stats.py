"""耗时分位统计 + **不 hedge** 的决定（The Tail at Scale, CACM 56(2), 2013）。

论文的操作结论是"均值没用，长尾才是问题"。我们此前没有任何耗时分布数据，
所以 `llm_budget` 的预算只能按最坏情况推、文档里的取舍只能靠推理——这个模块让
"p95 到底多少"变成可测量的。同一篇论文的对策 hedged request（发两路取先返回）
**我们没有采用**，理由与量化写在本文最后一组测试与 docs/llm-timeout-budget.md：
单一上游没有独立副本，第二路只会排在同一段容量后面，拿不到延迟收益却稳定多花一份 token。
"""

from __future__ import annotations

import asyncio
from pathlib import Path
from unittest.mock import AsyncMock, MagicMock, patch

import httpx
import pytest

from app.core import latency_stats
from app.core.ai import DeepSeekConfig
from app.core.llm_http import chat_completions

BACKEND_APP = Path(__file__).resolve().parent.parent / "app"


@pytest.fixture(autouse=True)
def _clean_stats():
    latency_stats.reset()
    yield
    latency_stats.reset()


# ---- 分位定义：可手算 --------------------------------------------------------


def test_percentile_is_nearest_rank_and_hand_checkable():
    values = sorted(float(i) for i in range(1, 101))  # 1..100
    assert latency_stats._percentile(values, 0.50) == 50
    assert latency_stats._percentile(values, 0.95) == 95
    assert latency_stats._percentile(values, 0.99) == 99
    assert latency_stats._percentile(values, 1.0) == 100
    # 单样本 / 越界也必须是确定的
    assert latency_stats._percentile([7.0], 0.99) == 7.0


def test_series_key_separates_model_tier_and_kind():
    """思考档与非思考档、不同能力必须分开统计——混在一起算出的 p99 没法用。"""
    fast = latency_stats.series_key("deepseek-flash", thinking=False, kind="write")
    think = latency_stats.series_key("deepseek-flash", thinking=True, kind="write")
    other = latency_stats.series_key("deepseek-flash", thinking=False, kind="probe")
    assert len({fast, think, other}) == 3
    assert latency_stats.series_key("", thinking=False, kind="") == "unknown|fast|llm"


# ---- 记录与汇总 --------------------------------------------------------------


def test_record_and_summarize():
    for i in range(1, 21):
        latency_stats.record_latency(i, model="m", kind="write")
    stats = latency_stats.percentiles("m|fast|write")
    assert stats["count"] == 20
    assert stats["total"]["p50"] == 10
    assert stats["total"]["p95"] == 19
    assert stats["total"]["max"] == 20
    assert stats["timeouts"] == 0


def test_empty_series_says_no_samples_not_zero_seconds():
    """"没有样本"必须是可区分的：显示成 0 秒会让人以为"快到不用管"。"""
    stats = latency_stats.percentiles("nothing|fast|write")
    assert stats == {"count": 0, "note": "没有样本"}


def test_window_is_bounded_and_keeps_the_latest():
    for i in range(latency_stats.WINDOW_SIZE + 50):
        latency_stats.record_latency(float(i), model="m")
    stats = latency_stats.percentiles("m|fast|llm")
    assert stats["count"] == latency_stats.WINDOW_SIZE
    # 保留的是**最近**的样本：窗口里最大值等于最后一个样本
    assert stats["total"]["max"] == float(latency_stats.WINDOW_SIZE + 49)


def test_timeouts_are_counted_as_tail_events():
    """超时也要进样本：只统计"成功的那些请求"会把 p99 稀释掉。"""
    for _ in range(4):
        latency_stats.record_latency(1.0, model="m", kind="write")
    latency_stats.record_latency(120.0, model="m", kind="write", timed_out=True)
    stats = latency_stats.percentiles("m|fast|write")
    assert stats["count"] == 5
    assert stats["timeouts"] == 1
    assert stats["timeoutRate"] == 0.2
    assert stats["total"]["max"] == 120.0


def test_first_token_is_tracked_only_when_present():
    latency_stats.record_latency(30.0, model="m", first_token=12.5)
    latency_stats.record_latency(20.0, model="m")  # 非流式：没有首字时间
    stats = latency_stats.percentiles("m|fast|llm")
    assert stats["total"]["count"] == 2
    assert stats["firstToken"]["count"] == 1
    assert stats["firstToken"]["p95"] == 12.5


def test_bad_values_never_raise():
    latency_stats.record_latency(float("nan"), model="m")
    latency_stats.record_latency(-3, model="m")
    latency_stats.record_latency("abc", model="m")  # type: ignore[arg-type]
    assert latency_stats.percentiles("m|fast|llm")["count"] == 0


def test_snapshot_is_sorted_and_self_describing():
    latency_stats.record_latency(1.0, model="a")
    for _ in range(3):
        latency_stats.record_latency(2.0, model="b")
    snap = latency_stats.snapshot()
    assert list(snap["series"])[0] == "b|fast|llm", "样本多的排前面"
    assert snap["windowSize"] == latency_stats.WINDOW_SIZE
    # 必须自述边界：看的人才知道 p99 为什么可能和上次不一样
    assert "进程内" in snap["scope"] and "重启清零" in snap["scope"]


# ---- 接进出站链路 ------------------------------------------------------------


def _cfg() -> DeepSeekConfig:
    return DeepSeekConfig(apiKey="sk-test", baseUrl="https://api.example.com", model="deepseek-flash")


def _ok_response() -> httpx.Response:
    return httpx.Response(
        200,
        json={"model": "deepseek-flash", "choices": [{"message": {"content": "ok"}}]},
        request=httpx.Request("POST", "https://api.example.com/v1/chat/completions"),
    )


def test_successful_call_is_recorded():
    posts = AsyncMock(return_value=_ok_response())
    client = MagicMock()
    client.post = posts
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)

    async def _run():
        with patch("app.core.llm_http.httpx.AsyncClient", return_value=client):
            return await chat_completions(_cfg(), messages=[{"role": "user", "content": "hi"}])

    assert asyncio.run(_run()).status_code == 200
    stats = latency_stats.percentiles("deepseek-flash|fast|llm")
    assert stats["count"] == 1
    assert stats["total"]["max"] >= 0


def test_read_timeout_is_recorded_as_a_timeout_then_raised():
    posts = AsyncMock(
        side_effect=httpx.ReadTimeout(
            "slow", request=httpx.Request("POST", "https://api.example.com/v1/chat/completions")
        )
    )
    client = MagicMock()
    client.post = posts
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)

    async def _run():
        with patch("app.core.llm_http.httpx.AsyncClient", return_value=client):
            with pytest.raises(RuntimeError, match="模型响应超时"):
                await chat_completions(_cfg(), messages=[{"role": "user", "content": "hi"}])

    asyncio.run(_run())
    stats = latency_stats.percentiles("deepseek-flash|fast|llm")
    assert stats["count"] == 1 and stats["timeouts"] == 1


def test_thinking_tier_is_a_separate_series():
    posts = AsyncMock(return_value=_ok_response())
    client = MagicMock()
    client.post = posts
    client.__aenter__ = AsyncMock(return_value=client)
    client.__aexit__ = AsyncMock(return_value=None)

    async def _run():
        with patch("app.core.llm_http.httpx.AsyncClient", return_value=client):
            await chat_completions(
                DeepSeekConfig(
                    apiKey="sk-test", baseUrl="https://api.example.com", model="deepseek-flash-think"
                ),
                messages=[{"role": "user", "content": "hi"}],
            )

    asyncio.run(_run())
    assert latency_stats.percentiles("deepseek-flash|think|llm")["count"] == 1
    assert latency_stats.percentiles("deepseek-flash|fast|llm")["count"] == 0


# ---- 政策：我们**不做** hedged request（理由与量化写在这里） ------------------


def test_no_hedged_requests_a_single_call_sends_exactly_one_request():
    """一次逻辑调用只发一个请求，重试只发生在**失败之后**（顺序），没有并发重复。

    为什么不做 hedging（论文的对策）：hedged request 的前提是"有独立副本"——
    同一份请求发给另一台机器，谁先回用谁的。我们只有一个上游端点，
    第二路只会排在同一段容量后面：**拿不到延迟收益，却稳定多花一份 token**
    （一次 hedged 调用的 token 成本 ×2）。所以这里没有任何"并发发同一请求"的写法。
    """
    src = (BACKEND_APP / "core" / "llm_http.py").read_text(encoding="utf-8")
    assert "asyncio.gather" not in src, "llm_http 里出现了并发发请求的写法（可能是 hedging 混进来了）"
    assert src.count("client.post(") == 1
    assert src.count("client.stream(") == 1


def test_sanctioned_parallelism_lives_elsewhere_and_is_bounded():
    """真正该并发的地方是**不同的工作**（不是同一请求的第二路），且都有上界。

    - 多变体采样 / 多窗口一致性扫描：不同 prompt、各自独立，
      `_LLM_SEMAPHORE` 给全站并发兜底；
    - 这两处都不属于"对冲"，它们在文档里单独说明。
    """
    llm_http = (BACKEND_APP / "core" / "llm_http.py").read_text(encoding="utf-8")
    assert "_LLM_SEMAPHORE = asyncio.Semaphore(" in llm_http

    from app.core.llm_http import _LLM_SEMAPHORE

    assert _LLM_SEMAPHORE._value >= 1  # noqa: SLF001 - 只断言"有上界且非零"

    candidates = (BACKEND_APP / "core" / "pipeline" / "candidates.py").read_text(encoding="utf-8")
    assert "asyncio.gather" in candidates, "多变体采样应当是并发的（不同的工作）"
    assert "DEFAULT_CANDIDATES = 3" in candidates, "候选项数必须有上界"

    scan = (BACKEND_APP / "core" / "consistency_scan.py").read_text(encoding="utf-8")
    assert "asyncio.Semaphore(" in scan, "多窗口扫描必须有并发上界"
