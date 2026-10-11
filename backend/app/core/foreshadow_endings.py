"""伏笔结局路径完备性：每条未回收伏笔须在至少一条通往结局的路径上有回收机会。

完备 = 存在一条从入口到某终点的简单路径，满足：
1. 经过植点章（或其后继）；
2. 在植点之后经过至少一个候选回收章（foreshadow_graph）或声明结局章。

已 paid 的伏笔：回收章须落在某条通往结局的路径上。
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Set, Tuple

from app.domain.types import VnProject


@dataclass
class ForeshadowEndingRow:
    foreshadow_id: str
    hook: str
    status: str
    planted_chapter: str
    paid_chapter: Optional[str]
    complete: bool
    reason: str
    ending_labels: List[str] = field(default_factory=list)


@dataclass
class ForeshadowEndingReport:
    rows: List[ForeshadowEndingRow] = field(default_factory=list)
    open_incomplete: int = 0
    paid_off_path: int = 0
    truncated: bool = False

    @property
    def completeness_rate(self) -> Optional[float]:
        if not self.rows:
            return 1.0
        ok = sum(1 for r in self.rows if r.complete)
        return ok / len(self.rows)

    def as_meta(self) -> Dict[str, Any]:
        return {
            "rowCount": len(self.rows),
            "openIncomplete": self.open_incomplete,
            "paidOffPath": self.paid_off_path,
            "completenessRate": self.completeness_rate,
            "truncated": self.truncated,
        }


def _chapter_of_label(graph: Any, label: str) -> str:
    return str((graph.labels.get(label) or {}).get("chapterId") or "")


def _enumerate_chapter_paths(
    graph: Any, *, max_paths: int = 4000
) -> Tuple[List[List[str]], bool]:
    """简单路径 → 章序列（去连续重复）。"""
    from app.core.branch_analysis import enumerate_paths

    # 复用边枚举的思想，自己走一层拿 visited labels
    root = graph.root()
    if root is None:
        return [], False
    adj = graph.adjacency()
    paths: List[List[str]] = []
    truncated = False
    stack: List[Tuple[str, Tuple[str, ...]]] = [(root, (root,))]
    while stack:
        node, visited = stack.pop()
        outs = adj.get(node) or []
        terminal = not outs or all(e.dst is None for e in outs)
        if terminal or any(e.dst is None for e in outs):
            chans: List[str] = []
            for lab in visited:
                cid = _chapter_of_label(graph, lab)
                if cid and (not chans or chans[-1] != cid):
                    chans.append(cid)
            paths.append(chans)
            if len(paths) >= max_paths:
                truncated = True
                break
        for e in outs:
            if e.dst is None:
                continue
            if e.dst in visited:
                continue
            stack.append((e.dst, (*visited, e.dst)))
        if len(paths) >= max_paths:
            truncated = True
            break
    return paths, truncated


def _ending_chapter_ids(project: VnProject, graph: Any) -> Set[str]:
    out: Set[str] = set()
    for e in project.endings or []:
        label = str(getattr(e, "label", "") or "").strip()
        if label and label in graph.labels:
            cid = _chapter_of_label(graph, label)
            if cid:
                out.add(cid)
    # 无声明结局时：用章末 / return 终端
    if not out:
        from app.core.branch_analysis import enumerate_paths, reconcile_endings

        info = enumerate_paths(graph)
        recon = reconcile_endings(project, graph, info)
        for label in recon.get("undeclaredTerminals") or []:
            cid = _chapter_of_label(graph, str(label))
            if cid:
                out.add(cid)
        for row in recon.get("declared") or []:
            if row.get("reachable"):
                lab = str(row.get("label") or "")
                cid = _chapter_of_label(graph, lab)
                if cid:
                    out.add(cid)
    return out


def check_foreshadow_ending_completeness(
    project: VnProject,
    *,
    payoff_by_hook: Optional[Dict[str, List[str]]] = None,
) -> ForeshadowEndingReport:
    from app.core.foreshadow_graph import build_foreshadow_graph
    from app.core.pipeline.ledger import foreshadow_report

    try:
        from app.core.branch_analysis import build_graph
    except Exception:
        return ForeshadowEndingReport()

    graph = build_graph(project)
    if not graph.order:
        # 轻小说：按叙事顺序 —— 植点后存在后续章即算有回收机会
        rows_src = foreshadow_report(project)
        chapter_ids = [str(c.id) for c in (project.chapters or [])]
        idx = {c: i for i, c in enumerate(chapter_ids)}
        rows: List[ForeshadowEndingRow] = []
        open_inc = 0
        for fo in rows_src:
            planted = str(fo.get("plantedChapter") or "")
            status = str(fo.get("status") or "open")
            paid = fo.get("paidInChapter")
            pi = idx.get(planted, -1)
            if status == "paid":
                complete = bool(paid) and str(paid) in idx
                if not complete:
                    open_inc += 0
                rows.append(
                    ForeshadowEndingRow(
                        foreshadow_id=str(fo.get("id") or ""),
                        hook=str(fo.get("hook") or ""),
                        status=status,
                        planted_chapter=planted,
                        paid_chapter=str(paid) if paid else None,
                        complete=complete,
                        reason="linear_paid_ok" if complete else "linear_paid_missing",
                    )
                )
                continue
            has_after = pi >= 0 and pi < len(chapter_ids) - 1
            if not has_after:
                open_inc += 1
            rows.append(
                ForeshadowEndingRow(
                    foreshadow_id=str(fo.get("id") or ""),
                    hook=str(fo.get("hook") or ""),
                    status=status,
                    planted_chapter=planted,
                    paid_chapter=None,
                    complete=has_after,
                    reason="linear_has_later_chapter" if has_after else "linear_no_later",
                )
            )
        return ForeshadowEndingReport(rows=rows, open_incomplete=open_inc)

    paths, truncated = _enumerate_chapter_paths(graph)
    ending_chs = _ending_chapter_ids(project, graph)
    # 只保留抵达结局章（或任一终端）的路径
    ending_paths = [
        p for p in paths if ending_chs.intersection(p) or p  # 有路径即候选；优先含结局
    ]
    if ending_chs:
        preferred = [p for p in ending_paths if ending_chs.intersection(p)]
        if preferred:
            ending_paths = preferred

    fg = build_foreshadow_graph(project)
    payoff_map: Dict[str, List[str]] = dict(payoff_by_hook or {})
    for e in fg.edges:
        payoff_map.setdefault(e.foreshadow_id or e.hook, []).append(e.payoff_chapter)

    rows_out: List[ForeshadowEndingRow] = []
    open_inc = 0
    paid_off = 0
    for fo in foreshadow_report(project):
        fid = str(fo.get("id") or "")
        hook = str(fo.get("hook") or "")
        planted = str(fo.get("plantedChapter") or "")
        status = str(fo.get("status") or "open")
        paid = str(fo.get("paidInChapter") or "") or None
        candidates = list(payoff_map.get(fid) or payoff_map.get(hook) or [])

        if status == "paid" and paid:
            on_path = any(
                planted in p and paid in p and p.index(planted) <= p.index(paid)
                for p in ending_paths
                if planted in p and paid in p
            )
            if not on_path:
                paid_off += 1
            rows_out.append(
                ForeshadowEndingRow(
                    foreshadow_id=fid,
                    hook=hook,
                    status=status,
                    planted_chapter=planted,
                    paid_chapter=paid,
                    complete=on_path,
                    reason="paid_on_ending_path" if on_path else "paid_off_ending_path",
                    ending_labels=sorted(ending_chs)[:6],
                )
            )
            continue

        # open：植点后存在候选回收章落在通向结局的路径上
        ok = False
        reason = "no_ending_path"
        for p in ending_paths:
            if planted not in p:
                continue
            pi = p.index(planted)
            after = set(p[pi + 1 :])
            if candidates and after.intersection(candidates):
                ok = True
                reason = "payoff_on_ending_path"
                break
            if not candidates and after:
                ok = True
                reason = "later_chapter_on_ending_path"
                break
        if not ok:
            open_inc += 1
            reason = reason if ending_paths else "no_paths"
        rows_out.append(
            ForeshadowEndingRow(
                foreshadow_id=fid,
                hook=hook,
                status=status,
                planted_chapter=planted,
                paid_chapter=None,
                complete=ok,
                reason=reason,
                ending_labels=sorted(ending_chs)[:6],
            )
        )

    return ForeshadowEndingReport(
        rows=rows_out,
        open_incomplete=open_inc,
        paid_off_path=paid_off,
        truncated=truncated,
    )


def format_foreshadow_ending_block(report: ForeshadowEndingReport, *, max_rows: int = 8) -> str:
    if not report.rows:
        return ""
    rate = report.completeness_rate
    lines = [
        "## 伏笔结局路径完备性",
        f"- 完备率：{rate:.0%}" if rate is not None else "- 完备率：—",
        f"- 未完备 open：{report.open_incomplete}；回收落在结局路径外：{report.paid_off_path}",
    ]
    bad = [r for r in report.rows if not r.complete][:max_rows]
    if bad:
        lines.append("- 需处理：")
        for r in bad:
            lines.append(
                f"  · [{r.status}] {r.hook[:40]}（{r.reason}；植于 {r.planted_chapter}）"
            )
    else:
        lines.append("- 当前未回收/已回收伏笔均落在可达结局路径的回收机会上。")
    if report.truncated:
        lines.append("- 注意：路径枚举已截断，完备性为下界。")
    return "\n".join(lines)
