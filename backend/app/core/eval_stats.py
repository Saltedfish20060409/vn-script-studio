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

#: 比例读数的"样本太少"门槛（次数，不是试玩场次）。
#: 与 `playtest_telemetry.MIN_SAMPLE_RUNS`（10 次试玩才做经验判断）同一套理由：
#: 个位数的样本上，任何方向性结论都站不住。这里按**选择次数**算——一个菜单可能只被
#: 选过 3 次，而全站有 20 场试玩。
THIN_SAMPLE_N = 10


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


# --------------------------------------------------------------- 比例型指标


def z_for_alpha(alpha: float = DEFAULT_ALPHA) -> float:
    """双侧置信水平对应的正态分位数（``alpha=0.05`` → 1.96）。

    用 Acklam 的有理逼近实现逆正态：误差 < 1e-9，纯 stdlib。
    为什么要支持任意 alpha 而不是写死 1.96：报告里同时要用到 90% / 95% / 99%
    （小样本时把区间放宽才不至于把噪声当结论），写死一个数会让调用方各自抄常量。
    """
    if not 0 < alpha < 1:
        raise ValueError("alpha 必须在 (0,1) 之间")
    p = 1.0 - alpha / 2.0
    # Acklam 逼近
    a = [-3.969683028665376e01, 2.209460984245205e02, -2.759285104469687e02,
         1.383577518672690e02, -3.066479806614716e01, 2.506628277459239e00]
    b = [-5.447609879822406e01, 1.615858368580409e02, -1.556989798598866e02,
         6.680131188771972e01, -1.328068155288572e01]
    c = [-7.784894002430293e-03, -3.223964580411365e-01, -2.400758277161838e00,
         -2.549732539343734e00, 4.374664141464968e00, 2.938163982698783e00]
    d = [7.784695709041462e-03, 3.224671290700398e-01, 2.445134137142996e00,
         3.754408661907416e00]
    plow, phigh = 0.02425, 1 - 0.02425
    if p < plow:
        q = math.sqrt(-2 * math.log(p))
        return (((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
        )
    if p > phigh:
        q = math.sqrt(-2 * math.log(1 - p))
        return -(((((c[0] * q + c[1]) * q + c[2]) * q + c[3]) * q + c[4]) * q + c[5]) / (
            (((d[0] * q + d[1]) * q + d[2]) * q + d[3]) * q + 1
        )
    q = p - 0.5
    r = q * q
    return (((((a[0] * r + a[1]) * r + a[2]) * r + a[3]) * r + a[4]) * r + a[5]) * q / (
        (((((b[0] * r + b[1]) * r + b[2]) * r + b[3]) * r + b[4]) * r) + 1
    )


def wilson_interval(
    successes: int,
    total: int,
    *,
    alpha: float = DEFAULT_ALPHA,
) -> Dict[str, Any]:
    """比例的 **Wilson 得分区间**（比"正态近似"在小样本/极端比例下正确得多）。

    为什么要它：试玩样本常常只有 5～20 次，而界面上显示的是 `share`（一个百分比）。
    「80% 选了 A」在 n=5 时的 95% 区间大约是 38%～96%——把这种数字当结论会直接改错剧本。
    本仓库早有同样的态度（"3 次试玩里没人选什么也说明不了"），这里把态度变成可显示的区间。

    为什么用 Wilson 而不是朴素正态近似：后者在 p 接近 0 或 1、或 n 很小时会给出越界
    （负的）或宽度为 0 的区间——而"没人选"恰恰是最常见的场景。

    边界：``total <= 0`` 时返回全 None（没数据就说没数据，不编 0）。
    """
    n = int(total or 0)
    k = int(successes or 0)
    if n <= 0:
        return {"n": 0, "k": 0, "p": None, "lo": None, "hi": None, "alpha": alpha}
    k = max(0, min(k, n))
    z = z_for_alpha(alpha)
    phat = k / n
    denom = 1 + z * z / n
    centre = (phat + z * z / (2 * n)) / denom
    half = (z * math.sqrt(phat * (1 - phat) / n + z * z / (4 * n * n))) / denom
    lo = max(0.0, centre - half)
    hi = min(1.0, centre + half)
    width = hi - lo
    return {
        "n": n,
        "k": k,
        "p": round(phat, 4),
        "lo": round(lo, 4),
        "hi": round(hi, 4),
        "alpha": alpha,
        # 区间宽度：调用方据此决定"这条读数敢不敢下结论"
        "width": round(width, 4),
        # 区间宽到横跨半个单位区间：任何方向性结论都不成立
        "wide": bool(width >= 0.5),
        # 样本量本身就少（次数口径）。为什么不只看宽度：5/5 的区间是 57%–100%，
        # 宽度 0.44 不到 0.5，但它显然不足以支撑"读者一致选它"这种结论。
        "thin": bool(n < THIN_SAMPLE_N),
    }


def format_proportion(ci: Dict[str, Any]) -> str:
    """给终端/日志用的一行人话：`80%（95%CI 38%–96%，n=5，样本太少）`。"""
    if not ci or ci.get("p") is None:
        return "n/a（没有样本）"
    pct = f"{ci['p'] * 100:.0f}%"
    lo = f"{ci['lo'] * 100:.0f}%"
    hi = f"{ci['hi'] * 100:.0f}%"
    pct_alpha = int(round((1 - float(ci.get("alpha") or DEFAULT_ALPHA)) * 100))
    tail = "，样本太少" if (ci.get("thin") or ci.get("wide")) else ""
    return f"{pct}（{pct_alpha}%CI {lo}–{hi}，n={ci['n']}{tail}）"
