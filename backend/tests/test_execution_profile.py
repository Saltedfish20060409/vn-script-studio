"""执行档：**同步端点收着，流式端点放宽**（回答"要不要为无限上下文换架构"）。

背景：上下文天花板不是模型窗口给的，而是**我们自己的超时预算**给的——
非流式请求的 read timeout 要覆盖"预填充 + 整段生成"，预填充随提示词线性增长。
所以"能不能放下更大的上下文"取决于**等的人是谁**：

- 同步端点：前端按"这个 HTTP 请求"计时、有阶梯预算 → 必须收着（96k 字符 / 预填充 +60s）；
- 流式端点（SSE + 20s 心跳，前端不设总超时）→ 可以放宽（240k 字符 / 预填充 +240s）。

这两档用请求级 ContextVar 表达（`core/execution_profile.py`），本文件钉住三件事：
1. 档位与几个数真的连在一起（不是写了两组数字放着不用）；
2. **默认必须是保守档**，且档位不会跨请求泄漏——否则同步路径会拿到宽预算，
   前端先掐断、用户又看到"后端是不是挂了"；
3. 放宽只落在流式路由上（源码级守卫，防止有人把 set 调用挪到同步路由里）。
"""

from __future__ import annotations

import contextvars
from pathlib import Path
from types import SimpleNamespace

import pytest

from app.core import latency_stats, llm_budget
from app.core.agent_context import (
    MAX_CONTEXT_MAX_CHARS,
    MAX_CONTEXT_MAX_CHARS_STREAMED,
    context_budget_for_model,
)
from app.core.execution_profile import (
    PROFILE_STREAMED,
    PROFILE_SYNC,
    current_profile,
    declared_window_k,
    normalize_profile,
    reset_declared_window,
    reset_profile,
    set_declared_window_k,
    set_profile,
)

BACKEND_APP = Path(__file__).resolve().parent.parent / "app"


@pytest.fixture(autouse=True)
def _clean():
    reset_profile()
    latency_stats.reset()
    yield
    reset_profile()
    reset_declared_window()
    latency_stats.reset()


# ---- 档位本身 -----------------------------------------------------------------


def test_default_is_the_conservative_profile():
    """没设置时一律按同步档：宁可让流式少等，也不能让同步拿到宽预算。"""
    assert current_profile() == PROFILE_SYNC
    reset_profile()
    assert current_profile() == PROFILE_SYNC


@pytest.mark.parametrize("bad", ["", None, "STREAMING", "fast", "streamed-ish"])
def test_unknown_profile_falls_back_to_sync(bad):
    assert normalize_profile(bad) == PROFILE_SYNC
    assert set_profile(bad) == PROFILE_SYNC


def test_set_and_reset():
    assert set_profile(PROFILE_STREAMED) == PROFILE_STREAMED
    assert current_profile() == PROFILE_STREAMED
    reset_profile()
    assert current_profile() == PROFILE_SYNC


def test_profile_does_not_leak_across_contexts():
    """另一个请求（独立 context）里设了流式档，不能影响本请求。

    注意用的是 `contextvars.Context()`（**空**上下文）而不是 `copy_context()`：
    后者会把当前已设的值一起复制过去，那样测的就不是"另一个请求"了。
    """
    set_profile(PROFILE_STREAMED)
    assert contextvars.Context().run(current_profile) == PROFILE_SYNC
    # 反向：本请求里设的档也不会被别的 context 看到，但本请求仍然是流式
    assert current_profile() == PROFILE_STREAMED


# ---- 档位 → 预算 --------------------------------------------------------------


def test_streamed_profile_raises_the_prefill_cap():
    big = 200_000
    sync_cap = llm_budget.prefill_allowance(big, streamed=False)
    streamed_cap = llm_budget.prefill_allowance(big, streamed=True)
    # 同步档在这个体积上已经顶到上限（60s），流式档还远没到（128s < 240s）
    assert sync_cap == llm_budget.PREFILL_MAX_BONUS
    assert streamed_cap == pytest.approx(
        (big - llm_budget.PREFILL_FREE_CHARS) / llm_budget.PREFILL_CHARS_PER_SECOND
    )
    assert streamed_cap > sync_cap

    # 再大就顶到流式档自己的上限（240s），不会是无限
    huge = 10_000_000
    assert llm_budget.prefill_allowance(huge, streamed=True) == pytest.approx(
        llm_budget.PREFILL_MAX_BONUS_STREAMED
    )
    assert llm_budget.prefill_allowance(huge, streamed=False) == pytest.approx(
        llm_budget.PREFILL_MAX_BONUS
    )

    # 不显式传参时按**当前档位**取
    set_profile(PROFILE_STREAMED)
    assert llm_budget.prefill_allowance(big) == pytest.approx(streamed_cap)
    reset_profile()
    assert llm_budget.prefill_allowance(big) == pytest.approx(sync_cap)


def test_streamed_profile_raises_the_context_ceiling(monkeypatch):
    """配置里把预算写大：同步档夹到 96k，流式档可以到 240k。"""
    import app.config as config

    class _S:
        agent_context_max_chars = 500_000

    monkeypatch.setattr(config, "get_settings", lambda: _S())
    assert context_budget_for_model("deepseek-flash", streamed=False) == MAX_CONTEXT_MAX_CHARS
    assert (
        context_budget_for_model("deepseek-flash", streamed=True)
        == MAX_CONTEXT_MAX_CHARS_STREAMED
    )
    assert MAX_CONTEXT_MAX_CHARS_STREAMED > MAX_CONTEXT_MAX_CHARS


def test_window_clamp_still_wins_over_the_streamed_ceiling():
    """放宽的是"我们愿意等多久"，不是"模型窗口有多大"——小窗口模型照样被夹。"""
    streamed = context_budget_for_model("qwen3:8b", streamed=True)
    assert streamed < MAX_CONTEXT_MAX_CHARS
    assert streamed == context_budget_for_model("qwen3:8b", streamed=False)


# ---- 用户声明的模型窗口（窗口保护的最后一块债） ------------------------------


def test_declared_window_overrides_the_conservative_guess_for_custom_models(monkeypatch):
    """自建端点/没收录的模型：用户声明就以他为准（只有他知道真实窗口）。"""
    import app.config as config

    class _S:
        agent_context_max_chars = 96_000  # 预算调大，才看得出窗口的作用
        agent_unknown_model_window_k = 128

    monkeypatch.setattr(config, "get_settings", lambda: _S())

    assert context_budget_for_model("my-own-model") == 76_800  # 保守假设
    set_declared_window_k(256)
    assert context_budget_for_model("my-own-model") == 96_000  # 声明更大 → 不再是瓶颈
    set_declared_window_k(32)
    assert context_budget_for_model("my-own-model") == 19_200  # 声明更小 → 按他说的夹


def test_declared_window_can_only_lower_a_known_model(monkeypatch):
    """已知模型：声明只能调**低**，不可能超过厂商窗口（否则就是把请求送去撞墙）。"""
    import app.config as config

    class _S:
        agent_context_max_chars = 96_000
        agent_unknown_model_window_k = 128

    monkeypatch.setattr(config, "get_settings", lambda: _S())

    set_declared_window_k(32)
    assert context_budget_for_model("deepseek-flash") == 19_200  # 预设 1000k → 取小的 32k
    set_declared_window_k(2000)
    assert context_budget_for_model("deepseek-flash") == 96_000  # 预设 1000k 胜出


def test_negative_declared_window_means_do_not_clamp(monkeypatch):
    import app.config as config

    class _S:
        agent_context_max_chars = 96_000
        agent_unknown_model_window_k = 128

    monkeypatch.setattr(config, "get_settings", lambda: _S())
    set_declared_window_k(-1)
    assert context_budget_for_model("my-own-model") == 96_000


@pytest.mark.parametrize(
    "raw,expected",
    [(None, 0), ("", 0), ("abc", 0), (-5, -1), (0, 0), (128, 128), (999_999, 10_000)],
)
def test_declared_window_is_normalized(raw, expected):
    assert set_declared_window_k(raw) == expected
    assert declared_window_k() == expected



def test_both_profiles_satisfy_the_cross_module_invariant():
    """每个档位各自满足：允许拼出来的最长上下文 ≤ 该档预填充加时上限能覆盖的量。"""
    sync = llm_budget.prefill_allowance(MAX_CONTEXT_MAX_CHARS, streamed=False)
    assert 0 < sync <= llm_budget.PREFILL_MAX_BONUS + 1e-9
    streamed = llm_budget.prefill_allowance(MAX_CONTEXT_MAX_CHARS_STREAMED, streamed=True)
    assert 0 < streamed <= llm_budget.PREFILL_MAX_BONUS_STREAMED + 1e-9
    # 流式档的"超时收益"不是无限的：240k 字符对应 ~155s 预填充，这就是代价
    assert streamed == pytest.approx(
        (MAX_CONTEXT_MAX_CHARS_STREAMED - llm_budget.PREFILL_FREE_CHARS)
        / llm_budget.PREFILL_CHARS_PER_SECOND,
        rel=1e-6,
    )


def test_worst_case_and_describe_follow_the_profile():
    set_profile(PROFILE_STREAMED)
    assert llm_budget.worst_case_seconds(120, attempts=2, prompt_chars=200_000) > 2 * 120
    assert "长上下文预填充" in llm_budget.describe(120, prompt_chars=200_000)


# ---- 只放宽流式路由（源码级守卫） --------------------------------------------


def test_streaming_routes_opt_in_and_sync_routes_do_not():
    """`execution_profile.set_profile(PROFILE_STREAMED)` 只能出现在流式处理函数里。

    这条防的是一类很难查的错：有人把 set 调用挪到同步路由（或模块顶层），
    于是同步端点拿到 240s 的宽预算——前端阶梯仍然收在几分钟上下，
    结果是"前端先掐断 + 用户被告知后端可能挂了"。所以逐函数地钉住位置。
    """
    marker = "execution_profile.set_profile(execution_profile.PROFILE_STREAMED)"
    src = (BACKEND_APP / "api" / "v1" / "projects.py").read_text(encoding="utf-8")
    assert src.count(marker) == 1, "只放宽流式端点，且只在一个地方放宽"
    head = src[: src.index(marker)]
    # 往上找最近的函数定义：必须是 SSE 流式端点
    func_at = head.rfind("\nasync def ")
    assert func_at > 0
    signature = head[func_at : func_at + 200]
    assert "run_project_agent_stream" in signature, signature

    pipeline = (BACKEND_APP / "api" / "v1" / "pipeline.py").read_text(encoding="utf-8")
    assert pipeline.count(marker) == 1
    # 而且只能在"确实在流式"的分支里放宽
    assert "if body.stream:" in pipeline, "pipeline 只能在流式分支放宽"
    assert pipeline.index("if body.stream:") < pipeline.index(marker)


# ---- 上下文体积/截断统计（判据） ---------------------------------------------


def test_context_stats_are_recorded_per_task():
    from app.core.agent_loop import record_context_stats

    record_context_stats(
        SimpleNamespace(charsUsed=12000, task="continue", truncated=False, excluded=[])
    )
    record_context_stats(
        SimpleNamespace(charsUsed=48000, task="continue", truncated=True, excluded=["craft"])
    )
    stats = latency_stats.percentiles("context|continue")
    assert stats["count"] == 2
    assert stats["total"]["p50"] == 12000
    assert stats["total"]["max"] == 48000
    assert stats["truncated"] == 1
    assert stats["truncationRate"] == 0.5


def test_context_stats_never_raise_on_odd_input():
    from app.core.agent_loop import record_context_stats

    record_context_stats(SimpleNamespace())  # 全默认
    record_context_stats(SimpleNamespace(charsUsed="x", task=None, truncated=None))
    assert latency_stats.percentiles("context|unknown")["count"] >= 1


def test_prompt_size_is_part_of_the_latency_summary():
    latency_stats.record_latency(3.0, model="m", kind="write", prompt_chars=48000)
    latency_stats.record_latency(4.0, model="m", kind="write", prompt_chars=2000)
    stats = latency_stats.percentiles("m|fast|write")
    assert stats["promptChars"]["p50"] == 2000
    assert stats["promptChars"]["max"] == 48000
    assert stats["timeoutRate"] == 0.0
    assert stats["truncationRate"] == 0.0


def test_context_meta_carries_budget_and_truncation_for_the_ui():
    """界面要能说"它这次读了多少、够不够、有没有被裁"——这三个量必须在 contextMeta 里。

    没有它们，作者只能看到 AI 写出前后矛盾的东西，然后以为"它怎么忘了"。
    """
    from app.domain.types import AgentContextMeta

    meta = AgentContextMeta(
        task="continue",
        charsUsed=47000,
        budgetChars=48000,
        truncated=True,
        included=["当前章截断:24000/60000字"],
    )
    dumped = meta.model_dump(mode="json")
    assert dumped["charsUsed"] == 47000
    assert dumped["budgetChars"] == 48000
    assert dumped["truncated"] is True

    # 旧字段不变（前端老版本仍能读）
    legacy = AgentContextMeta(task="chat", charsUsed=100)
    assert legacy.budgetChars is None
    assert legacy.truncated is None

