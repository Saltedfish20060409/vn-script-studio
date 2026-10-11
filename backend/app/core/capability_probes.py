"""写作能力探针集：推理 / 注意力 / 记忆 → 能力画像 → 策略档。

设计目标：低成本、可回归、针对写作 harness，不是学术大榜。
默认**不调模型**：用本地检索/账本/确定性矛盾检测打分；可选挂 memory_probe。

档位：score ∈ [0,1]；<0.5 → low（需多补）；0.5–0.7 mid；>0.7 high。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional, Tuple

from app.core.writing_strategy import (
    Tier,
    WritingStrategyProfile,
    profile_from_assist,
    set_writing_strategy,
)
from app.domain.types import VnProject

TierScore = Literal["low", "mid", "high"]


@dataclass
class ProbeScore:
    dimension: str
    score: float
    tier: TierScore
    detail: str = ""
    samples: int = 0


@dataclass
class CapabilityProfile:
    reasoning: float = 0.5
    attention: float = 0.5
    memory: float = 0.5
    instruction_following: float = 0.5
    probes: List[ProbeScore] = field(default_factory=list)

    def tier(self, dim: str) -> TierScore:
        v = float(getattr(self, dim, 0.5) or 0.5)
        if v < 0.5:
            return "low"
        if v <= 0.7:
            return "mid"
        return "high"

    def as_meta(self) -> Dict[str, Any]:
        return {
            "reasoning": round(self.reasoning, 3),
            "attention": round(self.attention, 3),
            "memory": round(self.memory, 3),
            "instruction_following": round(self.instruction_following, 3),
            "tiers": {
                "reasoning": self.tier("reasoning"),
                "attention": self.tier("attention"),
                "memory": self.tier("memory"),
                "instruction_following": self.tier("instruction_following"),
            },
            "probes": [
                {
                    "dimension": p.dimension,
                    "score": round(p.score, 3),
                    "tier": p.tier,
                    "detail": p.detail,
                    "samples": p.samples,
                }
                for p in self.probes
            ],
        }


def _score_to_tier(score: float) -> TierScore:
    if score < 0.5:
        return "low"
    if score <= 0.7:
        return "mid"
    return "high"


def probe_attention(project: VnProject, *, chapter_id: Optional[str] = None) -> ProbeScore:
    """注意力：关键设定能否被 hybrid 检索命中（埋针 → 查询）。"""
    from app.core.agent_context import chapter_plain
    from app.core.write_hybrid import collect_hybrid_hits

    chapters = list(project.chapters or [])
    if not chapters:
        return ProbeScore("attention", 0.5, "mid", "无章节，跳过", 0)

    # 从非焦点章抽一段可辨识片段当「埋针」
    focus = (chapter_id or "").strip()
    needle_ch = next((c for c in chapters if str(c.id) != focus), chapters[0])
    plain = chapter_plain(needle_ch, project.characters) or ""
    # 取中间一段作关键事实
    mid = plain[max(0, len(plain) // 2 - 40) : len(plain) // 2 + 40].strip()
    tokens = [t for t in mid.replace("\n", " ").split() if len(t) >= 2][:3]
    if not tokens and mid:
        tokens = [mid[:6]] if len(mid) >= 4 else []
    if not tokens:
        # 退回角色名
        names = [c.displayName for c in (project.characters or []) if c.displayName]
        tokens = names[:2]
    if not tokens:
        return ProbeScore("attention", 0.5, "mid", "无可埋针文本", 0)

    query = " ".join(tokens[:2])
    hits = collect_hybrid_hits(project, query, chapter_id=focus or None, limit=6)
    hit_labels = " ".join(str(h.get("label") or "") + str(h.get("snippet") or "") for h in hits)
    ok = any(t in hit_labels for t in tokens) or bool(hits)
    score = 1.0 if ok and len(hits) >= 1 else (0.4 if hits else 0.2)
    return ProbeScore(
        "attention",
        score,
        _score_to_tier(score),
        f"query={query!r} hits={len(hits)}",
        samples=1,
    )


def probe_memory(project: VnProject, *, chapter_id: Optional[str] = None) -> ProbeScore:
    """记忆：账本指纹是否跟上正文 + 状态快照是否非空。"""
    from app.core.chapter_digest import chapter_content_hash
    from app.core.pipeline.ledger import get_ledger

    ledger = get_ledger(project)
    facts = list(ledger.get("chapterFacts") or [])
    states = list(ledger.get("characterStates") or [])
    if not facts:
        return ProbeScore("memory", 0.25, "low", "账本无章节事实", 0)

    chapters = {str(c.id): c for c in (project.chapters or [])}
    matched = 0
    checked = 0
    for row in facts:
        cid = str(row.get("chapterId") or "")
        ch = chapters.get(cid)
        if not ch:
            continue
        checked += 1
        if row.get("sourceHash") == chapter_content_hash(ch):
            matched += 1
    hash_score = (matched / checked) if checked else 0.0
    state_score = 1.0 if states else 0.3
    # 焦点章是否有状态
    focus = (chapter_id or "").strip()
    if focus:
        has_focus = any(str(s.get("chapterId") or "") == focus for s in states) or any(
            str(f.get("chapterId") or "") == focus for f in facts
        )
        focus_score = 1.0 if has_focus else 0.4
    else:
        focus_score = 0.7
    score = 0.5 * hash_score + 0.3 * state_score + 0.2 * focus_score
    return ProbeScore(
        "memory",
        score,
        _score_to_tier(score),
        f"hash_match={matched}/{checked} states={len(states)}",
        samples=checked,
    )


def probe_reasoning(project: VnProject) -> ProbeScore:
    """推理：写前对账能否抓住「账本已故仍出场」（合成迷你样本）。"""
    try:
        from app.core.pipeline.ledger import get_ledger, set_ledger
        from app.core.write_precheck import precheck_before_continue
    except Exception as exc:  # noqa: BLE001
        return ProbeScore("reasoning", 0.5, "mid", f"跳过:{exc}", 0)

    p = project.model_copy(deep=True)
    chars = list(p.characters or [])
    if not chars or not p.chapters:
        return ProbeScore("reasoning", 0.5, "mid", "无角色/章节", 0)
    name = chars[0].displayName or chars[0].defineName or "主角"
    cid = str(chars[0].id)
    ch = p.chapters[0]
    ledger = get_ledger(p)
    ledger["characterStates"] = [
        {
            "id": "probe-dead",
            "chapterId": ch.id,
            "chapterTitle": ch.title,
            "characterId": cid,
            "characterName": name,
            "emotion": "已故",
            "body": "已死亡",
            "relations": "—",
        }
    ]
    p = set_ledger(p, ledger)
    draft = f'{name}：「我还活着。」'
    try:
        report = precheck_before_continue(
            p, chapter_id=str(ch.id), draft=draft, prose_audit=False
        )
    except Exception as exc:  # noqa: BLE001
        return ProbeScore("reasoning", 0.5, "mid", f"对账不可用:{exc}", 0)

    codes = {str(getattr(i, "code", "")) for i in (report.issues or [])}
    caught = "dead_character_present" in codes or (not report.ok)
    score = 1.0 if caught else 0.35
    return ProbeScore(
        "reasoning",
        score,
        _score_to_tier(score),
        "caught_dead_reentry" if caught else "missed_dead_reentry",
        samples=1,
    )


def probe_instruction_following(project: VnProject) -> ProbeScore:
    """指令遵循代理：可演硬约束块与 write_op framing 是否可装配（结构探针）。"""
    from app.core.vn_scene_constraints import format_vn_scene_constraints_block

    block = format_vn_scene_constraints_block(project)
    ok = "可演" in block and "假选择" in block
    score = 0.85 if ok else 0.4
    return ProbeScore(
        "instruction_following",
        score,
        _score_to_tier(score),
        "stageable_block_ok" if ok else "missing_constraints",
        samples=1,
    )


def run_capability_probes(
    project: VnProject,
    *,
    chapter_id: Optional[str] = None,
    include_memory_probe: bool = False,
) -> CapabilityProfile:
    """跑探针集，返回画像。"""
    probes = [
        probe_attention(project, chapter_id=chapter_id),
        probe_memory(project, chapter_id=chapter_id),
        probe_reasoning(project),
        probe_instruction_following(project),
    ]
    profile = CapabilityProfile(
        attention=probes[0].score,
        memory=probes[1].score,
        reasoning=probes[2].score,
        instruction_following=probes[3].score,
        probes=list(probes),
    )
    if include_memory_probe:
        try:
            from app.core.memory_probe import run_memory_probes

            report = run_memory_probes(project, focus_chapter_id=chapter_id)
            # miss rate → 压低 memory
            results = getattr(report, "results", None) or []
            if results:
                miss = sum(1 for r in results if not getattr(r, "ok", True)) / len(results)
                profile.memory = max(0.0, min(1.0, profile.memory * (1.0 - 0.5 * miss)))
                profile.probes.append(
                    ProbeScore(
                        "memory_probe_layer",
                        1.0 - miss,
                        _score_to_tier(1.0 - miss),
                        f"miss_rate={miss:.2f}",
                        samples=len(results),
                    )
                )
        except Exception as exc:  # noqa: BLE001
            profile.probes.append(
                ProbeScore("memory_probe_layer", 0.5, "mid", f"skip:{exc}", 0)
            )
    return profile


def profile_to_strategy(profile: CapabilityProfile) -> WritingStrategyProfile:
    """画像 → 策略：能力低 → tier=low（外部多补）。"""
    return WritingStrategyProfile(
        attention=profile.tier("attention"),  # type: ignore[arg-type]
        memory=profile.tier("memory"),  # type: ignore[arg-type]
        reasoning=profile.tier("reasoning"),  # type: ignore[arg-type]
    )


def apply_capability_profile(
    project: VnProject,
    *,
    chapter_id: Optional[str] = None,
    persist: bool = True,
) -> Tuple[CapabilityProfile, WritingStrategyProfile]:
    """跑探针并可选写入当前 ContextVar 策略档。"""
    cap = run_capability_probes(project, chapter_id=chapter_id)
    strat = profile_to_strategy(cap)
    if persist:
        set_writing_strategy(strat)
    return cap, strat


def blend_with_assist(
    profile: CapabilityProfile,
    writing_assist: Optional[str],
) -> WritingStrategyProfile:
    """请求体 writing_assist 与探针画像取「更保守」（更多补）的一侧。"""
    from_probe = profile_to_strategy(profile)
    if not (writing_assist or "").strip():
        return from_probe
    from_assist = profile_from_assist(writing_assist)
    order = {"high": 0, "mid": 1, "low": 2}

    def colder(a: Tier, b: Tier) -> Tier:
        return a if order[a] >= order[b] else b

    return WritingStrategyProfile(
        attention=colder(from_probe.attention, from_assist.attention),
        memory=colder(from_probe.memory, from_assist.memory),
        reasoning=colder(from_probe.reasoning, from_assist.reasoning),
    )
