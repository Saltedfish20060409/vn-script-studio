"""LLM 超时预算的唯一真源（秒）。

## 为什么需要这个模块

此前每个调用点自己写 `timeout=120`，前端又各自写 `timeoutMs: 180000`，
两边是**两种不同的心智模型**：

- 后端写的是「**一次** LLM 调用的上限」，而 `chat_completions` 默认还会重试 3 次；
  非流式请求里 httpx 的 read timeout 等于**整段生成**的时间，所以一次业务请求的
  真实上限是 `timeout × max_retries + 退避`。
- 前端写的是「**这个 HTTP 请求**总共等多久」。

于是出现结构性失配：前端 180s 掐断时，后端最坏还要跑 360s+。用户看到
「请求超时（180s）——请确认后端服务已启动」，而后端明明活着、只是模型慢。
慢思考模型（`*-think` 档）100% 撞上这条线。

本模块把三件事集中到一处，前端 `src/api/timeouts.ts` 通过不变量测试与它对齐：

1. 命名预算常量（迁移时**值不变**，只把散落的字面量换成有含义的名字）；
2. 思考模式加时系数——reasoning 期间上游长时间不产出，非流式请求尤其明显；
3. 最坏耗时与退避的计算（`worst_case_seconds`），供测试与文档引用。

## 重试与超时的关系（`llm_http` 的实际策略）

- **连接类错误**（连不上 / DNS / 连接超时 / 连接被重置）：真的可能是抖动，
  照旧重试，每次只花掉很短的连接超时。
- **读超时**（请求发出去了但模型 N 秒没返回）：**不重试**。同一个请求、同样的
  预算，重试只会再慢一遍并多烧一次 token；此时应当如实告诉用户"模型太慢"。
  这条策略是前端预算能收得住的前提——否则最坏耗时永远是 `timeout × 3`，
  前端无论填多少都不够。
- **408 / 429 / 5xx**：上游明确说"稍后再来"，照旧重试（尊重 `Retry-After`）。
"""
from __future__ import annotations

# --- 命名预算：一次单轮 LLM 调用的基础上限（秒） ---------------------------
#
# 数值刻意与迁移前的字面量完全一致（30/60/90/120/180/240），迁移不改变任何行为；
# 改含义时只改这里。
PROBE = 30.0
"""配置自检 / 健康探测：只要证明"能连通"就够了，故意短。

思考档会被 `effective_timeout` 自动放大（30 → 60），否则慢思考模型会在
设置页的"测试连接"里被判失败。
"""

QUICK = 60.0
"""单轮短回答：问题预问、节拍核对、检索问答。"""

MEDIUM = 90.0
"""中等：滚动记忆归档、账本补全。"""

CHAT = 120.0
"""默认单轮生成。"""

WRITE = 180.0
"""长文写作 / 审稿 / 一致性审计。"""

LONG = 240.0
"""多段或回炉：章节回炉、共情审读。"""

# --- 重试 -----------------------------------------------------------------
DEFAULT_MAX_RETRIES = 3
"""`chat_completions` 的默认尝试次数（含首次）。"""

# --- 思考模式加时 ---------------------------------------------------------
THINKING_TIMEOUT_FACTOR = 2.0
"""思考模式档（`*-think` / reasoner）的超时倍数。

思考模型在产出正式回答前要先跑完 reasoning，这段时间上游一个字节都不发；
非流式请求的 read timeout 覆盖整段生成，所以同一个预算在思考档上会提前击中。
2.0 是保守取值：既覆盖实测的思考耗时，又不会让用户白等太久。
可用环境变量 ``LLM_THINKING_TIMEOUT_FACTOR`` 覆盖（会被夹到 1.0–5.0）。
"""

_FACTOR_MIN = 1.0
_FACTOR_MAX = 5.0

# 退避参数（与 `llm_http` 的实际退避保持一致：0.6 * 2**attempt + jitter，封顶 20）
_BACKOFF_BASE = 0.6
_BACKOFF_CAP = 20.0
_BACKOFF_MAX_JITTER = 0.35


def thinking_factor() -> float:
    """当前生效的思考模式加时系数（可被环境变量覆盖，越界值夹回合法区间）。"""
    try:
        from app.config import get_settings

        raw = float(getattr(get_settings(), "llm_thinking_timeout_factor", THINKING_TIMEOUT_FACTOR))
    except Exception:  # noqa: BLE001 - 配置不可用时退回默认值，不能因此让调用失败
        return THINKING_TIMEOUT_FACTOR
    if raw != raw:  # NaN
        return THINKING_TIMEOUT_FACTOR
    return min(_FACTOR_MAX, max(_FACTOR_MIN, raw))


def effective_timeout(
    base: float,
    *,
    thinking: bool = False,
    factor: float | None = None,
) -> float:
    """把调用点写的基础预算换算成实际生效的超时。

    `thinking=True`（出站模型带 `thinking: enabled`）时长按系数放大。
    """
    if not thinking:
        return float(base)
    f = thinking_factor() if factor is None else float(factor)
    return float(base) * min(_FACTOR_MAX, max(_FACTOR_MIN, f))


def backoff_seconds(attempt: int, *, jitter: float = 0.0) -> float:
    """第 `attempt` 次失败后的等待秒数（`jitter=0` 时是确定性下界）。

    与 `llm_http._backoff_seconds` 同一公式；`worst_case_seconds` 需要可复现的
    上界，所以这里把随机抖动做成显式参数。
    """
    base = _BACKOFF_BASE * (2 ** max(0, attempt))
    return min(_BACKOFF_CAP, base + jitter)


def max_backoff_total(attempts: int) -> float:
    """`attempts` 次尝试之间可能消耗的最大退避总和（按最坏抖动计）。"""
    n = max(0, attempts - 1)
    return sum(backoff_seconds(i, jitter=_BACKOFF_MAX_JITTER) for i in range(n))


def worst_case_seconds(
    base: float,
    *,
    attempts: int = DEFAULT_MAX_RETRIES,
    thinking: bool = False,
) -> float:
    """一次 LLM 调用在最坏情况下占用多久（秒）。

    注意：这只对**连接类错误重试**成立。读超时按 `llm_http` 的策略不重试，
    所以"模型太慢"这条路径实际只花 `effective_timeout(base)`。
    """
    n = max(1, attempts)
    return n * effective_timeout(base, thinking=thinking) + max_backoff_total(n)


def describe(base: float, *, thinking: bool = False) -> str:
    """给报错文案用的一句话：基础预算 + 思考模式加时后的实际预算。"""
    eff = effective_timeout(base, thinking=thinking)
    if thinking and eff != float(base):
        return f"{eff:.0f}s（基础 {base:.0f}s × 思考模式 {eff / float(base):.1f}）"
    return f"{eff:.0f}s"
