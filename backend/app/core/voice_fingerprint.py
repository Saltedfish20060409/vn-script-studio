"""角色声线指纹：把"这个角色像不像本人"变成可计算的数字。

为什么需要它
------------
在此之前，"角色口吻是否跑偏"只有两条路：作者凭感觉读，或再调一次 LLM 让模型
主观判断（`core/voice_check.py` 就是后者）。前者不可复现，后者不可验证——
两者都答不出"这一章林夏的说话方式偏离了多少"。

这个模块换一条路：**从作者自己已经写好的台词里学出该角色的语言分布**，
再用统计偏离度度量新台词。纯本地计算、不调模型、不用 embedding，
因此能进单元测试、能逐章跑、能在 CI 里当回归量具。

三个量
------
1. ``drift``（0–1）：一段写法偏离该角色自身习惯的程度。各特征层的 z 偏离按权重
   平均，单特征最多记 ``DRIFT_CAP`` 个标准差（防极端值主导）。
2. **阈值自校准**：不设魔法常数，而是用留一法算出该角色**自己台词**的 drift
   分布，取 p90 / p97.5 作为"留意 / 跑偏"的界。多少算偏，由作者自己的文风定。
3. ``distinctiveness``：角色两两声线距离，用来回答"这两个人说话是不是一个味"。

已知边界
--------
- 这是**风格**量具，不是语义量具：抓句长、句子数、逗号密度、语气助词、疑问/感叹/
  省略倾向、敬语；抓不到"说的话不符合人设"（那属于内容层，仍由 LLM 审稿或作者判断）。
- 台词太少的角色（< ``MIN_UTTERANCES``）不给结论，只标 ``ready=False``：
  三五句台词算不出分布，硬算出来的均值没有意义。
"""

from __future__ import annotations

import math
import re
import statistics
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

from app.core.blocks import iter_dialogue
from app.domain.types import VnProject

# ---------------------------------------------------------------- 参数与常量

#: 参与 drift 的特征与权重。权重表达"这个特征有多能说明声线"：
#: 句长/台词长度最能说明节奏，逗号与语气助词次之，纯标点符号倾向再次。
FEATURE_WEIGHTS: Dict[str, float] = {
    "utteranceLen": 1.0,
    "sentenceLen": 1.0,
    "commas": 0.6,
    "softParticle": 0.8,
    "isQuestion": 0.6,
    "isExclaim": 0.6,
    "hasEllipsis": 0.5,
    "politeYou": 0.4,
}

#: 每个特征的最小刻度。角色若从不提问，其 isQuestion 标准差为 0；
#: 不设刻度的话"问了一句话"会算出无穷大的 z。刻度含义是"小于这个差异不算证据"。
FEATURE_FLOORS: Dict[str, float] = {
    "utteranceLen": 3.0,
    "sentenceLen": 2.0,
    "commas": 1.0,
    "softParticle": 0.25,
    "isQuestion": 0.25,
    "isExclaim": 0.25,
    "hasEllipsis": 0.2,
    "politeYou": 0.15,
}

FEATURE_LABELS: Dict[str, str] = {
    "utteranceLen": "台词长度",
    "sentenceLen": "句长",
    "commas": "逗号数",
    "softParticle": "语气助词",
    "isQuestion": "疑问句",
    "isExclaim": "感叹句",
    "hasEllipsis": "省略号",
    "politeYou": "敬语（您）",
}

#: 单个特征最多记 3 个标准差：超过之后"更极端"不再更有意义，只会被离群值带跑。
DRIFT_CAP = 3.0

#: 样本不足时不校准，退回这两个绝对值（仅作兜底，正常路径走稳健统计）。
FALLBACK_WATCH = 0.22
FALLBACK_DRIFT = 0.40

#: 绝对效应下限：**不管统计怎么说**，偏离小于这个值就不值得告诉作者。
#: 为什么必须有它：留一法分布里若混进了"被检测的异常本身"，稳健尺度可能被压到接近 0，
#: 于是任何微小波动都会越过阈值（量具开始喊狼来了）。这两条线是把"统计显著"与
#: "实际值得一读"分开的那道闸。
MIN_WATCH_EFFECT = 0.10
MIN_DRIFT_EFFECT = 0.18

#: MAD → 标准差的换算系数（正态下的一致性因子）。
MAD_TO_SIGMA = 1.4826

MIN_UTTERANCES = 8
"""少于这个台词数就不给结论：分布估计不出来。"""

MIN_CALIBRATION_SAMPLES = 10
"""少于这个数，留一法分位不稳，退回绝对值兜底。"""

MAX_PROFILE_UTTERANCES = 300
"""参与画像与留一法校准的台词上限（超出按章序保留最先出现的那些）。"""

MAX_CALIBRATION_SAMPLES = 120
"""留一法最多算这么多条（超出按确定步长抽样）。

留一法是 O(n²)：不封顶的话，"逐章评估"会退化成 O(章数 × 台词数²)。
抽样是确定性的（等步长），所以同一份稿子每次跑出来的阈值完全一致——
量具必须可复现，否则没法当回归基准。
"""

MIN_CHAPTER_UTTERANCES = 3
"""某角色在一章里至少说这么多句，才评估该章的声线。"""

MAX_FLAGGED_UTTERANCES = 8

# ------------------------------------------------------------------ 文本处理

_WS_RE = re.compile(r"\s+")
#: 连续标点折叠成一个字符：`……` / `！！` 是同一个标点习惯，不该算成长度。
_PUNCT_RUN_RE = re.compile(r"[。！？!?…，,、；;：:~～\-—.·]{2,}")
_SENT_SPLIT_RE = re.compile(r"[。！？!?…]+")
#: 用于"句尾助词"判断：去掉尾部标点后再看最后一个字。
_TRAIL_PUNCT_RE = re.compile(r"[\s。！？!?…，,、；;：:~～\-—.\"'“”「」『』（）()\[\]【】]+$")
_SOFT_PARTICLES = ("吧", "呢", "啊", "哦", "呀", "嘛", "么", "啦", "咯", "哟")
#: 语气助词看**小句末**，不是整句末：`……等了三个小时呢，结果……` 里的"呢"跟在逗号前，
#: 它同样是语气助词。只看句末会把多小句台词里的助词全漏掉。
_SOFT_PARTICLE_RE = re.compile(
    "[" + "".join(_SOFT_PARTICLES) + r"](?=[。！？!?…，,、；;：]|$)"
)
#: n-gram 挖掘前清洗：只留中日文字与字母数字。
_GRAM_CLEAN_RE = re.compile(r"[^\w\u4e00-\u9fff\u3040-\u30ff]+")


def _normalize(text: str) -> str:
    return _WS_RE.sub("", (text or "").strip())


def _collapse_punct(text: str) -> str:
    return _PUNCT_RUN_RE.sub("x", text)


def _sentences(text: str) -> List[str]:
    return [s for s in _SENT_SPLIT_RE.split(text) if s.strip()]


def extract_features(text: str) -> Dict[str, float]:
    """单句台词 → 特征向量。零向量输入返回零向量（句子被丢弃前不应到这里）。"""
    t = _normalize(text)
    if not t:
        return {**{k: 0.0 for k in FEATURE_WEIGHTS}, "sentenceCount": 0.0}
    sents = _sentences(t)
    body = _TRAIL_PUNCT_RE.sub("", t)
    sent_len = (sum(len(s) for s in sents) / len(sents)) if sents else float(len(t))
    return {
        "utteranceLen": float(len(_collapse_punct(t))),
        "sentenceLen": float(sent_len),
        "commas": float(t.count("，") + t.count(",") + t.count("、")),
        "softParticle": 1.0 if _SOFT_PARTICLE_RE.search(t) else 0.0,
        "isQuestion": 1.0 if ("？" in t or "?" in t or body.endswith("吗")) else 0.0,
        "isExclaim": 1.0 if ("！" in t or "!" in t) else 0.0,
        "hasEllipsis": 1.0 if ("…" in t or "..." in t) else 0.0,
        "politeYou": 1.0 if "您" in t else 0.0,
        # 仅用于展示，不参与 drift（否则与句长强相关、重复计权）。
        "sentenceCount": float(len(sents)),
    }


def aggregate_features(vectors: Sequence[Dict[str, float]]) -> Dict[str, float]:
    """特征向量 → 均值向量。"""
    if not vectors:
        return {k: 0.0 for k in FEATURE_WEIGHTS}
    n = float(len(vectors))
    return {
        key: sum(float(v.get(key, 0.0)) for v in vectors) / n for key in FEATURE_WEIGHTS
    }


def feature_scale(vectors: Sequence[Dict[str, float]]) -> Dict[str, float]:
    """特征向量 → 标准差向量（总体标准差；不足两个样本给 0）。"""
    if len(vectors) < 2:
        return {k: 0.0 for k in FEATURE_WEIGHTS}
    out: Dict[str, float] = {}
    for key in FEATURE_WEIGHTS:
        vals = [float(v.get(key, 0.0)) for v in vectors]
        out[key] = float(statistics.pstdev(vals))
    return out


def robust_center(vectors: Sequence[Dict[str, float]]) -> Dict[str, float]:
    """特征向量 → **中位数**向量（画像的中心）。

    为什么不用均值：台词长度是右偏分布，均值本来就被长句拖着走；更要紧的是
    均值对"别处的少数异常"很敏感——如果第 40 章被写走样，它会抬高整个角色的
    平均句长，于是第 40 章看起来"没那么离谱"（异常互相稀释）。
    中位数对少量异常几乎不动，这是把"某个角色像不像他自己"做成可靠量具的前提。
    """
    if not vectors:
        return {k: 0.0 for k in FEATURE_WEIGHTS}
    return {
        key: float(statistics.median([float(v.get(key, 0.0)) for v in vectors]))
        for key in FEATURE_WEIGHTS
    }


def robust_feature_scale(vectors: Sequence[Dict[str, float]]) -> Dict[str, float]:
    """特征向量 → **稳健尺度**向量（1.4826 × MAD）。

    同理：标准差会被少数走样台词撑大，于是"偏离几个标准差"的判定被稀释。
    MAD（绝对中位差）只看分布中间那半，少量异常动不了它。
    返回 0 是正常的（同一角色的台词完全一致），由 ``FEATURE_FLOORS`` 兜底。
    """
    if len(vectors) < 2:
        return {k: 0.0 for k in FEATURE_WEIGHTS}
    out: Dict[str, float] = {}
    for key in FEATURE_WEIGHTS:
        vals = [float(v.get(key, 0.0)) for v in vectors]
        med = statistics.median(vals)
        out[key] = float(MAD_TO_SIGMA * statistics.median([abs(v - med) for v in vals]))
    return out


def _percentile(sorted_vals: Sequence[float], q: float) -> float:
    """线性插值分位（纯 stdlib，避免为几个数字引入 numpy）。"""
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


# ------------------------------------------------------------------ drift 计算


def _drift_parts(
    agg: Dict[str, float],
    mean: Dict[str, float],
    scale: Dict[str, float],
) -> Tuple[float, List[Dict[str, Any]]]:
    """加权平均归一化偏离，同时给出**逐特征的证据**（作者能看到"为什么偏"）。"""
    total_w = 0.0
    acc = 0.0
    parts: List[Dict[str, Any]] = []
    for key, weight in FEATURE_WEIGHTS.items():
        mu = float(mean.get(key, 0.0))
        sd = max(float(scale.get(key, 0.0)), FEATURE_FLOORS[key])
        value = float(agg.get(key, mu))
        z = (value - mu) / sd
        capped = min(abs(z), DRIFT_CAP)
        acc += weight * (capped / DRIFT_CAP)
        total_w += weight
        parts.append(
            {
                "key": key,
                "label": FEATURE_LABELS.get(key, key),
                "value": round(value, 3),
                "mean": round(mu, 3),
                "scale": round(sd, 3),
                "z": round(z, 2),
                "direction": "high" if z > 0.5 else ("low" if z < -0.5 else "flat"),
            }
        )
    score = (acc / total_w) if total_w else 0.0
    parts.sort(key=lambda p: -abs(float(p["z"])))
    return round(score, 4), parts


def _describe(parts: Sequence[Dict[str, Any]]) -> List[str]:
    """把偏离最大的特征写成作者能读的一句话。"""
    out: List[str] = []
    for p in parts:
        if abs(float(p["z"])) < 1.0:
            continue
        way = "偏多/偏长" if float(p["z"]) > 0 else "偏少/偏短"
        out.append(
            f"{p['label']}{way}：本次 {p['value']:g}，平时 {p['mean']:g}（±{p['scale']:g}）"
        )
        if len(out) >= 3:
            break
    return out


# --------------------------------------------------------------- 口癖（n-gram）


def gram_counts(texts: Iterable[str], *, cap_chars: int = 20000) -> Tuple[Dict[str, int], int]:
    """句内 2–4 字 n-gram 计数 + 总槽数。

    只在**句内**取 gram：跨句拼接会造出"我。你"这种不存在的组合。
    """
    counts: Dict[str, int] = {}
    slots = 0
    budget = cap_chars
    for text in texts:
        for sent in _sentences(_normalize(text)):
            s = _GRAM_CLEAN_RE.sub("", sent)
            if len(s) < 2:
                continue
            if len(s) > budget:
                s = s[:budget]
            budget -= len(s)
            for n in (2, 3, 4):
                if len(s) < n:
                    continue
                slots += len(s) - n + 1
                for i in range(len(s) - n + 1):
                    g = s[i : i + n]
                    counts[g] = counts.get(g, 0) + 1
            if budget <= 0:
                return counts, slots
    return counts, slots


def mine_signature_phrases(
    counts: Dict[str, int],
    slots: int,
    other_counts: Sequence[Tuple[Dict[str, int], int]],
    *,
    exclude_terms: Sequence[str] = (),
    min_count: int = 3,
    min_distinct: float = 2.0,
    limit: int = 12,
) -> List[Dict[str, Any]]:
    """挑出"这个角色用得多、别人用得少"的说法（口癖 / 语言习惯）。

    判别度用**逐角色的平均占比**做分母，而不是"其他人的合并占比"：
    主角往往占全剧 70% 台词，合并占比会把"的时候"这种通用词判成主角的口癖。
    按角色占比取平均后，通用词在谁那儿占比都差不多 → 判别度≈1，自然被滤掉。
    """
    if slots <= 0:
        return []
    rows: List[Dict[str, Any]] = []
    for gram, c_self in counts.items():
        if c_self < min_count:
            continue
        if any(term and term in gram for term in exclude_terms):
            continue
        share_self = c_self / slots
        others = [
            (c.get(gram, 0) / s) for c, s in other_counts if s > 0
        ]
        mean_other = (sum(others) / len(others)) if others else 0.0
        distinct = share_self / (mean_other + 1e-6)
        if distinct < min_distinct:
            continue
        rows.append(
            {
                "phrase": gram,
                "count": c_self,
                "sharePerMille": round(share_self * 1000, 2),
                "distinctiveness": round(distinct, 2),
                "othersSharePerMille": round(mean_other * 1000, 2),
            }
        )
    # 排名：出现次数 × 判别度（判别度封顶 10，避免只出现 3 次的怪词霸榜）
    rows.sort(key=lambda r: (-(r["count"] * min(r["distinctiveness"], 10.0)), -len(r["phrase"])))

    # 抑制被更长 gram 覆盖的短 gram（"的话" vs "的话说" 同时出现时只留信息更多的）
    picked: List[Dict[str, Any]] = []
    for row in rows:
        covered = any(
            row["phrase"] in kept["phrase"] and kept["count"] >= row["count"]
            for kept in picked
        )
        if covered:
            continue
        picked.append(row)
        if len(picked) >= limit:
            break
    return picked


# ---------------------------------------------------------------------- 画像


def _cast_index(project: VnProject) -> Dict[str, Dict[str, Any]]:
    """角色 id → {texts, byChapter, chapters}；一次性遍历供全体角色复用。"""
    index: Dict[str, Dict[str, Any]] = {}
    for cid, char_id, text in iter_dialogue(project):
        if not char_id:
            continue
        row = index.setdefault(char_id, {"texts": [], "byChapter": {}})
        row["texts"].append(text)
        row["byChapter"].setdefault(cid, []).append(text)
    return index


def _name_terms(project: VnProject, character_id: str) -> List[str]:
    """该角色的一切叫法（用于从口癖候选里剔除"喊自己名字"）。"""
    for c in project.characters or []:
        if str(c.id) != str(character_id):
            continue
        terms = [c.displayName or "", c.defineName or "", str(c.id)]
        terms.extend(c.aliases or [])
        out = []
        for t in terms:
            t = str(t or "").strip()
            if len(t) >= 2:
                out.append(t)
        return out
    return []


def _all_cast_names(project: VnProject) -> List[str]:
    out: List[str] = []
    for c in project.characters or []:
        for t in [c.displayName, c.defineName, *(c.aliases or [])]:
            t = str(t or "").strip()
            if len(t) >= 2:
                out.append(t)
    return out


def _character(project: VnProject, character_id: str) -> Optional[Any]:
    for c in project.characters or []:
        if str(c.id) == str(character_id):
            return c
    return None


def _sample_strided(items: List[Any], cap: int) -> List[Any]:
    """确定性等步长抽样：同一输入永远抽到同一批（量具要可复现）。"""
    if len(items) <= cap or cap <= 0:
        return list(items)
    step = len(items) / float(cap)
    return [items[int(i * step)] for i in range(cap)]


def _loo_drift_scores(vectors: Sequence[Dict[str, float]], cap: int) -> List[float]:
    """留一法 drift 分布：每条台词都被"其余台词"构成的画像评分。

    不封顶的话单次 O(n²)；分层抽样后上限是 ``cap × n``。
    """
    if len(vectors) < 3:
        return []
    total = len(vectors)
    picked = _sample_strided(list(range(total)), cap)
    out: List[float] = []
    for i in picked:
        rest = vectors[:i] + vectors[i + 1 :]
        if len(rest) < 2:
            continue
        # 零分布也用稳健中心/尺度：否则"别处的异常"会同时抬高参考与阈值，
        # 让本该被抓住的那一章显得正常。
        score, _ = _drift_parts(
            vectors[i], robust_center(rest), robust_feature_scale(rest)
        )
        out.append(score)
    return out


def build_voice_profile(
    project: VnProject,
    character_id: str,
    *,
    cast_index: Optional[Dict[str, Dict[str, Any]]] = None,
    min_utterances: int = MIN_UTTERANCES,
    exclude_chapters: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """单角色画像（JSON 可序列化）。含自校准阈值与口癖列表。

    ``exclude_chapters`` 用于**留一章法**：评估某一章时，画像必须由其余章节构成。
    否则被评估的那一章自己参与了均值与阈值，越跑偏的章越会把自己的阈值抬高，
    结果是"写得越离谱越判不出来"——这正是旧版一致性检查的毛病，不能再犯一遍。
    """
    index = cast_index if cast_index is not None else _cast_index(project)
    row = index.get(str(character_id)) or {}
    skip = {str(c) for c in (exclude_chapters or ())}
    texts: List[str] = list(row.get("texts") or [])
    by_chapter: Dict[str, List[str]] = {
        str(k): list(v) for k, v in (row.get("byChapter") or {}).items() if str(k) not in skip
    }
    ref_texts: List[str] = [t for cid, vals in by_chapter.items() for t in vals]
    if not skip:
        ref_texts = texts
    char = _character(project, character_id)
    display = (char.displayName if char else None) or str(character_id)

    kept = ref_texts[:MAX_PROFILE_UTTERANCES]
    vectors = [extract_features(t) for t in kept]

    profile: Dict[str, Any] = {
        "characterId": str(character_id),
        "displayName": display,
        "utteranceCount": len(texts),
        "sampleSize": len(ref_texts),
        "chaptersSpoken": len(by_chapter),
        "ready": len(kept) >= min_utterances,
        # 中心用中位数、尺度用 MAD：见 robust_center / robust_feature_scale 的说明。
        "aggregate": robust_center(vectors),
        "scale": robust_feature_scale(vectors),
        "signaturePhrases": [],
        "calibration": {"calibrated": False, "samples": 0},
        "sampleLines": [t[:80] for t in kept[:3]],
    }

    # 口癖：与全体其他角色对比（用同一批参考台词，保持与均值同源）
    counts, slots = gram_counts(kept)
    others: List[Tuple[Dict[str, int], int]] = []
    for other_id, other_row in index.items():
        if str(other_id) == str(character_id):
            continue
        other_texts = [
            t
            for cid, vals in (other_row.get("byChapter") or {}).items()
            if str(cid) not in skip
            for t in vals
        ]
        if not skip:
            other_texts = list(other_row.get("texts") or [])
        oc, os_ = gram_counts(other_texts[:MAX_PROFILE_UTTERANCES])
        if os_ > 0:
            others.append((oc, os_))
    profile["signaturePhrases"] = mine_signature_phrases(
        counts,
        slots,
        others,
        exclude_terms=[*_all_cast_names(project), *_name_terms(project, character_id)],
    )

    if not profile["ready"]:
        return profile

    # —— 自校准：留一法 —— 用"角色自己的台词"建零分布，避免自己把自己拉平
    loo = sorted(_loo_drift_scores(vectors, MAX_CALIBRATION_SAMPLES))
    robust = _robust_thresholds(loo)
    if len(loo) >= MIN_CALIBRATION_SAMPLES:
        profile["calibration"] = {
            "calibrated": True,
            "samples": len(loo),
            "p50": round(_percentile(loo, 0.50), 4),
            "p90": round(_percentile(loo, 0.90), 4),
            "p975": round(_percentile(loo, 0.975), 4),
            "max": round(loo[-1], 4),
            **robust,
        }
    else:
        profile["calibration"] = {
            "calibrated": False,
            "samples": len(loo),
            "p50": round(_percentile(loo, 0.50), 4) if loo else 0.0,
            "p90": FALLBACK_WATCH,
            "p975": FALLBACK_DRIFT,
            **robust,
        }
    return profile


def _median(values: Sequence[float]) -> float:
    if not values:
        return 0.0
    return float(statistics.median(values))


def _robust_thresholds(loo: Sequence[float]) -> Dict[str, Any]:
    """从留一法 drift 分布里定阈值——用**稳健统计**，不用高分位。

    为什么不能用 p97.5 当阈值：留一法分布是用角色**自己的台词**建的，其中可能就混着
    我们想检测的那些异常（一部 60 章的作品里可能有 2–3 章走样）。高分位会落在异常簇里，
    于是"异常越多 → 阈值越高 → 越检测不出来"——正好反了。基准测试实测到了这一点：
    两处声线走样时，走样章自己的 drift 反而被抬高的阈值判成 watch。

    改用 中位数 + MAD 的稳健尺度（少数异常几乎不影响这两个量），再抬两条绝对下限
    （`MIN_WATCH_EFFECT` / `MIN_DRIFT_EFFECT`）挡住"稳健尺度趋近 0 导致微小波动也报警"。
    分位仍然保留在结果里，供展示与排查，但**不参与判定**。
    """
    if not loo:
        return {
            "watchThreshold": FALLBACK_WATCH,
            "driftThreshold": FALLBACK_DRIFT,
            "median": 0.0,
            "mad": 0.0,
            "robustScale": 0.0,
        }
    med = _median(loo)
    mad = _median([abs(v - med) for v in loo])
    robust = MAD_TO_SIGMA * mad
    watch = max(MIN_WATCH_EFFECT, med + 2.0 * robust)
    drift = max(MIN_DRIFT_EFFECT, med + 3.0 * robust)
    if drift <= watch:
        drift = watch * 1.25
    return {
        "watchThreshold": round(watch, 4),
        "driftThreshold": round(drift, 4),
        "median": round(med, 4),
        "mad": round(mad, 4),
        "robustScale": round(robust, 4),
    }


def _thresholds(profile: Dict[str, Any]) -> Tuple[float, float]:
    cal = profile.get("calibration") or {}
    watch = float(cal.get("watchThreshold") or FALLBACK_WATCH)
    drift = float(cal.get("driftThreshold") or FALLBACK_DRIFT)
    if drift <= watch:
        drift = watch * 1.25
    return watch, drift


def _level(score: float, watch: float, drift: float) -> str:
    if score >= drift:
        return "drift"
    if score >= watch:
        return "watch"
    return "ok"


def score_voice(
    profile: Dict[str, Any],
    texts: Sequence[str],
    *,
    chapter_id: Optional[str] = None,
    flag_limit: int = MAX_FLAGGED_UTTERANCES,
) -> Dict[str, Any]:
    """把一批台词（通常是一章里该角色的全部台词）与该角色画像比对。"""
    cleaned = [t for t in (str(x or "").strip() for x in texts) if t]
    if not profile.get("ready") or not cleaned:
        return {
            "characterId": profile.get("characterId"),
            "displayName": profile.get("displayName"),
            "chapterId": chapter_id,
            "utteranceCount": len(cleaned),
            "ready": False,
            "reason": "样本不足" if not profile.get("ready") else "本章无台词",
        }

    vectors = [extract_features(t) for t in cleaned]
    agg = aggregate_features(vectors)
    score, parts = _drift_parts(agg, profile.get("aggregate") or {}, profile.get("scale") or {})
    watch, drift = _thresholds(profile)
    level = _level(score, watch, drift)

    # 逐句：与完整画像比（单句层面不做留一，画像才是参照物）
    per_line: List[Dict[str, Any]] = []
    for text, vec in zip(cleaned, vectors):
        s, p = _drift_parts(vec, profile.get("aggregate") or {}, profile.get("scale") or {})
        per_line.append({"text": text[:120], "drift": s, "top": _describe(p)[:1]})
    flagged = sorted(per_line, key=lambda r: -float(r["drift"]))[:flag_limit]
    flagged = [r for r in flagged if r["drift"] >= watch]

    phrases = [p["phrase"] for p in (profile.get("signaturePhrases") or [])]
    joined = "\n".join(cleaned)
    hits = [p for p in phrases if p in joined]

    return {
        "characterId": profile.get("characterId"),
        "displayName": profile.get("displayName"),
        "chapterId": chapter_id,
        "ready": True,
        "utteranceCount": len(cleaned),
        "drift": score,
        "level": level,
        "watchThreshold": round(watch, 4),
        "driftThreshold": round(drift, 4),
        "reasons": _describe(parts),
        "features": parts,
        "signatureHits": hits,
        "missingSignatures": [p for p in phrases if p not in hits][:6],
        "flaggedLines": [
            {"text": r["text"], "drift": r["drift"], "reason": (r["top"] or [""])[0]}
            for r in flagged
        ],
    }


def profile_distance(a: Dict[str, Any], b: Dict[str, Any]) -> float:
    """两个角色画像的声线距离（0–1，越大越不像）。"""
    if not a.get("ready") or not b.get("ready"):
        return 0.0
    pooled: Dict[str, float] = {}
    for key in FEATURE_WEIGHTS:
        pooled[key] = max(
            float((a.get("scale") or {}).get(key, 0.0)),
            float((b.get("scale") or {}).get(key, 0.0)),
            FEATURE_FLOORS[key],
        )
    score, _ = _drift_parts(a.get("aggregate") or {}, b.get("aggregate") or {}, pooled)
    return score


def analyze_voices(
    project: VnProject,
    *,
    character_ids: Optional[Sequence[str]] = None,
    min_utterances: int = MIN_UTTERANCES,
) -> Dict[str, Any]:
    """全项目声线体检：逐角色画像 + 逐章漂移 + 角色间可混淆度。"""
    index = _cast_index(project)
    ids = [str(c) for c in (character_ids or [])] or list(index.keys())
    profiles: Dict[str, Dict[str, Any]] = {
        cid: build_voice_profile(
            project, cid, cast_index=index, min_utterances=min_utterances
        )
        for cid in ids
    }

    character_reports: List[Dict[str, Any]] = []
    for cid, profile in profiles.items():
        if not profile.get("ready"):
            character_reports.append(
                {
                    "characterId": cid,
                    "displayName": profile.get("displayName"),
                    "ready": False,
                    "utteranceCount": profile.get("utteranceCount", 0),
                    "reason": f"台词不足 {min_utterances} 句，不评估声线",
                }
            )
            continue
        by_chapter: Dict[str, List[str]] = dict(
            (index.get(cid) or {}).get("byChapter") or {}
        )
        chapter_rows: List[Dict[str, Any]] = []
        for ch_id, texts in by_chapter.items():
            if len(texts) < MIN_CHAPTER_UTTERANCES:
                continue
            # 留一章法：参照画像只由**其它章节**构成，被评估的这一章不参与建模。
            ref = build_voice_profile(
                project,
                cid,
                cast_index=index,
                min_utterances=min_utterances,
                exclude_chapters={ch_id},
            )
            r = score_voice(ref, texts, chapter_id=ch_id)
            if r.get("ready"):
                chapter_rows.append(r)
        chapter_rows.sort(key=lambda r: -float(r["drift"]))
        character_reports.append(
            {
                "characterId": cid,
                "displayName": profile.get("displayName"),
                "ready": True,
                "utteranceCount": profile["utteranceCount"],
                "chaptersSpoken": profile["chaptersSpoken"],
                "calibration": profile["calibration"],
                "signaturePhrases": profile["signaturePhrases"],
                "averageFeatures": {
                    k: round(v, 3) for k, v in (profile["aggregate"] or {}).items()
                },
                "chapters": chapter_rows[:6],
                "driftChapters": [
                    r["chapterId"] for r in chapter_rows if r.get("level") == "drift"
                ],
            }
        )

    # 角色间可混淆度：距离越小越"一个味"
    pairs: List[Dict[str, Any]] = []
    ready_ids = [cid for cid, p in profiles.items() if p.get("ready")]
    for i, a in enumerate(ready_ids):
        for b in ready_ids[i + 1 :]:
            d = profile_distance(profiles[a], profiles[b])
            pairs.append(
                {
                    "a": profiles[a].get("displayName"),
                    "b": profiles[b].get("displayName"),
                    "aId": a,
                    "bId": b,
                    "distance": d,
                }
            )
    pairs.sort(key=lambda r: float(r["distance"]))
    confusion = [p for p in pairs if p["distance"] < 0.15]

    return {
        "characters": character_reports,
        "closestPairs": pairs[:5],
        "confusablePairs": confusion,
        "notes": [
            "drift 由留一法自校准（阈值 = 该角色自己台词分布的 p90 / p97.5）",
            "只看风格（句长/节奏/助词/语气倾向），不看内容是否符合人设",
            f"台词少于 {min_utterances} 句的角色不评估",
        ],
    }
