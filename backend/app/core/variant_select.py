"""多变体的取舍：**按证据选**，不按"模型先写的那版"，也不抽签。

## 为什么需要它（依据）

- Kang et al., *Scalable Best-of-N Selection for Large Language Models via
  Self-Certainty*（NeurIPS 2025）：多变体应当用**模型自身的置信度**排序——
  不需要奖励模型、不需要额外训练，on-policy 采样即可。论文的 self-certainty 是
  输出分布与均匀分布的 KL（需要**全词表**分布）。
- Wang et al., *Self-Consistency Improves Chain of Thought Reasoning*
  (arXiv:2203.11171)：同一问题的多份采样中，**彼此一致**的那份更可能可靠。

在此之前的实际行为是：`mark_revise` 取"模型列在第一位的那个变体"（`variants[0]`），
而它只是**输出顺序**，没有任何质量含义——一次采样里模型先写哪个纯属偶然。
这就是清单里那条"Best-of-N：多变体按自洽度选（现在靠挑）"。

## 我们能拿到什么（如实写清，不假装复现论文）

1. **置信度（`certainty`）**：OpenAI 兼容接口只给"被采样的那个 token"的 `logprob`
   与 `top_logprobs`（我们取 5），拿不到全词表。所以我们算的是 **top-k 上的峰度**
   与"所选 token 的置信度"，并且**不用论文的名字**（`peakedness` / `confidence`），
   报告里标 `kind="topk-proxy"`。拿不到 logprobs 时是 `None`（"未测量"），
   **不是 0**——0 会被当成"这一版很差"。
2. **一致性（`consensus`）**：本地就能算（字符 n-gram Jaccard 的均值），不花钱。
   但 N=2 时两份候选彼此的相似度是**同一个数**，没有"多数"可依——此时如实返回
   `None` 并在说明里写"两份候选之间没有多数可依"，而不是编一个看似有区分度的数。
3. **约束（`constraint`）**：`mark_revise.check_replacement` 那类"能确定判断"的检查
   （长度失控、丢专名）。这是唯一**确定性**的信号，所以它的权重最大。

三条信号缺哪条就从权重里去掉、剩下的重新归一化（同 `pipeline.candidates._weighted_score`
的做法：缺席的分项不该变成免费加分）。若三条都不可用（例如 N=1、没 logprobs、
没有任何检查项），winner 只是"原顺序第一位"，说明里必须这么写。

## 已知局限（写在前面，免得被当成"选出来的一定更好"）

- **多数一致 ≠ 更好**：三版里两版雷同、第三版更好的时候，一致性信号会把票投给
  雷同的那一对。所以它的权重低于确定性检查，而且分差小于 `TIE_MARGIN` 时我们
  如实说"这次没有明显更好的一版，建议都看看"，不假装有结论。
- **置信度衡量的是"模型写得多顺"，不是"写得多好"**：跑偏但流畅的版本会拿到高分。
  它能排除的是"模型自己都在犹豫"的那种版本，不能替代作者判断。
- **我们不评判文学质量**：这里只做"按可测量的证据排序"，最终选择权仍在作者手里
  （界面上每一版都能点开对比）。
"""
from __future__ import annotations

import math
import re
from dataclasses import asdict, dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

#: 各信号的权重（**我们的取值**，不是论文给的）。理由：约束项是确定性的，
#: 权重最大；一致性与置信度都与"这段好不好"相关但都不确定，且彼此相关
#: （一致的两份往往也都自信），所以各占较小的一份。
SIGNAL_WEIGHTS: Dict[str, float] = {
    "constraint": 0.4,
    "consensus": 0.35,
    "certainty": 0.25,
}

#: 前两名差距小于这个值就算"没有明显更好的一版"，如实告诉作者"都看看"，
#: 而不是编一个"推荐第 1 版"。取 0.05 是按信号量级定的（分数是 0–1）。
TIE_MARGIN = 0.05

#: 置信度信号至少要看这么多 token 才当真（更短的话峰度/置信度的方差很大）。
MIN_CERTAINTY_TOKENS = 20

#: 默认取前几个候选分布；再大会让响应体膨胀（每个 token 多 5 条记录）。
DEFAULT_TOP_LOGPROBS = 5


@dataclass
class CertaintyReport:
    """一次采样的置信度报告（top-k 代理，见模块文档）。"""

    #: 所有被采样 token 的 logprob 均值（≤0）
    meanLogprob: float
    #: exp(meanLogprob)：所选 token 的平均概率
    confidence: float
    #: top-k 分布的平均峰度：1 = 每次都几乎确定，0 = 与均匀分布无异
    peakedness: float
    #: 参与统计的 token 数
    tokens: int
    #: 有 top_logprobs 的 token 数（峰度只在这些 token 上算）
    tokensWithTopk: int
    #: 复合分：0.5×confidence + 0.5×peakedness（**我们的合成方式**）
    composite: float
    #: 样本太短 → 信号仅供参考
    thin: bool
    #: 这个分数的来源，避免与论文的 self-certainty 混淆
    kind: str = "topk-proxy"


def certainty_from_logprobs(
    logprobs: Any, *, min_tokens: int = MIN_CERTAINTY_TOKENS
) -> Optional[CertaintyReport]:
    """从 OpenAI 兼容响应的 `choices[0].logprobs` 算置信度；拿不到就返回 None。

    接受两种形状：`{"content": [...]}` 或直接是那个 list。缺字段、类型不对、
    空列表一律返回 None（调用方据此显示"未测量"）。
    """
    content = logprobs
    if isinstance(content, dict):
        content = content.get("content")
    if not isinstance(content, list) or not content:
        return None

    logps: List[float] = []
    peakes: List[float] = []
    for item in content:
        if not isinstance(item, dict):
            continue
        lp = item.get("logprob")
        if isinstance(lp, bool) or not isinstance(lp, (int, float)):
            continue
        lp = float(lp)
        if lp != lp or lp == float("-inf"):  # NaN / -inf
            continue
        logps.append(lp)
        top = item.get("top_logprobs")
        if isinstance(top, list) and len(top) >= 2:
            values: List[float] = []
            for entry in top:
                if isinstance(entry, dict) and isinstance(entry.get("logprob"), (int, float)):
                    values.append(float(entry["logprob"]))
            if len(values) >= 2:
                probs = [math.exp(v) for v in values if v > -700]
                total = sum(probs)
                if total > 0:
                    norm = [p / total for p in probs]
                    entropy = -sum(p * math.log(p) for p in norm if p > 0)
                    ceiling = math.log(len(norm))
                    if ceiling > 0:
                        peakes.append(max(0.0, min(1.0, 1.0 - entropy / ceiling)))
    if not logps:
        return None

    mean_logprob = sum(logps) / len(logps)
    confidence = max(0.0, min(1.0, math.exp(mean_logprob)))
    peakedness = sum(peakes) / len(peakes) if peakes else 0.0
    return CertaintyReport(
        meanLogprob=round(mean_logprob, 4),
        confidence=round(confidence, 4),
        peakedness=round(peakedness, 4),
        tokens=len(logps),
        tokensWithTopk=len(peakes),
        composite=round(0.5 * confidence + 0.5 * peakedness, 4),
        thin=len(logps) < max(1, min_tokens),
    )


def _normalize_text(text: str) -> str:
    return " ".join(str(text or "").split())


def char_ngram_similarity(a: str, b: str, n: int = 3) -> float:
    """两份文本的字符 n-gram Jaccard 相似度（0–1）；两边都太短时用 unigram。"""
    left = _normalize_text(a)
    right = _normalize_text(b)
    if not left or not right:
        return 0.0
    if left == right:
        return 1.0
    size = n if min(len(left), len(right)) >= n else 1
    gram_a = {left[i : i + size] for i in range(len(left) - size + 1)}
    gram_b = {right[i : i + size] for i in range(len(right) - size + 1)}
    if not gram_a or not gram_b:
        return 0.0
    inter = len(gram_a & gram_b)
    union = len(gram_a | gram_b)
    return inter / union if union else 0.0


def consensus_scores(texts: Sequence[str]) -> List[Optional[float]]:
    """每份候选"与其余候选的平均一致度"；**少于 3 份时返回全 None**。

    为什么 N=2 不算：两份之间的相似度对双方是同一个数，排序时会退化成
    "总分相同"，看着像有信号其实没有。这种情况必须在说明里讲清楚。
    """
    rows = list(texts or [])
    if len(rows) < 3:
        return [None] * len(rows)
    out: List[Optional[float]] = []
    for i, text in enumerate(rows):
        others = [char_ngram_similarity(text, other) for j, other in enumerate(rows) if j != i]
        out.append(round(sum(others) / len(others), 4) if others else None)
    return out


def _renormalized(penalties: Dict[str, Optional[float]]) -> Tuple[float, Dict[str, float]]:
    """把可用信号的罚分加权成 0–1 总分；缺席的信号不参与。"""
    active = {k: w for k, w in SIGNAL_WEIGHTS.items() if penalties.get(k) is not None}
    total = sum(active.values())
    if total <= 0:
        return 1.0, {}
    weights = {k: round(w / total, 4) for k, w in active.items()}
    penalty = sum(weights[k] * float(penalties[k]) for k in active)
    return max(0.0, min(1.0, 1.0 - penalty)), weights


def score_variant(
    text: str,
    *,
    problems: Sequence[str] = (),
    certainty: Optional[CertaintyReport] = None,
    consensus: Optional[float] = None,
    max_problems: int = 2,
) -> Dict[str, Any]:
    """给一份候选算分：约束 + 一致性 + 置信度（缺哪条就少哪条，如实标 `None`）。

    `problems` 是确定性检查（`mark_revise.check_replacement`）的结论；一句都没有
    = 0 罚分。
    """
    penalties: Dict[str, Optional[float]] = {
        "constraint": min(1.0, len(list(problems)) / max(1, max_problems)),
        "consensus": None if consensus is None else max(0.0, min(1.0, 1.0 - float(consensus))),
        "certainty": None if certainty is None else max(0.0, min(1.0, 1.0 - certainty.composite)),
    }
    score, weights = _renormalized(penalties)
    return {
        "score": round(score, 4),
        "penalties": {k: (None if v is None else round(float(v), 4)) for k, v in penalties.items()},
        "weights": weights,
        "definedWeights": dict(SIGNAL_WEIGHTS),
        "certainty": None if certainty is None else asdict(certainty),
        "consensus": consensus,
    }


def _signals_note(rows: Sequence[Dict[str, Any]]) -> str:
    """如实列出这次**用了哪些信号、缺了哪些**（缺的要写明原因）。"""
    has_certainty = any(r.get("certainty") for r in rows)
    has_consensus = any(r.get("consensus") is not None for r in rows)
    bits: List[str] = []
    if len(rows) < 3:
        bits.append("候选少于 3 份：没有多数可依，不用一致性信号")
    elif has_consensus:
        bits.append("一致性（与其余候选的平均相似度）")
    if has_certainty:
        thin = [r for r in rows if (r.get("certainty") or {}).get("thin")]
        bits.append(
            "模型自身置信度（top-k 代理）"
            + (f"，其中 {len(thin)} 份样本过短、信号仅供参考" if thin else "")
        )
    else:
        bits.append("模型没有返回 logprobs：置信度信号未测量（不是 0 分）")
    bits.append("确定性检查（长度/专名）")
    return "本次取舍依据：" + "；".join(bits) + "。"


def select_best_variant(rows: Sequence[Dict[str, Any]]) -> Dict[str, Any]:
    """按证据挑一版：返回 winner、排序、分差、是否近似并列，以及取舍说明。

    `rows` 每一项至少要有 `text`；可选 `problems`（确定性检查结论）、
    `certainty`（`CertaintyReport`）、`index`/`temperature` 等透传字段。
    一致性由本函数统一算（调用方不用各自实现一遍）。
    """
    items = [dict(r) for r in (rows or []) if isinstance(r, dict)]
    if not items:
        return {
            "winner": None,
            "winnerIndex": None,
            "ranking": [],
            "margin": 0.0,
            "tie": False,
            "note": "没有可比较的候选。",
        }

    consensus = consensus_scores([str(r.get("text") or "") for r in items])
    scored: List[Dict[str, Any]] = []
    for i, row in enumerate(items):
        evidence = score_variant(
            str(row.get("text") or ""),
            problems=row.get("problems") or (),
            certainty=row.get("certainty"),
            consensus=consensus[i],
        )
        merged = dict(row)
        merged.update(evidence)
        merged["variantIndex"] = i
        scored.append(merged)

    order = sorted(
        range(len(scored)),
        key=lambda i: (
            # 确定性检查有问题的版本排在**无问题版本之后**（对齐
            # `pipeline.candidates.score_candidate` 的"硬错误一票否决"：
            # "跟别人像"这种统计信号不该把一条能确定的问题顶掉）。
            1 if len(scored[i].get("problems") or ()) else 0,
            -float(scored[i].get("score") or 0.0),
            i,
        ),
    )
    ranking = [scored[i] for i in order]
    for position, row in enumerate(ranking, start=1):
        row["rank"] = position
        row["vetoedByProblems"] = bool(len(row.get("problems") or ())) and position > 1
    winner = ranking[0]
    margin = (
        float(winner.get("score") or 0.0) - float(ranking[1].get("score") or 0.0)
        if len(ranking) > 1
        else 0.0
    )
    tie = len(ranking) > 1 and margin < TIE_MARGIN
    # 分差是按分数算的；如果"无问题"这条把顺序改写了，要说清楚（否则作者会看到
    # "总分更低的却赢了"而不知道原因）。
    order_changed_by_veto = any(row.get("vetoedByProblems") for row in ranking)
    if order_changed_by_veto:
        margin = 0.0
        tie = False
    note = _signals_note(ranking)
    if order_changed_by_veto:
        note += " 有版本没通过确定性检查，已排在通过检查的版本之后（不看总分）。"
    if tie:
        note += f" 前两名分差 {margin:.3f}（< {TIE_MARGIN}）：这次没有明显更好的一版，建议都看看。"
    elif len(ranking) == 1:
        note += " 只有一个候选，没有取舍余地。"
    # 结构差异点（非文学评分）
    contrast = contrast_variants([str(r.get("text") or "") for r in ranking])
    by_index = {int(p["index"]): p for p in contrast.get("points") or []}
    for position, row in enumerate(ranking):
        # ranking 已按证据重排；contrast 按重排后的顺序 index
        pt = by_index.get(position) or {}
        row["diffTags"] = list(pt.get("tags") or [])
    note = (note + " " + str(contrast.get("summary") or "")).strip()
    return {
        "winner": winner,
        "winnerIndex": order[0],
        "ranking": ranking,
        "margin": round(margin, 4),
        "tie": tie,
        "note": note,
        "contrast": contrast,
    }


def reason_for_winner(selection: Dict[str, Any]) -> str:
    """给作者看的一句话理由：必须点出**具体依据**，不能只说"分数更高"。"""
    winner = selection.get("winner")
    if not isinstance(winner, dict):
        return str(selection.get("note") or "没有可比较的候选。")
    bits: List[str] = []
    problems = list(winner.get("problems") or ())
    bits.append("确定性检查通过" if not problems else f"确定性检查有 {len(problems)} 处问题")
    if winner.get("consensus") is not None:
        bits.append(f"与其余候选一致度 {float(winner['consensus']):.2f}")
    certainty = winner.get("certainty") or {}
    if isinstance(certainty, dict) and certainty:
        bits.append(
            f"模型置信度 {float(certainty.get('composite') or 0.0):.2f}"
            + ("（样本过短）" if certainty.get("thin") else "")
        )
    return (
        f"第 {int(winner.get('variantIndex', 0)) + 1} 版（按证据优先，非文学最佳）："
        + "、".join(bits)
        + f"，总分 {float(winner.get('score') or 0.0):.2f}"
    )


def _avg_sentence_len(text: str) -> float:
    parts = [p for p in re.split(r"[。！？!?；;\n]+", text or "") if p.strip()]
    if not parts:
        return float(len(text or ""))
    return sum(len(p) for p in parts) / len(parts)


def _dialogue_ratio(text: str) -> float:
    t = text or ""
    if not t:
        return 0.0
    # 「」对白 + 说话人行
    quoted = sum(len(m) for m in re.findall(r"[「『].*?[」』]", t))
    speaker = sum(
        len(m.group(0))
        for m in re.finditer(r"^[^\s:：]{1,12}\s*[:：].+$", t, flags=re.M)
    )
    return min(1.0, (quoted + speaker) / max(1, len(t)))


_ABSTRACT = re.compile(r"仿佛|似乎|好像|不禁|涌上|微微|缓缓|轻轻|心中一动|说不清")


def contrast_variants(texts: Sequence[str]) -> Dict[str, Any]:
    """多变体之间的**可感知结构差异**（不是文学评分）。

    返回每版相对中位数的短标签，供界面并列展示；并列时诚实说「差异不大」。
    """
    cleaned = [str(t or "").strip() for t in texts]
    if len(cleaned) < 2:
        return {"points": [], "summary": "只有一版，没有可对比的差异。"}

    rows: List[Dict[str, Any]] = []
    for i, t in enumerate(cleaned):
        rows.append(
            {
                "index": i,
                "chars": len(t),
                "avgSentence": round(_avg_sentence_len(t), 1),
                "dialogueRatio": round(_dialogue_ratio(t), 3),
                "abstractHits": len(_ABSTRACT.findall(t)),
            }
        )

    def _med(key: str) -> float:
        vals = sorted(float(r[key]) for r in rows)
        mid = len(vals) // 2
        if len(vals) % 2:
            return vals[mid]
        return (vals[mid - 1] + vals[mid]) / 2.0

    med_chars = _med("chars")
    med_sent = _med("avgSentence")
    med_dlg = _med("dialogueRatio")
    med_abs = _med("abstractHits")

    points: List[Dict[str, Any]] = []
    for r in rows:
        tags: List[str] = []
        if med_chars > 0 and abs(r["chars"] - med_chars) / med_chars >= 0.15:
            tags.append("更短" if r["chars"] < med_chars else "更长")
        if med_sent > 0 and abs(r["avgSentence"] - med_sent) / med_sent >= 0.18:
            tags.append("句更短" if r["avgSentence"] < med_sent else "句更长")
        if abs(r["dialogueRatio"] - med_dlg) >= 0.08:
            tags.append("对白更多" if r["dialogueRatio"] > med_dlg else "叙述更多")
        if abs(r["abstractHits"] - med_abs) >= 1.5:
            tags.append(
                "虚写更少" if r["abstractHits"] < med_abs else "虚写更多（仿佛/微微等）"
            )
        points.append({"index": r["index"], "tags": tags, **r})

    tagged = sum(1 for p in points if p["tags"])
    if tagged == 0:
        summary = "各版结构差异不大（字数/句长/对白比接近）；请直接读原文挑选，不作文学排名。"
    else:
        bits = []
        for p in points:
            if not p["tags"]:
                continue
            bits.append(f"第{p['index'] + 1}版：" + "、".join(p["tags"]))
        summary = "结构差异（非文学评分）：" + "；".join(bits)
    return {"points": points, "summary": summary}
