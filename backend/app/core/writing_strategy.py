"""写作策略档：按注意力 / 记忆 / 推理短板调节硬锚注入与 framing。

与 ``execution_profile``（sync/streamed 超时预算）正交：这里管的是「补短板」，
不是「客户端在不在看着」。

档位可由请求体静态解析，也可由本场守卫 / probe 信号**抬升**（闭环）。
档位含义：``low`` = 外部多补；``high`` = 少干预。
"""

from __future__ import annotations

from contextvars import ContextVar
from dataclasses import dataclass
from typing import Any, Dict, List, Literal, Optional, Tuple

Tier = Literal["low", "mid", "high"]
AssistStrength = Literal["strong", "mid", "weak"]

#: 写作辅助强度 → 注意力/记忆档（reasoning 默认 mid，仅 strong 时降为 low）
_ASSIST_MAP: Dict[str, Dict[str, Tier]] = {
    "strong": {"attention": "low", "memory": "low", "reasoning": "low"},
    "mid": {"attention": "mid", "memory": "mid", "reasoning": "mid"},
    "weak": {"attention": "high", "memory": "high", "reasoning": "high"},
}

_TIER_STRENGTHEN: Dict[Tier, Tier] = {"high": "mid", "mid": "low", "low": "low"}
_ASSIST_ORDER: Tuple[AssistStrength, ...] = ("weak", "mid", "strong")


@dataclass(frozen=True)
class WritingStrategyProfile:
    """档位含义：low = 外部多补；high = 少干预。"""

    attention: Tier = "low"
    memory: Tier = "low"
    reasoning: Tier = "mid"


DEFAULT_PROFILE = WritingStrategyProfile()

_profile: ContextVar[WritingStrategyProfile] = ContextVar(
    "writing_strategy_profile", default=DEFAULT_PROFILE
)


def _norm_tier(value: Optional[str], *, default: Tier) -> Tier:
    v = (value or "").strip().lower()
    if v in ("low", "mid", "high"):
        return v  # type: ignore[return-value]
    return default


def profile_from_assist(strength: Optional[str]) -> WritingStrategyProfile:
    """``strong|mid|weak`` → WritingStrategyProfile。"""
    key = (strength or "").strip().lower() or "strong"
    mapped = _ASSIST_MAP.get(key) or _ASSIST_MAP["strong"]
    return WritingStrategyProfile(
        attention=mapped["attention"],
        memory=mapped["memory"],
        reasoning=mapped["reasoning"],
    )


def resolve_writing_strategy(
    *,
    writing_assist: Optional[str] = None,
    attention: Optional[str] = None,
    memory: Optional[str] = None,
    reasoning: Optional[str] = None,
) -> WritingStrategyProfile:
    """解析顺序：显式维度覆盖 > writing_assist 映射 > 默认（补短板）。"""
    base = (
        profile_from_assist(writing_assist)
        if (writing_assist or "").strip()
        else DEFAULT_PROFILE
    )
    return WritingStrategyProfile(
        attention=_norm_tier(attention, default=base.attention),
        memory=_norm_tier(memory, default=base.memory),
        reasoning=_norm_tier(reasoning, default=base.reasoning),
    )


def set_writing_strategy(profile: WritingStrategyProfile) -> WritingStrategyProfile:
    _profile.set(profile)
    return profile


def current_writing_strategy() -> WritingStrategyProfile:
    return _profile.get()


def reset_writing_strategy() -> None:
    _profile.set(DEFAULT_PROFILE)


#: 硬锚块字符预算（含开闭标签）；超出时从尾部砍行，保留最高优先级条目。
CRITICAL_ANCHOR_BUDGET_CHARS = 720
CRITICAL_ANCHOR_TOP_K = 5
CRITICAL_ANCHOR_OPEN = "<important>"
CRITICAL_ANCHOR_CLOSE = "</important>"


def _fit_anchor_lines(lines: List[str], *, budget: int, open_tag: str, close_tag: str, head: str) -> List[str]:
    """按预算从前往后装行；装不下就停（前面是更高优先级）。"""
    fixed = len(open_tag) + len(close_tag) + len(head) + 3  # newlines
    kept: List[str] = []
    used = fixed
    for line in lines:
        cost = len(line) + 1
        if kept and used + cost > budget:
            break
        if not kept and used + cost > budget:
            # 至少留一行截断版
            room = max(24, budget - used - 1)
            kept.append(line[:room] + ("…" if len(line) > room else ""))
            break
        kept.append(line)
        used += cost
    return kept


def critical_anchors_block(
    ledger: Dict[str, Any],
    *,
    top_k: int = CRITICAL_ANCHOR_TOP_K,
    chapters: Optional[List[Any]] = None,
    budget_chars: int = CRITICAL_ANCHOR_BUDGET_CHARS,
) -> str:
    """注意力低分：把最高相关硬锚前置为「必须遵守」块。

    取未回收伏笔（按章龄）+ 最近角色状态，各取若干条合成 top_k。
    两侧加 ``<important>`` 标签，并受 ``budget_chars`` 字符预算约束。
    """
    from app.core.pipeline.ledger import _foreshadow_rows

    k = max(1, int(top_k))
    lines: List[str] = []
    fores = [x for x in (ledger.get("foreshadows") or []) if x.get("status") != "paid"]
    if fores:
        ages = {
            str(f.get("id")): f.get("ageChapters")
            for f in _foreshadow_rows(ledger, chapters)
        }

        def _age(fo: Dict[str, Any]) -> int:
            a = ages.get(str(fo.get("id")))
            return a if isinstance(a, int) else -1

        for fo in sorted(fores, key=_age, reverse=True)[: max(1, k // 2 + 1)]:
            hook = fo.get("hook") or fo.get("id")
            age = ages.get(str(fo.get("id")))
            age_bit = (
                f"（已埋 {age} 章未回收）"
                if isinstance(age, int) and age >= 3
                else ""
            )
            lines.append(f"- 未回收伏笔：{hook}{age_bit}")

    states = list(ledger.get("characterStates") or [])[-8:]
    for s in reversed(states):
        if len(lines) >= k:
            break
        name = s.get("characterName") or s.get("characterId") or "?"
        emotion = s.get("emotion") or "—"
        body = s.get("body") or "—"
        lines.append(f"- 角色状态：{name} 情={emotion}；身={body}")

    if not lines:
        return ""
    body_lines = lines[:k]
    head = "【必须遵守 · 本轮关键硬锚】生成前请先确认，勿推翻："
    budget = max(120, int(budget_chars))
    fitted = _fit_anchor_lines(
        body_lines,
        budget=budget,
        open_tag=CRITICAL_ANCHOR_OPEN,
        close_tag=CRITICAL_ANCHOR_CLOSE,
        head=head,
    )
    if not fitted:
        return ""
    return (
        f"{CRITICAL_ANCHOR_OPEN}\n"
        f"{head}\n"
        + "\n".join(fitted)
        + f"\n{CRITICAL_ANCHOR_CLOSE}"
    )


def memory_snapshot_preface(ledger: Dict[str, Any]) -> str:
    """记忆力低分：强调「截至本章」的角色状态快照，而非完整小传。"""
    states = list(ledger.get("characterStates") or [])
    if not states:
        return ""
    # 每人保留最新一条
    latest: Dict[str, Dict[str, Any]] = {}
    for s in states:
        key = str(s.get("characterName") or s.get("characterId") or "")
        if key:
            latest[key] = s
    if not latest:
        return ""
    lines = ["【截至本章 · 角色状态快照】以下为当前有效状态，勿使用过期设定："]
    for name, s in list(latest.items())[:10]:
        lines.append(
            f"- {name}：情={s.get('emotion') or '—'}；"
            f"身={s.get('body') or '—'}；关系={s.get('relations') or '—'}"
        )
    return "\n".join(lines)


def reasoning_framing_extra(write_op: str) -> str:
    """推理低分：continue/rewrite 时要求先列节拍再写。"""
    op = (write_op or "continue").strip() or "continue"
    if op not in ("continue", "rewrite"):
        return ""
    return (
        "【本轮 reasoning=low · 分步】先用两三行列出本章/本段 3 个节拍"
        "（目标→转折→收束），再写对白与旁白；不要跳步直接成稿。\n"
    )


def apply_strategy_to_ledger_block(
    ledger_block: str,
    ledger: Dict[str, Any],
    *,
    profile: Optional[WritingStrategyProfile] = None,
    chapters: Optional[List[Any]] = None,
) -> str:
    """按策略档增强账本注入块（前置关键锚 / 状态快照）。"""
    prof = profile or current_writing_strategy()
    parts: List[str] = []
    if prof.attention == "low":
        crit = critical_anchors_block(
            ledger, top_k=CRITICAL_ANCHOR_TOP_K, chapters=chapters
        )
        if crit:
            parts.append(crit)
    if prof.memory == "low":
        snap = memory_snapshot_preface(ledger)
        if snap:
            parts.append(snap)
    if ledger_block:
        parts.append(ledger_block)
    return "\n\n".join(parts).strip()


def write_precheck_fact_limit(profile: Optional[WritingStrategyProfile] = None) -> int:
    """注意力低分时略增 write_precheck 事实条数。"""
    prof = profile or current_writing_strategy()
    if prof.attention == "low":
        return 12
    if prof.attention == "mid":
        return 8
    return 6


def assist_from_profile(profile: WritingStrategyProfile) -> AssistStrength:
    """把三维档位粗映射回 strong/mid/weak（供前端落盘）。"""
    lows = sum(
        1
        for t in (profile.attention, profile.memory, profile.reasoning)
        if t == "low"
    )
    highs = sum(
        1
        for t in (profile.attention, profile.memory, profile.reasoning)
        if t == "high"
    )
    if lows >= 2:
        return "strong"
    if highs >= 2:
        return "weak"
    return "mid"


def strengthen_profile(
    profile: Optional[WritingStrategyProfile] = None,
    *,
    bump_attention: bool = True,
    bump_memory: bool = True,
    bump_reasoning: bool = False,
) -> WritingStrategyProfile:
    """向「多补」方向抬一档（high→mid→low）。"""
    base = profile or current_writing_strategy()
    return WritingStrategyProfile(
        attention=_TIER_STRENGTHEN[base.attention] if bump_attention else base.attention,
        memory=_TIER_STRENGTHEN[base.memory] if bump_memory else base.memory,
        reasoning=(
            _TIER_STRENGTHEN[base.reasoning] if bump_reasoning else base.reasoning
        ),
    )


def strengthen_assist(current: Optional[str]) -> AssistStrength:
    cur = (current or "mid").strip().lower()
    if cur not in _ASSIST_ORDER:
        cur = "mid"
    idx = _ASSIST_ORDER.index(cur)  # type: ignore[arg-type]
    return _ASSIST_ORDER[min(idx + 1, len(_ASSIST_ORDER) - 1)]


@dataclass(frozen=True)
class StrategyAdaptResult:
    profile: WritingStrategyProfile
    suggested_assist: AssistStrength
    reasons: Tuple[str, ...]
    changed: bool


def adapt_from_turn_signals(
    profile: Optional[WritingStrategyProfile] = None,
    *,
    scene_guard_strengthen: bool = False,
    gate_failed: bool = False,
    probe_miss_rate: Optional[float] = None,
    contradiction_count: int = 0,
    current_assist: Optional[str] = None,
) -> StrategyAdaptResult:
    """根据本轮信号决定是否抬升策略。

    - 本场守卫要求 strengthen / gate 失败 → 抬 attention+memory
    - 矛盾 ≥ 2 → 再抬 reasoning
    - probe 未命中率 ≥ 0.4 → 抬 memory
    """
    base = profile or current_writing_strategy()
    reasons: List[str] = []
    next_p = base
    bump_a = bump_m = bump_r = False

    if scene_guard_strengthen or gate_failed:
        bump_a = bump_m = True
        reasons.append("本场守卫/写后闸未通过")
    if contradiction_count >= 2:
        bump_r = True
        reasons.append(f"事实矛盾 {contradiction_count} 条")
    if probe_miss_rate is not None and probe_miss_rate >= 0.4:
        bump_m = True
        reasons.append(f"记忆探针未命中率 {probe_miss_rate:.0%}")

    if bump_a or bump_m or bump_r:
        next_p = strengthen_profile(
            base,
            bump_attention=bump_a,
            bump_memory=bump_m,
            bump_reasoning=bump_r,
        )

    changed = next_p != base
    if changed:
        set_writing_strategy(next_p)

    suggested = (
        strengthen_assist(current_assist)
        if changed
        else assist_from_profile(next_p)
    )
    if changed and current_assist:
        suggested = strengthen_assist(current_assist)
    elif changed:
        suggested = assist_from_profile(next_p)

    return StrategyAdaptResult(
        profile=next_p,
        suggested_assist=suggested,
        reasons=tuple(reasons),
        changed=changed,
    )
