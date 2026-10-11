"""分支记忆 · flag/变量状态切片。

在 label 可达性之外，按「到达焦点章前可能成立的变量赋值」裁剪记忆：
- 收集可达路径上的 ``set`` 赋值，得到 possible flag 域；
- 调用方可传入 ``assumed_flags``（试玩器当前状态）；
- 条件边若对 assumed 恒不成立，则其目标章视为他线。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from app.domain.types import VnProject


@dataclass
class FlagSlice:
    assumed: Dict[str, Any] = field(default_factory=dict)
    possible: Dict[str, Set[Any]] = field(default_factory=dict)
    #: 因条件与 assumed 冲突而被剔除的章
    excluded_chapter_ids: Set[str] = field(default_factory=set)
    #: 到达焦点前路径上出现过的 set 摘要
    assignments: List[Dict[str, Any]] = field(default_factory=list)
    note: str = ""

    def as_meta(self) -> Dict[str, Any]:
        return {
            "assumedKeys": list(self.assumed.keys()),
            "possibleKeys": list(self.possible.keys()),
            "excludedChapters": len(self.excluded_chapter_ids),
            "assignmentCount": len(self.assignments),
            "note": self.note,
        }


def _collect_sets_on_labels(graph: Any, labels: Set[str]) -> List[Dict[str, Any]]:
    from app.core.blocks import walk_blocks

    rows: List[Dict[str, Any]] = []
    for name in labels:
        meta = graph.labels.get(name) or {}
        seg = meta.get("segment") or []
        cid = str(meta.get("chapterId") or "")
        for b in walk_blocks(list(seg)):
            if b.get("type") != "set":
                continue
            key = str(b.get("key") or "")
            if not key:
                continue
            rows.append(
                {
                    "key": key,
                    "op": b.get("op") or "=",
                    "value": b.get("value"),
                    "label": name,
                    "chapterId": cid,
                }
            )
    return rows


def _eval_condition(cond: str, assumed: Dict[str, Any]) -> Optional[bool]:
    """能判定则 True/False；解析失败则 None（不可证伪）。"""
    raw = (cond or "").strip()
    if not raw:
        return True
    try:
        from app.core.conditions import evaluate_condition, parse_condition

        parsed = parse_condition(raw)
        return bool(evaluate_condition(parsed, assumed))
    except Exception:  # noqa: BLE001
        return None


def build_flag_slice(
    project: VnProject,
    *,
    chapter_id: Optional[str] = None,
    assumed_flags: Optional[Dict[str, Any]] = None,
    reachable_labels: Optional[Set[str]] = None,
) -> FlagSlice:
    """构建 flag 切片；无脚本图时返回空切片。"""
    assumed = dict(assumed_flags or {})
    # 声明变量默认值并入 assumed（未显式传入时）
    for v in project.variables or []:
        key = str(getattr(v, "key", "") or "")
        if key and key not in assumed:
            assumed[key] = getattr(v, "value", None)

    try:
        from app.core.branch_analysis import build_graph, reachable_from, variable_domain
    except Exception as exc:  # noqa: BLE001
        return FlagSlice(assumed=assumed, note=f"无分支分析:{exc}")

    graph = build_graph(project)
    if not graph.order:
        return FlagSlice(assumed=assumed, note="无脚本图，跳过 flag 切片")

    labels = set(reachable_labels or reachable_from(graph))
    focus = (chapter_id or "").strip()
    if focus and focus in (graph.chapterFirstLabel or {}):
        fl = graph.chapterFirstLabel[focus]
        if fl:
            labels |= reachable_from(graph, fl)

    assignments = _collect_sets_on_labels(graph, labels)
    possible: Dict[str, Set[Any]] = {}
    for row in assignments:
        if row.get("op") == "=":
            possible.setdefault(str(row["key"]), set()).add(row.get("value"))

    # 合并 domain
    try:
        domain = variable_domain(project, graph, reachable_only=True)
        for key, info in domain.items():
            vals = info.get("values") or set()
            if isinstance(vals, set):
                possible.setdefault(key, set()).update(vals)
            else:
                possible.setdefault(key, set()).update(list(vals))
    except Exception:  # noqa: BLE001
        pass

    # 条件边：assumed 下恒假 → 目标章剔除
    excluded: Set[str] = set()
    for e in graph.edges:
        cond = str(getattr(e, "condition", "") or "").strip()
        if not cond:
            continue
        verdict = _eval_condition(cond, assumed)
        if verdict is False and e.dst:
            meta = graph.labels.get(e.dst) or {}
            cid = str(meta.get("chapterId") or "")
            if cid and cid != focus:
                excluded.add(cid)

    return FlagSlice(
        assumed=assumed,
        possible=possible,
        excluded_chapter_ids=excluded,
        assignments=assignments[:80],
        note="按可达路径 set 域 + assumed 条件边裁剪",
    )


def format_flag_slice_block(slice_: FlagSlice, *, max_keys: int = 12) -> str:
    if not slice_.possible and not slice_.excluded_chapter_ids and not slice_.assumed:
        return ""
    lines = ["## Flag 状态切片（本路线变量）"]
    if slice_.assumed:
        bits = [f"{k}={v!r}" for k, v in list(slice_.assumed.items())[:max_keys]]
        lines.append("- 当前假定：" + "；".join(bits))
    if slice_.possible:
        lines.append("- 可达路径上可能出现的赋值：")
        for key, vals in list(slice_.possible.items())[:max_keys]:
            shown = ", ".join(repr(v) for v in list(vals)[:6])
            lines.append(f"  · {key} ∈ {{{shown}}}")
    if slice_.excluded_chapter_ids:
        lines.append(
            f"- 因条件与假定冲突而剔除的他线章：{len(slice_.excluded_chapter_ids)} 章"
            "（勿使用其独有事实）"
        )
    lines.append("- 规则：勿写只有在相反 flag 下才成立的情节。")
    return "\n".join(lines)


def apply_flag_slice_to_scope_chapters(
    reachable: Set[str],
    slice_: FlagSlice,
) -> Tuple[Set[str], Set[str]]:
    """从可达章中去掉 flag 冲突章；返回 (new_reachable, newly_excluded)。"""
    drop = slice_.excluded_chapter_ids & reachable
    return reachable - drop, drop
