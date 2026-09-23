"""配对实验的统计量具（纯 stdlib，不引 numpy/scipy）。

为什么需要
----------
`--ab` 报告以前只打两臂**均值之差**：n=13、没有区间、没有显著性。于是
"工具 2.9 vs 裸聊 1.1" 读起来像结论，实际上 13 个样本的均值差，
置信区间完全可能横跨 0。一份自己都不给不确定度的评测，没法用来做决策，
更没法回答"这软件是不是还不如直接聊天框问一句"。

这里补三件量具，都是配对（同一用例、两臂）场景下正确的做法：

1. **bootstrap 置信区间**：对"每例的差值"重采样。配对差值把用例间的难度差异
   抵消掉了，比分别对两臂求区间再目测重叠要敏感得多。
2. **符号检验**：只看差值正负号的非参数检验。评分是有界序数（1–4），
   均值本身就不太站得住，符号检验对离群值免疫，正好补上这一点。
3. **McNemar 精确检验**：配对二分类（一票否决这种 0/1 结果）的专用检验。
   只数"两臂判断不一致"的那几例，一致的那些不提供信息。

随机性由调用方传入的 ``random.Random`` 控制，同一 seed 结果完全可复现——
量具必须可复现，否则每次跑出来的"结论"都不一样。
"""

from __future__ import annotations

import math
import random
from typing import Any, Dict, Iterable, List, Optional, Sequence

DEFAULT_ITERS = 5000
DEFAULT_ALPHA = 0.05


def _percentile(sorted_vals: Sequence[float], q: float) -> float:
    if not sorted_vals:
        return 0.0
    if len(sorted_vals) == 1:
        return float(sorted_vals[0])
    pos = (len(sorted_vals) - 1) * q
    lo = int(math.floor(pos))
    hi = int(math.ceil(pos))
    if lo == hi:
        return float(sorted_vals[lo])
    return float(sorted_vals[lo] + (sorted_vals[hi] - sorted_vals[lo]) * (pos - lo))


def paired_bootstrap_ci(
    diffs: Sequence[float],
    *,
    iters: int = DEFAULT_ITERS,
    alpha: float = DEFAULT_ALPHA,
    rng: Optional[random.Random] = None,
) -> Dict[str, Any]:
    """配对差值的均值与 bootstrap 置信区间。

    样本为空时返回 ``n=0`` 而不是编一个 0 —— 没数据就说没数据。
    """
    vals = [float(d) for d in diffs]
    n = len(vals)
    if n == 0:
        return {"n": 0, "mean": None, "lo": None, "hi": None, "iters": 0, "alpha": alpha}
    rnd = rng or random.Random(0)
    mean = sum(vals) / n
    if n == 1:
        return {
            "n": 1,
            "mean": round(mean, 4),
            "lo": None,
            "hi": None,
            "iters": 0,
            "alpha": alpha,
            "note": "只有 1 例，无法给出区间",
        }
    means: List[float] = []
    for _ in range(max(1, iters)):
        s = 0.0
        for _ in range(n):
            s += vals[rnd.randrange(n)]
        means.append(s / n)
    means.sort()
    return {
        "n": n,
        "mean": round(mean, 4),
        "lo": round(_percentile(means, alpha / 2), 4),
        "hi": round(_percentile(means, 1 - alpha / 2), 4),
        "iters": max(1, iters),
        "alpha": alpha,
        "crossesZero": _percentile(means, alpha / 2) <= 0 <= _percentile(means, 1 - alpha / 2),
    }


def binom_two_sided_p(k: int, n: int, p: float = 0.5) -> float:
    """精确二项检验（双尾）。

    双尾的定义用"概率不高于观测点"的取值求和，而不是简单地 ×2——
    后者在分布不对称时会给出大于 1 的 p 值。
    """
    if n <= 0:
        return 1.0
    k = max(0, min(n, int(k)))
    probs = [math.comb(n, i) * (p**i) * ((1 - p) ** (n - i)) for i in range(n + 1)]
    obs = probs[k]
    tol = obs * (1 + 1e-9) + 1e-15
    return min(1.0, sum(pr for pr in probs if pr <= tol))


def sign_test(diffs: Sequence[float], *, tol: float = 1e-9) -> Dict[str, Any]:
    """符号检验：差值 > 0 / < 0 的条数，以及双尾精确 p。"""
    pos = sum(1 for d in diffs if d > tol)
    neg = sum(1 for d in diffs if d < -tol)
    ties = len(diffs) - pos - neg
    n = pos + neg
    p = binom_two_sided_p(min(pos, neg), n) if n else 1.0
    return {"positive": pos, "negative": neg, "ties": ties, "n": n, "p": round(p, 4)}


def mcnemar_exact(b: int, c: int) -> Dict[str, Any]:
    """McNemar 精确检验。``b`` / ``c`` 是两臂判断**不一致**的例数。"""
    n = int(b) + int(c)
    p = binom_two_sided_p(min(int(b), int(c)), n) if n else 1.0
    return {"b": int(b), "c": int(c), "discordant": n, "p": round(p, 4)}


def _mean(values: Sequence[float]) -> Optional[float]:
    return (sum(values) / len(values)) if values else None


def summarize_paired(
    tool: Sequence[Optional[float]],
    bare: Sequence[Optional[float]],
    *,
    iters: int = DEFAULT_ITERS,
    alpha: float = DEFAULT_ALPHA,
    rng: Optional[random.Random] = None,
) -> Dict[str, Any]:
    """两臂配对汇总：均值、均值差、配对 bootstrap 区间、符号检验。

    只统计**两臂都有值**的用例（有臂报错时该例对差值无贡献），并如实报出 n。
    """
    diffs: List[float] = []
    t_vals: List[float] = []
    b_vals: List[float] = []
    for t, b in zip(tool, bare):
        if t is None or b is None:
            continue
        t_vals.append(float(t))
        b_vals.append(float(b))
        diffs.append(float(t) - float(b))
    ci = paired_bootstrap_ci(diffs, iters=iters, alpha=alpha, rng=rng)
    return {
        "n": len(diffs),
        "toolMean": round(_mean(t_vals), 4) if t_vals else None,
        "bareMean": round(_mean(b_vals), 4) if b_vals else None,
        "meanDiff": round(_mean(diffs), 4) if diffs else None,
        "ci": ci,
        "signTest": sign_test(diffs),
    }


def summarize_binary_paired(
    tool: Iterable[bool], bare: Iterable[bool]
) -> Dict[str, Any]:
    """配对二分类汇总（用在一票否决这类 0/1 结果上）。"""
    b = c = both = neither = 0
    for t, br in zip(tool, bare):
        t, br = bool(t), bool(br)
        if t and not br:
            b += 1
        elif br and not t:
            c += 1
        elif t and br:
            both += 1
        else:
            neither += 1
    out = mcnemar_exact(b, c)
    out.update({"both": both, "neither": neither})
    return out


def format_ci(ci: Dict[str, Any]) -> str:
    """给终端用的一行人话。"""
    if not ci or ci.get("mean") is None:
        return "n/a"
    if ci.get("lo") is None:
        return f"{ci['mean']:+.2f}（n={ci['n']}，样本太少无法给出区间）"
    flag = "（区间跨 0，方向不显著）" if ci.get("crossesZero") else "（区间不含 0）"
    return (
        f"{ci['mean']:+.2f}  95%CI [{ci['lo']:+.2f}, {ci['hi']:+.2f}] "
        f"n={ci['n']}{flag}"
    )
