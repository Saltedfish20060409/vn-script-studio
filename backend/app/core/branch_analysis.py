"""剧本控制流分析引擎：把"分支"从展示树变成可推理的图。

为什么重写
----------
旧实现（`branch_tree.py`）只是把章节按 menu/jump 连成一棵树用来画图，
`script_analysis` 里的可达性也只看 label→label 的字符串边。两者都答不出
作者真正会踩的坑：

- 「这个选项我按不按都一样」——**无后果选项**；
- 「这个条件永远不成立」——flag 从没被赋过需要的值；
- 「玩家会不会卡死在这一段」——**状态无关死循环**；
- 「我写了 5 个结局，实际能走到几个」——声明与可达对不上账；
- 「这条分支有没有人走得到」——**分支覆盖**。

本模块把这些全部做成确定性静态分析（纯本地、不调模型），因此可进单测、可在 CI 回归。

语义基准（重要）
----------------
控制流以**本应用的试玩器**（`frontend/src/lib/playState.ts`）为准，因为它才是作者
点"试玩"时看到的东西，Ren'Py 行为与之对齐：

1. label 是**标记**不是终点：块按顺序线性执行，走过 label 继续往下；
   因此"下一个 label"不是结局，而是一条 ``fallthrough`` 边。
2. 章节末尾没有出口 = 这一章结束（试玩器按章播放）。
   但**导出到 Ren'Py 后会继续流入下一章**——这是真实隐患，单独报 ``chapter_end_no_exit``。
3. 无条件 transfer（jump/return，或"所有分支都离开"的 menu/if）之后的同级语句是死代码。
"""

from __future__ import annotations

from collections import Counter
from dataclasses import dataclass, field
from typing import Any, Dict, Iterable, List, Optional, Sequence, Set, Tuple

from app.core.blocks import iter_project_blocks, walk_blocks
from app.core.conditions import (
    Comparison,
    ConditionError,
    condition_keys,
    evaluate_condition,
    parse_condition,
)
from app.domain.types import VnProject

# --------------------------------------------------------------------- 参数

MAX_PATHS = 20000
"""路径枚举上限。到顶就标记 truncated，绝不假装"已经枚举完"。"""

MAX_PATH_DEPTH = 80
MAX_CYCLES = 40

_NUMERIC_OPS = (">", ">=", "<", "<=")


# ------------------------------------------------------------------ 数据结构


@dataclass
class Edge:
    """控制流边。``dst is None`` 表示终结（return / 章末）。"""

    src: str
    dst: Optional[str]
    kind: str  # jump | choice | if | fallthrough | return | choice-return | chapter-end
    chapterId: str
    label: str
    condition: str = ""
    menuId: str = ""
    choiceIndex: int = -1
    choiceText: str = ""
    index: int = -1  # 在 graph.edges 中的序号（报告里用它对齐覆盖率）


@dataclass
class ScriptGraph:
    labels: Dict[str, Dict[str, Any]] = field(default_factory=dict)
    order: List[str] = field(default_factory=list)
    edges: List[Edge] = field(default_factory=list)
    chapterFirstLabel: Dict[str, str] = field(default_factory=dict)
    chapterLastLabel: Dict[str, str] = field(default_factory=dict)
    order_index: Dict[str, int] = field(default_factory=dict)

    def adjacency(self) -> Dict[str, List[Edge]]:
        adj: Dict[str, List[Edge]] = {}
        for e in self.edges:
            adj.setdefault(e.src, []).append(e)
        return adj

    def root(self) -> Optional[str]:
        if "start" in self.labels:
            return "start"
        return self.order[0] if self.order else None


# ------------------------------------------------------------- 退出点扫描


def _scan_exits(blocks: Sequence[Any]) -> Tuple[List[Dict[str, Any]], bool]:
    """扫描一段块序列，返回 ``(出口列表, 是否可能流出去)``。

    这两个量必须**同时**返回。反例：一个菜单，选项 A 跳走、选项 B 是内联正文——
    只报"有出口"会漏掉"B 之后继续往下演"；只报"能流出去"又会把 A 这条边丢掉，
    分支覆盖统计因此偏低（选项 A 永远算没被走过）。真实控制流是两者的并集。

    只要遇到必然离开本段的语句，其后的同级语句就是死代码，立即停止扫描。
    """
    out: List[Dict[str, Any]] = []
    for b in blocks or []:
        if not isinstance(b, dict):
            continue
        btype = b.get("type")
        if btype == "jump" and b.get("target"):
            out.append({"kind": "jump", "target": str(b["target"]), "via": "jump"})
            return out, False
        if btype == "return":
            out.append({"kind": "return", "target": None, "via": "return"})
            return out, False
        if btype == "menu":
            choices = [c for c in (b.get("choices") or []) if isinstance(c, dict)]
            if not choices:
                continue
            all_leave = True
            for i, c in enumerate(choices):
                menu_meta = {
                    "via": "choice",
                    "menuId": str(b.get("id") or "menu"),
                    "choiceIndex": i,
                    "choiceText": str(c.get("text") or ""),
                }
                cond = str(c.get("condition") or "")
                if c.get("jump"):
                    out.append({**menu_meta, "kind": "jump", "target": str(c["jump"]), "condition": cond})
                    continue
                body_exits, body_falls = _scan_exits(c.get("blocks") or [])
                if body_falls:
                    all_leave = False
                for e in body_exits:
                    out.append(
                        {
                            **e,
                            **menu_meta,
                            "condition": cond or str(e.get("condition") or ""),
                        }
                    )
            if all_leave:
                return out, False
            continue  # 有选项会继续 → 后面的语句仍可达，继续扫描
        if btype == "if":
            branches = [br for br in (b.get("branches") or []) if isinstance(br, dict)]
            if not branches:
                continue
            has_else = any(not str(br.get("condition") or "").strip() for br in branches)
            all_leave = has_else
            for i, br in enumerate(branches):
                cond = str(br.get("condition") or "")
                br_exits, br_falls = _scan_exits(br.get("blocks") or [])
                if br_falls:
                    all_leave = False
                for e in br_exits:
                    out.append(
                        {
                            **e,
                            "via": "if",
                            "branchIndex": i,
                            "condition": cond or str(e.get("condition") or ""),
                        }
                    )
            if all_leave:
                return out, False
            continue
    return out, True


def _first_unconditional_transfer(blocks: Sequence[Any]) -> Optional[int]:
    """返回第一个"必然离开本段"的同级块下标（用于死代码定位）。"""
    for i, b in enumerate(blocks or []):
        if not isinstance(b, dict):
            continue
        btype = b.get("type")
        if btype == "jump" and b.get("target"):
            return i
        if btype == "return":
            return i
        if btype in ("menu", "if"):
            exits, falls = _scan_exits([b])
            if exits and not falls:
                return i
    return None


def _segment_flags(blocks: Sequence[Any]) -> Dict[str, bool]:
    all_blocks = list(walk_blocks(list(blocks or [])))
    sets_var = any(b.get("type") == "set" for b in all_blocks)
    cond = False
    for b in all_blocks:
        if b.get("type") == "menu" and any(
            str(c.get("condition") or "").strip()
            for c in (b.get("choices") or [])
            if isinstance(c, dict)
        ):
            cond = True
        if b.get("type") == "if" and any(
            str(br.get("condition") or "").strip()
            for br in (b.get("branches") or [])
            if isinstance(br, dict)
        ):
            cond = True
    return {"setsVariable": sets_var, "hasConditionalExit": cond}


# ------------------------------------------------------------------ 构图


def build_graph(project: VnProject) -> ScriptGraph:
    """全项目 label 图（跨章；与导出后的 script.rpy 一致，label 是全局的）。"""
    graph = ScriptGraph()
    for ch in project.chapters or []:
        cid = str(getattr(ch, "id", "") or "")
        blocks = [b for b in (getattr(ch, "blocks", None) or []) if isinstance(b, dict)]
        positions = [
            i
            for i, b in enumerate(blocks)
            if b.get("type") == "label" and b.get("name")
        ]
        for pos, start in enumerate(positions):
            name = str(blocks[start]["name"])
            if name in graph.labels:
                continue  # 重名 label：Ren'Py 会覆盖前一个，先到先得（另有 duplicate_label 检查）
            end = positions[pos + 1] if pos + 1 < len(positions) else len(blocks)
            graph.labels[name] = {
                "name": name,
                "chapterId": cid,
                "index": start,
                "segment": blocks[start + 1 : end],
            }
            graph.order.append(name)
            graph.order_index[name] = start
            graph.chapterFirstLabel.setdefault(cid, name)
            graph.chapterLastLabel[cid] = name

    # 边
    for name in graph.order:
        node = graph.labels[name]
        cid = node["chapterId"]
        seg = node["segment"]
        exits, falls = _scan_exits(seg)
        for ex in exits:
            # 边类型 = "这条边是怎么产生的"（jump / choice / if），
            # 终结边统一记 return。注意不能直接拿 ex["kind"]：它是**退出点**的种类，
            # 选项里的 jump 与正文里的 jump 都是 "jump"，混用会让分支覆盖统计恒为 0。
            is_terminal = ex.get("kind") == "return" or ex.get("target") is None
            kind = "return" if is_terminal else str(ex.get("via") or "jump")
            graph.edges.append(
                Edge(
                    src=name,
                    dst=ex.get("target"),
                    kind=kind,
                    chapterId=cid,
                    label=name,
                    condition=str(ex.get("condition") or ""),
                    menuId=str(ex.get("menuId") or ""),
                    choiceIndex=int(ex.get("choiceIndex", -1)),
                    choiceText=str(ex.get("choiceText") or ""),
                )
            )
        if not falls:
            continue
        # 还能"流出去" → 流向下一个 label（同章）或本章结束
        nxt = _next_label_in_chapter(graph, cid, name)
        if nxt:
            graph.edges.append(
                Edge(src=name, dst=nxt, kind="fallthrough", chapterId=cid, label=name)
            )
        else:
            graph.edges.append(
                Edge(
                    src=name,
                    dst=None,
                    kind="chapter-end",
                    chapterId=cid,
                    label=name,
                )
            )
    for i, e in enumerate(graph.edges):
        e.index = i
    return graph


def _next_label_in_chapter(graph: ScriptGraph, cid: str, name: str) -> Optional[str]:
    names = [n for n in graph.order if graph.labels[n]["chapterId"] == cid]
    if name not in names:
        return None
    i = names.index(name)
    return names[i + 1] if i + 1 < len(names) else None


def reachable_from(graph: ScriptGraph, root: Optional[str] = None) -> Set[str]:
    start = root or graph.root()
    if start is None or start not in graph.labels:
        return set()
    adj = graph.adjacency()
    seen = {start}
    stack = [start]
    while stack:
        cur = stack.pop()
        for e in adj.get(cur, ()):
            if e.dst and e.dst in graph.labels and e.dst not in seen:
                seen.add(e.dst)
                stack.append(e.dst)
    return seen


# ------------------------------------------------------------------ 环检测


def _normalize_cycle(nodes: Sequence[str]) -> Tuple[str, ...]:
    if not nodes:
        return ()
    i = min(range(len(nodes)), key=lambda k: nodes[k])
    return tuple(list(nodes[i:]) + list(nodes[:i]))


def find_cycles(graph: ScriptGraph, *, limit: int = MAX_CYCLES) -> List[Dict[str, Any]]:
    """DFS 找有向环，并判断"这个环能不能绕出去"。

    ``canLoopForever``：环上既没有变量赋值、也没有任何条件出口 —— 玩家一旦进来
    就只能反复看同一段，出不去（试玩器靠 2000 步上限兜底，Ren'Py 里是真死循环）。
    这是视觉小说里最贵的一类 bug，所以单独判。
    """
    adj: Dict[str, List[str]] = {}
    for e in graph.edges:
        if e.dst:
            adj.setdefault(e.src, []).append(e.dst)
    color: Dict[str, int] = {}
    found: Dict[Tuple[str, ...], List[str]] = {}
    for start in graph.order:
        if color.get(start):
            continue
        # 灰色在**入栈时**就置上：否则同一节点可能在还没被处理前被两个父节点各压一次，
        # 于是被走两遍、path 里出现重复节点，报出并不存在的环。
        color[start] = 1
        stack: List[Tuple[str, int]] = [(start, 0)]
        path: List[str] = [start]
        while stack:
            node, idx = stack[-1]
            outs = adj.get(node, [])
            if idx < len(outs):
                stack[-1] = (node, idx + 1)
                nxt = outs[idx]
                state = color.get(nxt, 0)
                if state == 1:
                    if nxt in path:
                        cyc = path[path.index(nxt) :]
                        found.setdefault(_normalize_cycle(cyc), list(cyc))
                elif state == 0:
                    color[nxt] = 1
                    path.append(nxt)
                    stack.append((nxt, 0))
            else:
                color[node] = 2
                stack.pop()
                if path and path[-1] == node:
                    path.pop()

    reachable = reachable_from(graph)
    out: List[Dict[str, Any]] = []
    for key, cyc in found.items():
        labels = [graph.labels[n] for n in cyc if n in graph.labels]
        sets_var = any(_segment_flags(n["segment"])["setsVariable"] for n in labels)
        cond_exit = any(_segment_flags(n["segment"])["hasConditionalExit"] for n in labels)
        out.append(
            {
                "labels": list(cyc),
                "length": len(cyc),
                "reachable": all(n in reachable for n in cyc),
                "hasVariableChange": sets_var,
                "hasConditionalExit": cond_exit,
                "canLoopForever": (not sets_var) and (not cond_exit),
            }
        )
    out.sort(key=lambda r: (not r["canLoopForever"], not r["reachable"], -r["length"]))
    return out[:limit]


# -------------------------------------------------------- 条件可满足性分析


def _constraint_bounds(terms: Sequence[Comparison]) -> Dict[str, Any]:
    """把一组比较归纳成区间约束。只做我们**能证明**的判定，拿不准就说 unknown。"""
    lo: Optional[float] = None
    hi: Optional[float] = None
    lo_inc = True
    hi_inc = True
    eqs: List[Any] = []
    neqs: List[Any] = []
    truthy = False
    mismatch: Optional[str] = None
    for c in terms:
        op, val = c.op, c.value
        if op is None:
            truthy = True
            continue
        if op == "==":
            eqs.append(val)
            continue
        if op == "!=":
            neqs.append(val)
            continue
        if not isinstance(val, (int, float)) or isinstance(val, bool):
            mismatch = f"「{c.key}」按数值比较，但比较值不是数字（{val!r}）"
            continue
        v = float(val)
        if op in (">", ">="):
            inc = op == ">="
            if lo is None or v > lo or (v == lo and not inc):
                lo, lo_inc = v, inc
        else:
            inc = op == "<="
            if hi is None or v < hi or (v == hi and not inc):
                hi, hi_inc = v, inc
    return {
        "lo": lo,
        "hi": hi,
        "loInc": lo_inc,
        "hiInc": hi_inc,
        "eqs": eqs,
        "neqs": neqs,
        "truthy": truthy,
        "mismatch": mismatch,
    }


def _interval_unsat(b: Dict[str, Any]) -> Optional[str]:
    """区间层面的矛盾（对无界数值也成立）。"""
    lo, hi = b["lo"], b["hi"]
    if lo is not None and hi is not None:
        if lo > hi:
            return f"区间为空（要求 ≥{lo:g} 同时 ≤{hi:g}）"
        if lo == hi and not (b["loInc"] and b["hiInc"]):
            return f"区间为空（{lo:g} 处被排除）"
    eqs = b["eqs"]
    distinct = {repr(v) for v in eqs}
    if len(distinct) > 1:
        return f"同一个变量被要求同时等于 {sorted(distinct)}"
    if eqs:
        v = eqs[0]
        for n in b["neqs"]:
            if repr(n) == repr(v):
                return f"同时要求等于且不等于 {v!r}"
        if isinstance(v, bool) or not isinstance(v, (int, float)):
            if b["lo"] is not None or b["hi"] is not None:
                return f"既要求 {v!r} 又做数值区间比较，无法同时成立"
            return None
        fv = float(v)
        if b["lo"] is not None and (fv < b["lo"] or (fv == b["lo"] and not b["loInc"])):
            return f"{fv:g} 落在下界之外"
        if b["hi"] is not None and (fv > b["hi"] or (fv == b["hi"] and not b["hiInc"])):
            return f"{fv:g} 落在上界之外"
    return None


def _dedupe_values(values: Iterable[Any], limit: int = 48) -> List[Any]:
    seen: Set[str] = set()
    out: List[Any] = []
    for v in values:
        k = repr(v)
        if k in seen:
            continue
        seen.add(k)
        out.append(v)
        if len(out) >= limit:
            break
    return out


def _domain_values(info: Dict[str, Any]) -> List[Any]:
    """变量**真正可能取到**的值（声明初值 + 可达 set 赋的值）。

    证伪只能在这个集合里做：拿域外的值去试，会把"flag 永远是 0"这种真问题
    试成"好像也能成立"，于是永远报不出来。
    """
    return _dedupe_values(info.get("values") or [])


def _condition_verdict(
    text: str,
    domain: Dict[str, Dict[str, Any]],
) -> Dict[str, Any]:
    """判断一个条件是否**永远不成立**（只在能证明时才下这个结论）。"""
    try:
        terms = parse_condition(text)
    except ConditionError as exc:
        return {"satisfiable": True, "unknown": True, "error": str(exc), "reason": ""}
    if not terms:
        return {"satisfiable": True, "unknown": False, "error": None, "reason": ""}

    by_key: Dict[str, List[Comparison]] = {}
    for c in terms:
        by_key.setdefault(c.key, []).append(c)

    unknown = False
    for key, cs in by_key.items():
        info = domain.get(key)
        b = _constraint_bounds(cs)
        if b["mismatch"]:
            return {
                "satisfiable": True,
                "unknown": False,
                "error": None,
                "reason": b["mismatch"],
                "typeMismatch": True,
            }
        proof = _interval_unsat(b)
        if proof:
            return {"satisfiable": False, "unknown": False, "error": None, "reason": proof}
        if info is None or info.get("unbounded"):
            unknown = True
            continue
        vals = _domain_values(info)
        if not vals:
            unknown = True
            continue
        if not any(evaluate_condition(terms, {key: v}) for v in vals):
            return {
                "satisfiable": False,
                "unknown": False,
                "error": None,
                "reason": (
                    f"「{key}」可能取值 {[repr(v) for v in vals]}，没有任何一个满足该条件"
                ),
            }
    # 多变量联合可行性：只在所有相关变量域都有限时才敢判定
    finite = all(
        (domain.get(k) is not None and not domain[k].get("unbounded")) for k in by_key
    )
    if finite and len(by_key) > 1:
        probes = {k: _domain_values(domain.get(k) or {}) for k, _cs in by_key.items()}
        combos: List[Dict[str, Any]] = [{}]
        for k, vs in probes.items():
            nxt: List[Dict[str, Any]] = []
            for base in combos:
                for v in vs:
                    nxt.append({**base, k: v})
                    if len(nxt) > 2000:
                        break
            combos = nxt
        if combos and not any(evaluate_condition(terms, c) for c in combos):
            return {
                "satisfiable": False,
                "unknown": False,
                "error": None,
                "reason": "各变量取值组合中没有任何一组能让该条件成立",
            }
    return {"satisfiable": True, "unknown": unknown, "error": None, "reason": ""}


# ------------------------------------------------------- 变量可达取值（域）


def variable_domain(
    project: VnProject, graph: ScriptGraph, *, reachable_only: bool = True
) -> Dict[str, Dict[str, Any]]:
    """每个变量**可能取到的值**。

    声明值 + 可达代码里的 ``set``。``+=`` / ``-=`` 视为无界（能连续变化），
    因此这类变量不会用来判定"条件恒不成立"——只能证伪才叫证伪。
    """
    reachable = reachable_from(graph) if reachable_only else set(graph.labels)
    domain: Dict[str, Dict[str, Any]] = {}
    for v in project.variables or []:
        key = str(getattr(v, "key", "") or "")
        if not key:
            continue
        domain[key] = {
            "type": getattr(v, "type", None),
            "values": {(v.value)},
            "unbounded": False,
            "declared": True,
            "name": getattr(v, "name", None),
        }
    if reachable_only:
        for name in reachable:
            seg = (graph.labels.get(name) or {}).get("segment") or []
            for b in walk_blocks(list(seg)):
                if b.get("type") != "set":
                    continue
                key = str(b.get("key") or "")
                if not key:
                    continue
                info = domain.setdefault(
                    key, {"type": None, "values": set(), "unbounded": False, "declared": False}
                )
                if (b.get("op") or "=") == "=":
                    info["values"].add(b.get("value"))
                else:
                    info["unbounded"] = True
    return domain


def analyze_conditions(
    project: VnProject, graph: Optional[ScriptGraph] = None
) -> Dict[str, Any]:
    """收集全部条件（选项 + if 分支）并判定可满足性。"""
    g = graph or build_graph(project)
    domain = variable_domain(project, g)
    rows: List[Dict[str, Any]] = []
    for cid, b in iter_project_blocks(project):
        entries: List[Tuple[str, str, str, int]] = []
        if b.get("type") == "menu":
            for i, c in enumerate(b.get("choices") or []):
                if not isinstance(c, dict):
                    continue
                raw = str(c.get("condition") or "").strip()
                if raw:
                    entries.append(("choice", raw, str(c.get("text") or f"选项{i + 1}"), i))
        elif b.get("type") == "if":
            for i, br in enumerate(b.get("branches") or []):
                if not isinstance(br, dict):
                    continue
                raw = str(br.get("condition") or "").strip()
                if raw:
                    entries.append(("if", raw, "", i))
        for where, raw, detail, idx in entries:
            verdict = _condition_verdict(raw, domain)
            rows.append(
                {
                    "chapterId": cid,
                    "where": where,
                    "text": raw,
                    "detail": detail,
                    "branchIndex": idx,
                    "keys": condition_keys(parse_condition(raw))
                    if not verdict.get("error")
                    else [],
                    "error": verdict.get("error"),
                    "satisfiable": verdict["satisfiable"],
                    "unknown": verdict.get("unknown", False),
                    "typeMismatch": verdict.get("typeMismatch", False),
                    "reason": verdict.get("reason", ""),
                }
            )
    return {
        "conditions": rows,
        "invalid": [r for r in rows if r["error"]],
        "neverTrue": [r for r in rows if not r["satisfiable"]],
        "typeMismatch": [r for r in rows if r.get("typeMismatch")],
        "domain": {
            k: {
                "type": v.get("type"),
                "values": sorted((repr(x) for x in (v.get("values") or [])), key=str),
                "unbounded": v.get("unbounded"),
                "declared": v.get("declared"),
            }
            for k, v in domain.items()
        },
    }


# ---------------------------------------------------------- 菜单与选项分析


def _choice_effect(choice: Dict[str, Any]) -> Dict[str, Any]:
    """一个选项的"后果签名"：跳到哪 / 改了哪些变量 / 是否有正文。"""
    body = [b for b in (choice.get("blocks") or []) if isinstance(b, dict)]
    vars_set = sorted(
        {str(b.get("key")) for b in walk_blocks(body) if b.get("type") == "set" and b.get("key")}
    )
    exits, falls = _scan_exits(body)
    target = None
    kind = "inline"
    if choice.get("jump"):
        target, kind = str(choice["jump"]), "jump"
    elif exits and not falls:
        first = exits[0]
        target = first.get("target")
        kind = "return" if first.get("kind") == "return" else "jump"
    return {
        "kind": kind,
        "target": target,
        "varsModified": vars_set,
        "bodyLength": len(body),
        "signature": f"{kind}:{target or ''}|{','.join(vars_set)}",
    }


def analyze_menus(
    project: VnProject,
    graph: Optional[ScriptGraph] = None,
    conditions: Optional[Dict[str, Any]] = None,
) -> List[Dict[str, Any]]:
    """逐个菜单给出选项后果与问题（无后果选项、死选项、重复条件、软锁）。"""
    g = graph or build_graph(project)
    cond_info = conditions if conditions is not None else analyze_conditions(project, g)
    never_true = {
        (r["chapterId"], r["where"] == "choice", r["branchIndex"])
        for r in cond_info["neverTrue"]
    }
    # 块 → 所在 label 的身份映射（一次性建好；嵌套块也要能正确归属）
    owner: Dict[int, str] = {}
    for name in g.order:
        for blk in walk_blocks(list(g.labels[name].get("segment") or [])):
            owner.setdefault(id(blk), name)

    out: List[Dict[str, Any]] = []
    for cid, b in iter_project_blocks(project):
        if b.get("type") != "menu":
            continue
        choices = [c for c in (b.get("choices") or []) if isinstance(c, dict)]
        if not choices:
            continue
        label = owner.get(id(b)) or g.chapterFirstLabel.get(cid, "")
        effects = [_choice_effect(c) for c in choices]
        texts = [str(c.get("text") or "").strip() for c in choices]
        conds = [str(c.get("condition") or "").strip() for c in choices]
        findings: List[Dict[str, Any]] = []

        # ① 整个菜单没有后果：所有选项签名一致且都没改变量
        sigs = {e["signature"] for e in effects}
        if len(sigs) == 1 and not any(e["varsModified"] for e in effects):
            findings.append(
                _finding(
                    "warn",
                    "menu_no_effect",
                    f"菜单「{str(b.get('prompt') or b.get('id') or '').strip() or label}」的 "
                    f"{len(choices)} 个选项后果完全相同、且不改任何变量：玩家选哪个都一样",
                    cid,
                    label,
                )
            )

        # ② 选项自身是 no-op：条件/正文都没有，也没有跳转
        for i, (c, e) in enumerate(zip(choices, effects)):
            if not texts[i]:
                findings.append(
                    _finding("error", "choice_empty_text", f"第 {i + 1} 个选项没有文案（玩家会看到空选项）", cid, label)
                )
            if e["kind"] == "inline" and e["bodyLength"] == 0 and not conds[i]:
                findings.append(
                    _finding(
                        "info",
                        "choice_inline_empty",
                        f"选项「{texts[i] or i + 1}」既没有跳转也没有正文，选中后直接继续——检查是否有意为之",
                        cid,
                        label,
                    )
                )
            if (cid, True, i) in never_true:
                findings.append(
                    _finding(
                        "error",
                        "choice_never_available",
                        f"选项「{texts[i] or i + 1}」的条件永远不成立，玩家永远看不到它：{conds[i]}",
                        cid,
                        label,
                    )
                )

        # ③ 重复文案 / 重复条件
        dup_text = [t for t, n in Counter(t for t in texts if t).items() if n > 1]
        if dup_text:
            findings.append(
                _finding(
                    "warn",
                    "choice_duplicate_text",
                    f"菜单里有重复的选项文案：{'、'.join(dup_text)}",
                    cid,
                    label,
                )
            )
        dup_cond = [t for t, n in Counter(c for c in conds if c).items() if n > 1]
        if dup_cond:
            findings.append(
                _finding(
                    "warn",
                    "choice_duplicate_condition",
                    f"同一菜单里条件完全相同（会同时出现/消失）：{'、'.join(dup_cond)}",
                    cid,
                    label,
                )
            )

        # ④ 软锁：所有选项都带条件且都恒不成立
        if conds and all(conds) and all((cid, True, i) in never_true for i in range(len(choices))):
            findings.append(
                _finding(
                    "error",
                    "menu_always_empty",
                    "菜单所有选项的条件都恒不成立：玩家会遇到一个没有可选项的死菜单",
                    cid,
                    label,
                )
            )
        if len(choices) == 1:
            findings.append(
                _finding(
                    "info",
                    "menu_single_option",
                    f"这个菜单只有 1 个选项（「{texts[0]}」）：它其实不是选择，考虑改成正文",
                    cid,
                    label,
                )
            )

        out.append(
            {
                "chapterId": cid,
                "label": label,
                "menuId": str(b.get("id") or "menu"),
                "prompt": str(b.get("prompt") or ""),
                "choices": [
                    {
                        "index": i,
                        "text": texts[i],
                        "condition": conds[i],
                        "effect": effects[i]["kind"],
                        "target": effects[i]["target"],
                        "varsModified": effects[i]["varsModified"],
                        "available": (cid, True, i) not in never_true,
                    }
                    for i in range(len(choices))
                ],
                "findings": findings,
            }
        )
    return out


# ---------------------------------------------------------------- 路径枚举


def enumerate_paths(
    graph: ScriptGraph, *, max_paths: int = MAX_PATHS, max_depth: int = MAX_PATH_DEPTH
) -> Dict[str, Any]:
    """从入口出发枚举**简单路径**（不重复经过同一 label）并统计覆盖率。

    只走简单路径是刻意的取舍：图里允许有环（合法的 hub 菜单就是环），
    完整路径集合可能是无限的。简单路径给出的是"玩家能走到的分支组合"的
    可复现下界，配合 ``truncated`` 标记如实说明没枚举完。
    """
    root = graph.root()
    if root is None:
        return {"paths": 0, "truncated": False, "edgeUse": {}, "terminals": {}, "lengths": []}
    adj = graph.adjacency()
    edge_use: Counter = Counter()
    terminals: Counter = Counter()
    lengths: List[int] = []
    stack: List[Tuple[str, Tuple[str, ...], Tuple[int, ...]]] = [(root, (root,), ())]
    count = 0
    truncated = False
    while stack:
        node, visited, taken = stack.pop()
        outs = adj.get(node) or []
        if not outs:
            terminals[("no-edge", node)] += 1
            lengths.append(len(taken))
            continue
        for e in outs:
            if e.dst is None:
                edge_use[e.index] += 1
                terminals[(e.kind, e.label)] += 1
                lengths.append(len(taken) + 1)
                count += 1
                continue
            if e.dst in visited or len(visited) >= max_depth:
                continue
            edge_use[e.index] += 1
            stack.append((e.dst, (*visited, e.dst), (*taken, e.index)))
        if count > max_paths:
            truncated = True
            break
    return {
        "paths": count,
        "truncated": truncated,
        "edgeUse": {e.index: edge_use.get(e.index, 0) for e in graph.edges},
        "terminals": {f"{k[0]}|{k[1]}": v for k, v in terminals.items()},
        "lengths": lengths,
    }


# ------------------------------------------------------------- 结局对账


def reconcile_endings(
    project: VnProject, graph: ScriptGraph, path_info: Dict[str, Any]
) -> Dict[str, Any]:
    """声明的结局 vs 实际可达的终点，逐条对账。"""
    declared = list(project.endings or [])
    reached = {
        k.split("|", 1)[1]
        for k in (path_info.get("terminals") or {})
        if k.split("|", 1)[0] in ("return", "chapter-end")
    }
    rows: List[Dict[str, Any]] = []
    findings: List[Dict[str, Any]] = []
    seen_labels: Set[str] = set()
    for e in declared:
        label = str(getattr(e, "label", "") or "").strip()
        name = str(getattr(e, "name", "") or "").strip()
        resolved = label or name
        exists = resolved in graph.labels
        reachable = exists and resolved in reached
        if label and not exists:
            findings.append(
                _finding(
                    "error",
                    "ending_label_missing",
                    f"结局「{name}」指向的 label「{label}」在剧本里不存在",
                    graph.labels.get(resolved, {}).get("chapterId", ""),
                    label,
                )
            )
        elif not label:
            findings.append(
                _finding(
                    "warn",
                    "ending_no_label",
                    f"结局「{name}」没有登记 label：无法自动核对它到底走得到走不到",
                    "",
                    "",
                )
            )
        if resolved in seen_labels:
            findings.append(
                _finding("warn", "ending_duplicate_label", f"多个结局登记在同一个 label「{resolved}」上", "", resolved)
            )
        seen_labels.add(resolved)
        rows.append(
            {
                "id": str(getattr(e, "id", "")),
                "name": name,
                "label": label,
                "route": str(getattr(e, "route", "") or ""),
                "condition": str(getattr(e, "condition", "") or ""),
                "exists": exists,
                "reachable": reachable,
            }
        )
    undeclared = sorted(reached - seen_labels)
    for label in undeclared:
        findings.append(
            _finding(
                "warn",
                "ending_undeclared",
                f"终点「{label}」在控制流里可达，但没有登记为结局：要么补登记，要么它可能是个 bug",
                graph.labels.get(label, {}).get("chapterId", ""),
                label,
            )
        )
    return {
        "declared": rows,
        "declaredCount": len(rows),
        "reachableDeclared": sum(1 for r in rows if r["reachable"]),
        "undeclaredTerminals": undeclared,
        "findings": findings,
    }


# ------------------------------------------------------------------ 汇总


def _finding(
    severity: str,
    code: str,
    message: str,
    chapter_id: str = "",
    label: str = "",
) -> Dict[str, Any]:
    return {
        "severity": severity,
        "code": code,
        "message": message,
        "source": "branch",
        "chapterId": chapter_id,
        "label": label,
    }


def analyze_branches(project: VnProject) -> Dict[str, Any]:
    """分支结构全面体检（纯本地静态分析）。"""
    graph = build_graph(project)
    reachable = reachable_from(graph)
    path_info = enumerate_paths(graph)
    cond = analyze_conditions(project, graph)
    menus = analyze_menus(project, graph, cond)
    cycles = find_cycles(graph)
    endings = reconcile_endings(project, graph, path_info)

    findings: List[Dict[str, Any]] = []
    findings.extend(endings["findings"])
    for m in menus:
        findings.extend(m["findings"])

    # 死代码：无条件 transfer 之后的同级语句
    dead_blocks: List[Dict[str, Any]] = []
    for name in graph.order:
        node = graph.labels[name]
        seg = node["segment"]
        pos = _first_unconditional_transfer(seg)
        if pos is None:
            continue
        for j in range(pos + 1, len(seg)):
            b = seg[j]
            if not isinstance(b, dict) or b.get("type") == "comment":
                continue
            dead_blocks.append(
                {
                    "chapterId": node["chapterId"],
                    "label": name,
                    "type": str(b.get("type") or "?"),
                    "preview": str(b.get("text") or b.get("code") or "")[:60],
                }
            )
            findings.append(
                _finding(
                    "warn",
                    "dead_block",
                    f"label「{name}」里有一条 {b.get('type')} 永远不会执行："
                    f"它前面已经无条件跳走了",
                    node["chapterId"],
                    label=name,
                )
            )

    # 章末没有出口：试玩器按章结束，但导出成 Ren'Py 会直接流入下一章
    chapters = [str(getattr(c, "id", "") or "") for c in (project.chapters or [])]
    chapter_fallthrough: List[Dict[str, Any]] = []
    for i, cid in enumerate(chapters):
        last = graph.chapterLastLabel.get(cid)
        if not last:
            continue
        if not any(
            e.src == last and e.dst is None and e.kind == "chapter-end" for e in graph.edges
        ):
            continue
        if i + 1 >= len(chapters):
            continue
        chapter_fallthrough.append({"chapterId": cid, "label": last, "nextChapterId": chapters[i + 1]})
        findings.append(
            _finding(
                "warn",
                "chapter_end_no_exit",
                f"章末 label「{last}」没有 return/jump：导出到 Ren'Py 后会直接流进下一章",
                cid,
                last,
            )
        )

    # 悬空跳转 / 重名 label
    dangling = [
        {"chapterId": e.chapterId, "label": e.label, "target": e.dst}
        for e in graph.edges
        if e.dst and e.dst not in graph.labels
    ]
    for d in dangling:
        findings.append(
            _finding(
                "error",
                "dangling_jump",
                f"跳转目标「{d['target']}」不存在（玩家会卡住或报错）",
                d["chapterId"],
                d["label"],
            )
        )
    duplicates: List[str] = []
    seen: Set[str] = set()
    for _cid, b in iter_project_blocks(project):
        if b.get("type") == "label" and b.get("name"):
            nm = str(b["name"])
            if nm in seen and nm not in duplicates:
                duplicates.append(nm)
            seen.add(nm)
    for nm in duplicates:
        findings.append(
            _finding("error", "duplicate_label", f"label「{nm}」定义了多次：后面的会覆盖前面的", "", nm)
        )

    # 不可达 label
    unreachable = sorted(set(graph.labels) - reachable)
    for nm in unreachable:
        findings.append(
            _finding(
                "warn",
                "unreachable_label",
                f"label「{nm}」从入口走不到（死代码；玩家永远看不到它）",
                graph.labels[nm]["chapterId"],
                nm,
            )
        )

    # 循环
    for cyc in cycles:
        if cyc["canLoopForever"]:
            findings.append(
                _finding(
                    "error",
                    "loop_no_exit",
                    "死循环："
                    + " → ".join(cyc["labels"])
                    + " 这条回路既没有变量变化也没有条件出口，玩家出不去",
                    graph.labels.get(cyc["labels"][0], {}).get("chapterId", ""),
                    cyc["labels"][0],
                )
            )
        elif cyc["reachable"]:
            findings.append(
                _finding(
                    "info",
                    "plot_cycle",
                    "回路：" + " → ".join(cyc["labels"]) + "（有变量或条件出口，通常是有意的 hub）",
                    graph.labels.get(cyc["labels"][0], {}).get("chapterId", ""),
                    cyc["labels"][0],
                )
            )

    for r in cond["invalid"]:
        findings.append(
            _finding("error", "invalid_condition", f"条件写法不合法：{r['text']}（{r['error']}）", r["chapterId"])
        )
    for r in cond["typeMismatch"]:
        findings.append(
            _finding("error", "condition_type_mismatch", r["reason"], r["chapterId"])
        )
    for r in cond["neverTrue"]:
        if r.get("where") != "choice":  # 选项那条已在菜单里报过，避免重复
            findings.append(
                _finding(
                    "warn",
                    "condition_never_true",
                    f"if 条件恒不成立：{r['text']}（{r['reason']}）",
                    r["chapterId"],
                )
            )

    # 分支覆盖：能选得到的选项里，真的被某条可达路径走过的比例。
    # 注意区分两件事：`usable`（条件可满足 = 玩家看得见）和 `traversed`（枚举到的路径
    # 确实经过它）。两者都要报——前者是"能不能选"，后者是"有没有路"。
    choice_edges = [e for e in graph.edges if e.kind == "choice"]
    usable = [e for e in choice_edges if cond_satisfiable_edge(e, cond)]
    traversed = [e for e in usable if path_info["edgeUse"].get(e.index, 0) > 0]
    never_traversed = [e for e in usable if path_info["edgeUse"].get(e.index, 0) == 0]
    labels_total = len(graph.labels)
    labels_reachable = len([n for n in graph.labels if n in reachable])
    paths = path_info["paths"]
    lengths = path_info["lengths"]
    coverage = {
        "labels": {
            "total": labels_total,
            "reachable": labels_reachable,
            "ratio": round(labels_reachable / labels_total, 3) if labels_total else 0.0,
        },
        "choices": {
            "total": len(choice_edges),
            "usable": len(usable),
            "traversed": len(traversed),
            "neverTraversed": len(never_traversed),
            "ratio": round(len(traversed) / len(choice_edges), 3) if choice_edges else 0.0,
            "satisfiableRatio": (
                round(len(usable) / len(choice_edges), 3) if choice_edges else 0.0
            ),
        },
        "paths": {
            "count": paths,
            "truncated": path_info["truncated"],
            "minLabels": min(lengths) if lengths else 0,
            "maxLabels": max(lengths) if lengths else 0,
            "avgLabels": round(sum(lengths) / len(lengths), 1) if lengths else 0.0,
        },
        "terminals": sorted((path_info.get("terminals") or {}).keys()),
    }
    coverage["score"] = round(
        (
            coverage["labels"]["ratio"]
            + (coverage["choices"]["ratio"] if choice_edges else coverage["labels"]["ratio"])
        )
        / 2,
        3,
    )
    for e in never_traversed:
        findings.append(
            _finding(
                "warn",
                "choice_never_traversed",
                f"选项「{e.choiceText}」在任何可达路径上都没被走过（检查它所在 label 是否可达）",
                e.chapterId,
                e.label,
            )
        )

    order = {"error": 0, "warn": 1, "info": 2}
    findings.sort(key=lambda f: (order.get(str(f["severity"]), 3), str(f["code"]), str(f["message"])))
    counts = Counter(str(f["severity"]) for f in findings)
    return {
        "graph": {
            "labels": labels_total,
            "edges": len(graph.edges),
            "roots": [graph.root()] if graph.root() else [],
            "edgeKinds": dict(Counter(e.kind for e in graph.edges)),
        },
        "coverage": coverage,
        "cycles": cycles,
        "deadBlocks": dead_blocks,
        "chapterEndWithoutExit": chapter_fallthrough,
        "danglingJumps": dangling,
        "duplicateLabels": duplicates,
        "unreachableLabels": unreachable,
        "conditions": cond["conditions"],
        "variables": cond["domain"],
        "menus": menus,
        "endings": endings,
        "findings": findings,
        "counts": {
            "error": counts.get("error", 0),
            "warn": counts.get("warn", 0),
            "info": counts.get("info", 0),
            "pass": counts.get("error", 0) == 0,
        },
    }


def cond_satisfiable_edge(edge: Edge, cond: Dict[str, Any]) -> bool:
    """这条选项边在当前条件下是否**有可能被玩家选到**。"""
    if not edge.condition.strip():
        return True
    for r in cond["neverTrue"]:
        if (
            r.get("where") == "choice"
            and r["chapterId"] == edge.chapterId
            and r.get("branchIndex") == edge.choiceIndex
            and r["text"] == edge.condition
        ):
            return False
    return True
