"""伏笔支付图：plant → 候选回收场 → 章龄压力 → 写时强制曝光。

不替代账本 open/paid；在其上建轻量边，供写路径与垂直评测使用。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence, Set

from app.domain.types import VnProject

#: 埋了这么多章还没收 → 写时「优先回收」
PRESSURE_AGE = 3
#: 每个伏笔最多挂几个候选回收章
MAX_PAYOFF_CANDIDATES = 3


@dataclass
class ForeshadowEdge:
    foreshadow_id: str
    hook: str
    planted_chapter: str
    payoff_chapter: str
    reason: str  # adjacent | keyword | pressure_slot
    age_chapters: Optional[int] = None
    pressure: bool = False


@dataclass
class ForeshadowGraph:
    edges: List[ForeshadowEdge] = field(default_factory=list)
    open_count: int = 0
    pressure_count: int = 0

    def as_meta(self) -> Dict[str, Any]:
        return {
            "edgeCount": len(self.edges),
            "openCount": self.open_count,
            "pressureCount": self.pressure_count,
        }


def _chapter_index(project: VnProject) -> Dict[str, int]:
    return {str(c.id): i for i, c in enumerate(project.chapters or [])}


def _chapter_plain_snip(project: VnProject, chapter_id: str, n: int = 800) -> str:
    from app.core.agent_context import chapter_plain

    ch = next((c for c in (project.chapters or []) if str(c.id) == chapter_id), None)
    if not ch:
        return ""
    return (chapter_plain(ch, project.characters) or "")[:n]


def _hook_keywords(hook: str) -> List[str]:
    import re

    toks = re.findall(r"[\u4e00-\u9fff]{2,}|[A-Za-z]{3,}", hook or "")
    # 去过短噪音
    return [t for t in toks if len(t) >= 2][:6]


def build_foreshadow_graph(
    project: VnProject,
    ledger: Optional[Dict[str, Any]] = None,
    *,
    reachable_chapter_ids: Optional[Set[str]] = None,
) -> ForeshadowGraph:
    from app.core.pipeline.ledger import foreshadow_report, get_ledger, set_ledger

    # foreshadow_report 读 project.writingLedger；若传入过滤账本，临时挂上再算章龄
    led = ledger if isinstance(ledger, dict) else get_ledger(project)
    proj_for_report = project
    if ledger is not None:
        proj_for_report = set_ledger(project, led)
    rows = foreshadow_report(proj_for_report)

    idx = _chapter_index(project)
    chapter_ids = [str(c.id) for c in (project.chapters or [])]
    reach = reachable_chapter_ids

    edges: List[ForeshadowEdge] = []
    pressure_n = 0
    open_n = 0

    for row in rows:
        if str(row.get("status") or "open") == "paid":
            continue
        open_n += 1
        fid = str(row.get("id") or "")
        hook = str(row.get("hook") or "")
        planted = str(row.get("plantedChapter") or "")
        age = row.get("ageChapters")
        age_i = int(age) if isinstance(age, int) else None
        pressure = age_i is not None and age_i >= PRESSURE_AGE
        if pressure:
            pressure_n += 1

        plant_i = idx.get(planted, -1)
        candidates: List[tuple[str, str]] = []

        # 1) 邻接章（埋点后 1..3 章）
        if plant_i >= 0:
            for j in range(plant_i + 1, min(len(chapter_ids), plant_i + 1 + MAX_PAYOFF_CANDIDATES)):
                cid = chapter_ids[j]
                if reach is not None and cid not in reach:
                    continue
                candidates.append((cid, "adjacent"))

        # 2) 关键词命中后续章
        kws = _hook_keywords(hook)
        if kws and plant_i >= 0:
            for cid in chapter_ids[plant_i + 1 :]:
                if reach is not None and cid not in reach:
                    continue
                if any(c[0] == cid for c in candidates):
                    continue
                snip = _chapter_plain_snip(project, cid)
                if any(k in snip for k in kws):
                    candidates.append((cid, "keyword"))
                if len(candidates) >= MAX_PAYOFF_CANDIDATES + 2:
                    break

        # 3) 高压伏笔：若还没有候选，挂焦点后最近可达章
        if pressure and not candidates and chapter_ids:
            for cid in chapter_ids:
                if reach is not None and cid not in reach:
                    continue
                if idx.get(cid, -1) > plant_i:
                    candidates.append((cid, "pressure_slot"))
                    break

        for cid, reason in candidates[:MAX_PAYOFF_CANDIDATES]:
            edges.append(
                ForeshadowEdge(
                    foreshadow_id=fid,
                    hook=hook[:80],
                    planted_chapter=planted,
                    payoff_chapter=cid,
                    reason=reason,
                    age_chapters=age_i,
                    pressure=pressure,
                )
            )

    return ForeshadowGraph(edges=edges, open_count=open_n, pressure_count=pressure_n)


def format_foreshadow_payoff_block(
    graph: ForeshadowGraph,
    *,
    focus_chapter_id: Optional[str] = None,
    max_lines: int = 8,
) -> str:
    """写时强制曝光：高压未回收 + 本场是候选回收场的钩子。"""
    focus = (focus_chapter_id or "").strip()
    lines: List[str] = ["## 伏笔支付图（本场须对照）"]
    if graph.open_count == 0:
        lines.append("- （无未回收伏笔）")
        return "\n".join(lines)

    lines.append(
        f"- 未回收 {graph.open_count} 条；高压（≥{PRESSURE_AGE} 章）{graph.pressure_count} 条"
    )

    # 本场是候选回收场的边优先
    focus_edges = [e for e in graph.edges if focus and e.payoff_chapter == focus]
    pressure_edges = [e for e in graph.edges if e.pressure]
    shown: Set[str] = set()
    ordered: List[ForeshadowEdge] = []
    for e in focus_edges + pressure_edges + graph.edges:
        key = e.foreshadow_id or e.hook
        if key in shown:
            continue
        shown.add(key)
        ordered.append(e)
        if len(ordered) >= max_lines:
            break

    for e in ordered:
        age_bit = f"，已埋 {e.age_chapters} 章" if e.age_chapters is not None else ""
        pressure_bit = "【优先回收】" if e.pressure else ""
        focus_bit = "（本场为候选回收场）" if focus and e.payoff_chapter == focus else ""
        lines.append(
            f"- {pressure_bit}{e.hook}{age_bit}{focus_bit} "
            f"→ 候选章 {e.payoff_chapter}（{e.reason}）"
        )
    lines.append(
        "- 规则：高压未回收钩子应在本场对白/旁白中有所推进或回收；"
        "勿无故重置线索状态。"
    )
    return "\n".join(lines)


def foreshadow_payoff_coverage(
    graph: ForeshadowGraph,
    *,
    focus_chapter_id: str,
    draft: str,
) -> Dict[str, Any]:
    """评测用：本场高压钩子是否在草稿里被提及（关键词粗检）。"""
    focus = (focus_chapter_id or "").strip()
    text = draft or ""
    pressure_hooks = []
    hit = 0
    for e in graph.edges:
        if not e.pressure:
            continue
        if focus and e.payoff_chapter != focus and e.planted_chapter != focus:
            # 仍统计所有高压：写本场时是否碰过
            pass
        pressure_hooks.append(e.hook)
        kws = _hook_keywords(e.hook)
        if kws and any(k in text for k in kws):
            hit += 1
        elif e.hook and e.hook[:4] in text:
            hit += 1
    total = len({e.foreshadow_id or e.hook for e in graph.edges if e.pressure})
    return {
        "pressureTotal": total,
        "pressureMentioned": hit,
        "rate": (hit / total) if total else None,
    }
