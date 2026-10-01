"""正文资产：改稿"不该删掉的东西"的确定性计量。

为什么需要它
------------
`pipeline.rewrite_contract` 把"信息只增不减"写成了硬契约，但在此之前**删掉是免费的**：
打分表里只有罚分项（体检 warn / 节拍缺失 / 声线偏离 / AI 味 / 长度），删字能让每一项都变好，
而"删掉了什么"没有任何一项在管。于是"把整场戏删掉"成了最优解——第一章那顿晚饭就是这么没的，
`chapter_revise` 的 `SMOOTH_SYSTEM` 甚至写着"正文刚被规则删掉若干说明书段落"。

这里把资产变成可计量的，形状与既有的量具保持一致：**确定性、不调模型、同一输入同一结论**。

两条设计上的克制
----------------
1. **只在有原稿可比时计量**（改稿、多变体挑选）。生成侧（best-of-N 新写一段）没有原稿，
   硬给"资产分"会奖励废话——多写字数并不等于多给信息。那种场景这一项**缺席**，
   由 `candidates._weighted_score` 本来就在的规矩（缺席项不参与、权重重新归一化）自动摘掉。
2. **只量结构信号，不猜语义**。它抓的是"整场被删"，不抓"单句被压缩"——
   后者需要语义判断，那属于人类或审稿模型，不属于这里。宁可量得粗，也不要量出一个
   看起来精确、其实是编的分数。
"""
from __future__ import annotations

import re
from typing import Any, Dict, Iterable, List, Optional, Sequence, Tuple

#: 括号动作/旁白：VN 剧本里 `（他退出去，把门带上——没关严。）`
_ACTION_RE = re.compile(r"[（(][^）)]{1,80}[）)]")
#: 对白：`她：「热的。」` / `「……」`
_DIALOGUE_RE = re.compile(r"[「『][^」』]{1,200}[」』]")
#: 问句：问号收尾的行
_QUESTION_RE = re.compile(r"[？?]")
#: 专有名词：书名号 + 拉丁词（角色名由调用方另外传入）
_BOOK_RE = re.compile(r"《[^》]{1,40}》")
_LATIN_RE = re.compile(r"[A-Za-z]{2,}")

#: 参与计量的信号。`proper` 是集合，其余是计数。
_COUNT_SIGNALS = ("actions", "dialogues", "questions")
_SIGNAL_LABELS = {
    "actions": "括号动作/旁白",
    "dialogues": "对白",
    "questions": "问句",
    "proper": "专有名词",
}


def _lines(text: str) -> List[str]:
    return [ln.strip() for ln in (text or "").splitlines() if ln.strip()]


def extract_assets(
    text: str,
    *,
    names: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """量一份正文的结构资产。纯函数，同一输入同一结论。"""
    body = text or ""
    name_list = [str(n).strip() for n in (names or []) if str(n or "").strip()]
    proper: set = set(_BOOK_RE.findall(body)) | set(_LATIN_RE.findall(body))
    for n in name_list:
        if n in body:
            proper.add(n)
    return {
        "actions": len(_ACTION_RE.findall(body)),
        "dialogues": len(_DIALOGUE_RE.findall(body)),
        "questions": len(_QUESTION_RE.findall(body)),
        "proper": proper,
        "lines": len(_lines(body)),
        "chars": len(body),
    }


def asset_preservation(
    before: str,
    after: str,
    *,
    names: Optional[Iterable[str]] = None,
) -> Dict[str, Any]:
    """原稿 → 改稿 的资产保留情况。

    返回 ``loss``（0 = 一点没丢，1 = 最惨的那项全丢）与 ``worst``（哪一项最惨），
    外加人可读的 ``note``。**只罚丢，不奖多**：`after` 比 `before` 多不算加分，
    那属于长度项的事。
    """
    src = extract_assets(before, names=names)
    dst = extract_assets(after, names=names)

    ratios: Dict[str, Optional[float]] = {}
    for key in _COUNT_SIGNALS:
        base = int(src[key])
        if base <= 0:
            ratios[key] = None  # 原稿本来就没有这一项 → 不参与
            continue
        ratios[key] = min(1.0, int(dst[key]) / base)

    src_proper = set(src["proper"])
    lost_proper = sorted(src_proper - set(dst["proper"]))
    ratios["proper"] = None if not src_proper else 1.0 - len(lost_proper) / len(src_proper)

    measured = {k: v for k, v in ratios.items() if v is not None}
    if measured:
        worst = min(measured, key=lambda k: (measured[k], k))
        loss = round(max(0.0, 1.0 - float(measured[worst])), 4)
    else:
        worst = ""
        loss = 0.0

    drops = {
        k: int(src[k]) - int(dst[k])
        for k in _COUNT_SIGNALS
        if int(src[k]) - int(dst[k]) > 0
    }
    bits: List[str] = []
    for key, drop in sorted(drops.items(), key=lambda kv: -kv[1]):
        bits.append(f"{_SIGNAL_LABELS[key]}少 {drop}（{src[key]}→{dst[key]}）")
    if lost_proper:
        shown = "、".join(lost_proper[:4])
        more = f" 等 {len(lost_proper)} 个" if len(lost_proper) > 4 else ""
        bits.append(f"丢了专名：{shown}{more}")

    return {
        "loss": loss,
        "worst": worst,
        "worstLabel": _SIGNAL_LABELS.get(worst, ""),
        "ratios": {k: (None if v is None else round(float(v), 4)) for k, v in ratios.items()},
        "before": {k: (src[k] if k != "proper" else sorted(src["proper"])) for k in (*_COUNT_SIGNALS, "proper")},
        "after": {k: (dst[k] if k != "proper" else sorted(dst["proper"])) for k in (*_COUNT_SIGNALS, "proper")},
        "note": "；".join(bits),
    }


def asset_problems(
    before: str,
    after: str,
    *,
    names: Optional[Iterable[str]] = None,
    max_loss: float = 0.34,
) -> List[str]:
    """把明显的资产流失转成"确定性检查的问题句"（喂给 `variant_select` 的约束轴）。

    阈值 0.34：三成以上的对白/动作/问句没了，就不是"措辞变紧"，而是"内容被删"。
    低于它不报——改稿本来就允许把两句并成一句，报出来只会变成噪声。
    """
    out: List[str] = []
    if not (after or "").strip():
        return out  # 空稿由各自的"结果为空"检查负责
    report = asset_preservation(before, after, names=names)
    if report["loss"] > max_loss and report["note"]:
        out.append(f"改稿删掉了原稿的内容（{report['note']}）")
    return out


# ---------------------------------------------------------------- 逐字重合度
#
# 上面量的是**信息类别**有没有少；下面量的是**逐字重合度**。两个别混用：
#
# - 改稿删了几句台词 → `asset_preservation` 会掉，`text_preservation` 也会掉；
# - **整章重写** → `asset_preservation` 可能完全正常（对白还是那么多、专名一个没丢），
#   而 `text_preservation` 会掉到个位数百分比。
#
# 线上那次（《拟合少女》第一章，作者「搁浅de咸鱼」）就是第二种：模型自述"按你的决定
# 改了 7 处"，实际动的是 `replace_script`，203 个段落里只有 10 个逐字留了下来（**5%**）。
# 只看前者会得出"信息没丢、没问题"的错误结论。

REWRITE_LOSS_THRESHOLD = 0.5
"""逐字保留率低于它，就认为这**不是"改了几处"，而是"整章重写"**。

0.5 是保守取法：定点改几处时，正常会保留八九成；整章重写则掉到一成以下。
中间地带（大面积重排但保留了骨架）不报警——那种情况本来就需要人来判断。
"""


def text_preservation(before: str, after: str) -> Dict[str, Any]:
    """原有段落有多少**逐字**还在改稿里（按行比对，确定性、不猜语义）。"""
    src = [ln.strip() for ln in (before or "").splitlines() if ln.strip()]
    body = after or ""
    kept = [ln for ln in src if ln in body]
    total = len(src)
    return {
        "beforeLines": total,
        "keptLines": len(kept),
        "lostLines": total - len(kept),
        "ratio": 1.0 if total == 0 else round(len(kept) / total, 4),
    }


def rewrite_loss_note(before: str, after: str) -> Optional[str]:
    """整章替换的**就**读：丢得太多时给作者一句实话，阈值以上返回 `None`。

    样本太小（原文不到 5 段）不报：那点量算出来的比例没有意义。
    """
    report = text_preservation(before, after)
    if report["beforeLines"] < 5 or report["ratio"] >= REWRITE_LOSS_THRESHOLD:
        return None
    pct = round(float(report["ratio"]) * 100)
    return (
        f"这是整章替换：原有 {report['beforeLines']} 段里只有 "
        f"{report['keptLines']} 段逐字留了下来（{pct}%）。"
        "只想改几处的话，用 patch_script 定点改——其余正文一个字都不会动"
    )
