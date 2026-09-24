"""LLM 调用耗时的**分位统计**（进程内、有界窗口）。

## 为什么要它（依据）

Dean & Barroso, *The Tail at Scale*（CACM 56(2), 2013）的核心操作结论是：
**均值没用，长尾才是问题**——只看平均值会让人以为"平均 3 秒，挺好的"，
而 p99 可能已经顶到前端预算。我们此前**没有任何耗时分布数据**：
`llm_budget` 里的预算是按最坏情况推的，`docs/llm-timeout-budget.md` 里的取舍
也只能靠推理。没有实测分布，"要不要 hedge / 要不要加预算"就只能拍脑袋。

同一篇论文的对策是 hedged request（发两路取先返回）。**我们没有采用**，
理由与量化写在 `docs/llm-timeout-budget.md` 第十节：单一上游没有独立副本，
第二路请求只会排在同一段容量后面，拿不到延迟收益，却稳定地多花一份 token。
本模块的作用是把那个决定变成**可被推翻的**：先量出真实的 p95/p99，
再谈要不要为尾部付双份钱。

## 边界（如实写出来，别把它当监控系统）

- **进程内、不落库**：重启即清零，多 worker 各自一份（`uvicorn --workers N` 时不合并）。
  代价换来的好处是热路径上零 IO、零迁移。
- **有界窗口**：每个 key 只保留最近 `WINDOW_SIZE` 次，内存恒定。
- **只统计调用耗时**，不记用户、不记 prompt/输出内容——所以它最多泄露
  "某个模型名有多慢"，放在管理员接口里（`/admin/llm-latency`）。
- 需要**历史** p99（跨重启、跨 worker）时，正确的做法是把它写进用量表
  （`core/usage.py` 那条通道），而不是把这个模块做大。
"""
from __future__ import annotations

import threading
from typing import Any, Dict, List, Optional, Sequence

#: 每个 key 保留的最近样本数。200 足够看 p95/p99 的量级（p99=第 2 慢的那次），
#: 又不至于让内存随流量增长。
WINDOW_SIZE = 200

#: 会做分位统计的数值字段（布尔字段另算"发生率"）。
#: `promptChars` 是"这次出站提示词多大"——它回答的是**上下文预算有没有被用满**，
#: 也是"要不要为更大上下文换架构"的唯一依据（见 docs/long-context-policy.md）。
_NUMERIC_FIELDS = ("total", "firstToken", "promptChars")

#: 会被统计成"发生率"的布尔字段（字段名 → (次数键, 发生率键)）。
#: 这些是**尾部/降级事件**：只统计成功的请求会把它们稀释掉。
#: `timeouts` 这个键名是既有约定（管理员接口与测试都在用），不要改名。
_FLAG_FIELDS = {
    "timedOut": ("timeouts", "timeoutRate"),
    "truncated": ("truncated", "truncationRate"),
}

_LOCK = threading.Lock()
#: key -> 最近样本（每个样本是 dict：total / firstToken / timedOut）
_SAMPLES: Dict[str, List[Dict[str, Any]]] = {}


def series_key(model: str, *, thinking: bool = False, kind: str = "") -> str:
    """统计口径：模型 + 是否思考档 + 能力类型（kind 来自 `core/usage.py` 的上下文）。

    为什么按这三项分：它们的耗时量级完全不同（思考档 vs 非思考档、写作 vs 探测），
    混在一起算出的 p99 既不能用来调预算，也不能用来判断"哪条链路慢"。
    """
    name = (model or "unknown").strip() or "unknown"
    tier = "think" if thinking else "fast"
    label = (kind or "llm").strip() or "llm"
    return f"{name}|{tier}|{label}"


def record_latency(
    seconds: float,
    *,
    model: str,
    thinking: bool = False,
    kind: str = "",
    first_token: Optional[float] = None,
    timed_out: bool = False,
    prompt_chars: Optional[int] = None,
    truncated: bool = False,
) -> None:
    """记一次调用耗时（也可带上"这次提示词多大/上下文是否被裁"）。任何异常都不许冒泡。"""
    try:
        value = float(seconds)
        if value != value or value < 0:  # NaN / 负数
            return
        sample: Dict[str, Any] = {"total": value, "timedOut": bool(timed_out)}
        if first_token is not None:
            ft = float(first_token)
            if ft == ft and ft >= 0:
                sample["firstToken"] = ft
        if prompt_chars is not None:
            pc = float(prompt_chars)
            if pc == pc and pc >= 0:
                sample["promptChars"] = pc
        if truncated:
            sample["truncated"] = True
        key = series_key(model, thinking=thinking, kind=kind)
        with _LOCK:
            bucket = _SAMPLES.setdefault(key, [])
            bucket.append(sample)
            if len(bucket) > WINDOW_SIZE:
                del bucket[: len(bucket) - WINDOW_SIZE]
    except Exception:  # noqa: BLE001 - 统计永远不该打断调用
        return


def record_context(
    chars_used: int,
    *,
    task: str,
    truncated: bool = False,
    dropped_sections: int = 0,
) -> None:
    """记一次**上下文拼装**的体积与是否被裁（口径见 `agent_context`）。

    与 `record_latency` 分开是因为它统计的是"我们拼了多大的提示词"，
    不是"模型花了多久"——但两者一起才能回答"预算是不是真的卡住了写作"：
    - `promptChars` 的分位逼近天花板 + `truncationRate` 高 → 该放开预算（甚至换架构）；
    - 两者都很低 → 调大预算是白花钱（线上实测拼装量长期只有几千字符）。
    """
    try:
        value = float(chars_used)
        if value != value or value < 0:
            return
        sample: Dict[str, Any] = {"total": value, "truncated": bool(truncated)}
        dropped = int(dropped_sections)
        if dropped > 0:
            sample["droppedSections"] = float(dropped)
        key = f"context|{(task or 'unknown').strip() or 'unknown'}"
        with _LOCK:
            bucket = _SAMPLES.setdefault(key, [])
            bucket.append(sample)
            if len(bucket) > WINDOW_SIZE:
                del bucket[: len(bucket) - WINDOW_SIZE]
    except Exception:  # noqa: BLE001
        return


def _percentile(sorted_values: Sequence[float], q: float) -> float:
    """最近秩（nearest-rank）分位：取第 ceil(q×n) 个值。

    刻意用最简单、可手算的定义：`p95(1..100) == 95`。近似的插值法会让
    "p99 到底是多少"变成一件需要解释的事，而这里的数据是给人做决策用的，
    可复现比平滑更重要。
    """
    if not sorted_values:
        raise ValueError("empty")
    n = len(sorted_values)
    index = int(-(-(q * n) // 1))  # ceil(q*n)
    index = min(n, max(1, index))
    return float(sorted_values[index - 1])


def _summarize(values: Sequence[float]) -> Dict[str, float]:
    ordered = sorted(float(v) for v in values)
    return {
        "count": len(ordered),
        "p50": round(_percentile(ordered, 0.50), 3),
        "p95": round(_percentile(ordered, 0.95), 3),
        "p99": round(_percentile(ordered, 0.99), 3),
        "max": round(ordered[-1], 3),
        "mean": round(sum(ordered) / len(ordered), 3),
    }


def percentiles(key: str) -> Dict[str, Any]:
    """某个口径的分位统计；没有样本时如实返回 `{"count": 0, "note": "没有样本"}`。"""
    with _LOCK:
        samples = list(_SAMPLES.get(key) or [])
    return _summarize_samples(samples)


def _summarize_samples(samples: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = {"count": len(samples)}
    if not samples:
        # "没有样本" ≠ "0 秒"：调用方必须能区分这两件事
        out["note"] = "没有样本"
        return out
    for field in _NUMERIC_FIELDS:
        values = [s[field] for s in samples if isinstance(s.get(field), (int, float))]
        if values:
            out[field] = _summarize(values)
    for field, (count_key, rate_key) in _FLAG_FIELDS.items():
        hits = sum(1 for s in samples if s.get(field))
        out[count_key] = hits
        out[rate_key] = round(hits / len(samples), 4)
    return out


def snapshot() -> Dict[str, Any]:
    """所有口径的统计（给管理员接口用）。按样本数降序，方便先看量大的链路。"""
    with _LOCK:
        keys = sorted(_SAMPLES, key=lambda k: -len(_SAMPLES[k]))
        series = {key: _summarize_samples(list(_SAMPLES[key])) for key in keys}
    return {
        "windowSize": WINDOW_SIZE,
        "series": series,
        # 说清它是"进程内、有界窗口"：看的人才知道 p99 为什么可能和上次不一样
        "scope": "进程内最近样本（重启清零；多 worker 各自一份，不合并）",
    }


def reset() -> None:
    """清空统计（测试用；也方便运维在换模型后重新起算）。"""
    with _LOCK:
        _SAMPLES.clear()
