"""VN/轻小说特异约束总装：分支记忆 + flag 切片 + 伏笔图/完备性 + 可演 + 声线 + 子代理。

``intensity``（由 writing_assist 映射）：
- ``full``（strong）：全量 VN 块
- ``mid``：分支/flag/伏笔支付/可演；关声线先验、结局完备、子代理
- ``light``（weak）：仅薄可演约束 + 策略裁过的账本；关掉重块
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Literal, Optional

from app.core.branch_memory import (
    BranchMemoryScope,
    filter_ledger_for_route,
    format_branch_memory_block,
    resolve_branch_memory_scope,
)
from app.core.flag_slice import build_flag_slice, format_flag_slice_block
from app.core.foreshadow_endings import (
    check_foreshadow_ending_completeness,
    format_foreshadow_ending_block,
)
from app.core.foreshadow_graph import (
    ForeshadowGraph,
    build_foreshadow_graph,
    format_foreshadow_payoff_block,
)
from app.core.pipeline.ledger import format_ledger_for_agent, get_ledger
from app.core.subagent_isolation import run_consistency_subagent
from app.core.vn_scene_constraints import (
    format_vn_scene_constraints_block,
    scene_constraints_meta,
)
from app.core.voice_write_prior import (
    build_voice_write_priors,
    format_voice_write_prior_block,
)
from app.core.writing_strategy import (
    WritingStrategyProfile,
    apply_strategy_to_ledger_block,
    current_writing_strategy,
)
from app.domain.types import VnProject

BundleIntensity = Literal["full", "mid", "light"]


def resolve_vn_bundle_intensity(
    *,
    writing_assist: Optional[str] = None,
    strategy: Optional[WritingStrategyProfile] = None,
) -> BundleIntensity:
    """强度跟**请求的 writing_assist**走（不被探针 blend 抬成 full）。"""
    assist = (writing_assist or "").strip().lower()
    if assist == "weak":
        return "light"
    if assist == "mid":
        return "mid"
    if assist == "strong":
        return "full"
    prof = strategy or current_writing_strategy()
    if prof.attention == "high" and prof.memory == "high":
        return "light"
    if prof.attention == "mid" or prof.memory == "mid":
        return "mid"
    return "full"


@dataclass
class VnWriteBundle:
    lore_craft: str = ""
    framing_extra: str = ""
    scope: Optional[BranchMemoryScope] = None
    foreshadow_graph: Optional[ForeshadowGraph] = None
    meta: Dict[str, Any] = field(default_factory=dict)


def assemble_vn_write_bundle(
    project: VnProject,
    *,
    chapter_id: Optional[str] = None,
    strategy: Optional[WritingStrategyProfile] = None,
    assumed_flags: Optional[Dict[str, Any]] = None,
    writing_assist: Optional[str] = None,
    intensity: Optional[BundleIntensity] = None,
    playtest_hints_block: str = "",
    include_voice_prior: bool = True,
    include_scene_constraints: bool = True,
    include_subagent: bool = True,
    include_ending_completeness: bool = True,
    include_playtest_hints: bool = True,
) -> VnWriteBundle:
    """组装写路径 VN 特异块。"""
    prof = strategy or current_writing_strategy()
    level: BundleIntensity = intensity or resolve_vn_bundle_intensity(
        writing_assist=writing_assist, strategy=prof
    )

    # light：关掉重块；mid：关声线/结局/子代理
    if level == "light":
        include_voice_prior = False
        include_subagent = False
        include_ending_completeness = False
        include_playtest_hints = False
        heavy_route = False
    elif level == "mid":
        include_voice_prior = False
        include_subagent = False
        include_ending_completeness = False
        heavy_route = True
    else:
        heavy_route = True

    scope = resolve_branch_memory_scope(
        project, chapter_id=chapter_id, assumed_flags=assumed_flags
    )
    raw_ledger = get_ledger(project)
    filtered = filter_ledger_for_route(raw_ledger, scope)

    ledger_block = format_ledger_for_agent(
        filtered,
        chapters=project.chapters,
        focus_chapter_id=chapter_id,
        graded=True,
    )
    ledger_block = apply_strategy_to_ledger_block(
        ledger_block, filtered, profile=prof, chapters=project.chapters
    )

    branch_block = ""
    flag_block = ""
    payoff_block = ""
    ending_block = ""
    ending_meta: Dict[str, Any] = {}
    flag_meta: Dict[str, Any] = {}
    graph: Optional[ForeshadowGraph] = None
    foreshadow_meta: Dict[str, Any] = {}

    if heavy_route:
        branch_block = format_branch_memory_block(scope, filtered)
        flag_slice = build_flag_slice(
            project,
            chapter_id=chapter_id,
            assumed_flags=assumed_flags,
            reachable_labels=scope.reachable_labels or None,
        )
        flag_block = format_flag_slice_block(flag_slice)
        flag_meta = flag_slice.as_meta()
        graph = build_foreshadow_graph(
            project,
            filtered,
            reachable_chapter_ids=scope.reachable_chapter_ids,
        )
        payoff_block = format_foreshadow_payoff_block(
            graph, focus_chapter_id=chapter_id
        )
        foreshadow_meta = graph.as_meta()
        if include_ending_completeness:
            ending_report = check_foreshadow_ending_completeness(project)
            ending_block = format_foreshadow_ending_block(ending_report)
            ending_meta = ending_report.as_meta()

    parts: List[str] = [branch_block, flag_block, payoff_block, ending_block]
    if ledger_block:
        parts.append(ledger_block)
    lore = "\n\n".join(p for p in parts if p and p.strip())

    framing_bits: List[str] = []
    if include_scene_constraints:
        scene_block = format_vn_scene_constraints_block(
            project, chapter_id=chapter_id
        )
        if level == "light" and scene_block:
            # 弱档只留首段硬约束，砍掉展开说明
            scene_block = scene_block.split("\n\n")[0].strip()
        if scene_block:
            framing_bits.append(scene_block)

    voice_meta: Dict[str, Any] = {"priorCount": 0}
    if include_voice_prior:
        priors = build_voice_write_priors(project, chapter_id=chapter_id)
        voice_block = format_voice_write_prior_block(priors)
        if voice_block:
            framing_bits.append(voice_block)
        voice_meta = {"priorCount": len(priors)}

    subagent_meta: Dict[str, Any] = {}
    if include_subagent:
        conclusion = run_consistency_subagent(project, chapter_id=chapter_id)
        block = conclusion.format_for_main()
        if block:
            framing_bits.append(block)
        subagent_meta = conclusion.as_meta()

    playtest_meta: Dict[str, Any] = {"injected": False}
    if include_playtest_hints and (playtest_hints_block or "").strip():
        framing_bits.append(playtest_hints_block.strip())
        playtest_meta = {"injected": True}

    return VnWriteBundle(
        lore_craft=lore,
        framing_extra="\n\n".join(framing_bits).strip(),
        scope=scope,
        foreshadow_graph=graph,
        meta={
            "intensity": level,
            "writingAssist": (writing_assist or "").strip() or None,
            "branch": scope.as_meta(),
            "flag": flag_meta,
            "foreshadow": foreshadow_meta,
            "foreshadowEndings": ending_meta,
            "scene": scene_constraints_meta(project, chapter_id),
            "voice": voice_meta,
            "subagent": subagent_meta,
            "playtestHints": playtest_meta,
        },
    )
