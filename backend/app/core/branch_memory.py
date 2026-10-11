"""分支条件记忆：只注入「当前路径可达」的事实，隔离他线污染。

依赖 ``branch_analysis.build_graph`` / ``reachable_from``。无脚本图（纯轻小说）时
退化为叙事顺序前缀：焦点章及之前的章一律可达。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set

from app.domain.types import VnProject


@dataclass
class BranchMemoryScope:
    mode: str  # "graph" | "linear" | "empty"
    focus_chapter_id: str = ""
    reachable_chapter_ids: Set[str] = field(default_factory=set)
    unreachable_chapter_ids: Set[str] = field(default_factory=set)
    reachable_labels: Set[str] = field(default_factory=set)
    note: str = ""
    flag_meta: Dict[str, Any] = field(default_factory=dict)

    def as_meta(self) -> Dict[str, Any]:
        return {
            "mode": self.mode,
            "focusChapterId": self.focus_chapter_id,
            "reachableChapters": len(self.reachable_chapter_ids),
            "unreachableChapters": len(self.unreachable_chapter_ids),
            "reachableLabels": len(self.reachable_labels),
            "note": self.note,
            "flag": self.flag_meta,
        }


def resolve_branch_memory_scope(
    project: VnProject,
    *,
    chapter_id: Optional[str] = None,
    assumed_flags: Optional[Dict[str, Any]] = None,
) -> BranchMemoryScope:
    """解析本轮写作可用的章集合（含可选 flag 切片）。"""
    chapters = list(project.chapters or [])
    all_ids = {str(c.id) for c in chapters if c.id}
    focus = (chapter_id or "").strip()
    if not focus and chapters:
        focus = str(chapters[0].id)

    scope: Optional[BranchMemoryScope] = None
    # 尝试脚本图
    try:
        from app.core.branch_analysis import build_graph, reachable_from

        graph = build_graph(project)
        if graph.order:
            root = graph.root()
            labels = reachable_from(graph, root)
            # 焦点章的入口 label：若存在，取「从 start 可达且能进焦点章」的并集
            focus_first = graph.chapterFirstLabel.get(focus)
            if focus_first and focus_first in graph.labels:
                via_focus = reachable_from(graph, focus_first)
                labels = labels | via_focus
            chapter_ids: Set[str] = set()
            for lab, meta in graph.labels.items():
                if lab not in labels:
                    continue
                cid = str((meta or {}).get("chapterId") or "")
                if cid:
                    chapter_ids.add(cid)
            # 纯 prose、图上无 label 的章：焦点章及之前仍视为已发生（非他线脚本章）
            labeled_chapters = {
                str((meta or {}).get("chapterId") or "")
                for meta in graph.labels.values()
            } - {""}
            for c in chapters:
                cid = str(c.id)
                if cid not in labeled_chapters:
                    chapter_ids.add(cid)
                if focus and cid == focus:
                    break
            unreachable = all_ids - chapter_ids
            scope = BranchMemoryScope(
                mode="graph",
                focus_chapter_id=focus,
                reachable_chapter_ids=chapter_ids,
                unreachable_chapter_ids=unreachable,
                reachable_labels=set(labels),
                note="按控制流可达章；无 label 的 prose 章按焦点前缀并入",
            )
    except Exception:  # noqa: BLE001
        pass

    if scope is None:
        # 轻小说 / 无图：焦点章及之前
        reached: Set[str] = set()
        for c in chapters:
            reached.add(str(c.id))
            if focus and str(c.id) == focus:
                break
        if not reached:
            reached = set(all_ids)
        scope = BranchMemoryScope(
            mode="linear",
            focus_chapter_id=focus,
            reachable_chapter_ids=reached,
            unreachable_chapter_ids=all_ids - reached,
            note="无脚本图，按叙事顺序前缀视为可达",
        )

    # Flag 状态切片：从可达集中剔除与 assumed 冲突的条件边目标章
    try:
        from app.core.flag_slice import (
            apply_flag_slice_to_scope_chapters,
            build_flag_slice,
        )

        slice_ = build_flag_slice(
            project,
            chapter_id=focus,
            assumed_flags=assumed_flags,
            reachable_labels=scope.reachable_labels or None,
        )
        new_reach, dropped = apply_flag_slice_to_scope_chapters(
            scope.reachable_chapter_ids, slice_
        )
        if dropped:
            scope.reachable_chapter_ids = new_reach
            scope.unreachable_chapter_ids |= dropped
            scope.note = (scope.note or "") + "；已套用 flag 切片"
        scope.flag_meta = slice_.as_meta()
    except Exception as exc:  # noqa: BLE001
        scope.flag_meta = {"error": str(exc)[:120]}

    return scope


def filter_ledger_for_route(
    ledger: Dict[str, Any],
    scope: BranchMemoryScope,
) -> Dict[str, Any]:
    """过滤账本：事实/状态/事件仅保留可达章；伏笔拆成「本路线」与「他线勿用」。"""
    reach = scope.reachable_chapter_ids
    if not reach:
        return dict(ledger)

    def _cid(row: Dict[str, Any], key: str = "chapterId") -> str:
        return str(row.get(key) or "")

    facts = [f for f in (ledger.get("chapterFacts") or []) if _cid(f) in reach]
    states = [s for s in (ledger.get("characterStates") or []) if _cid(s) in reach]
    events = [e for e in (ledger.get("events") or []) if _cid(e) in reach]

    route_fores: List[Dict[str, Any]] = []
    other_fores: List[Dict[str, Any]] = []
    for fo in ledger.get("foreshadows") or []:
        planted = _cid(fo, "plantedChapter")
        if not planted or planted in reach:
            route_fores.append(fo)
        else:
            other_fores.append(fo)

    out = dict(ledger)
    out["chapterFacts"] = facts
    out["characterStates"] = states
    out["events"] = events
    out["foreshadows"] = route_fores
    out["_otherRouteForeshadows"] = other_fores
    return out


def format_branch_memory_block(
    scope: BranchMemoryScope,
    filtered_ledger: Dict[str, Any],
    *,
    max_other: int = 5,
) -> str:
    """写路径注入：本路线范围说明 + 他线伏笔隔离警告。"""
    lines = [
        "## 分支条件记忆（本路线）",
        f"- 模式：{scope.mode}；可达章 {len(scope.reachable_chapter_ids)} / "
        f"他线章 {len(scope.unreachable_chapter_ids)}",
    ]
    if scope.note:
        lines.append(f"- {scope.note}")
    lines.append(
        "- **只使用本路线已发生的事实**；他线剧情不得写进当前路径，"
        "除非作者指令明确要求合流。"
    )
    others = list(filtered_ledger.get("_otherRouteForeshadows") or [])[:max_other]
    if others:
        lines.append("### 他线伏笔（当前路径不可达 · 禁止当作本线事实）")
        for fo in others:
            hook = fo.get("hook") or fo.get("id")
            planted = fo.get("plantedChapter") or "?"
            lines.append(f"- [他线] {hook}（植于 {planted}）")
    return "\n".join(lines)
