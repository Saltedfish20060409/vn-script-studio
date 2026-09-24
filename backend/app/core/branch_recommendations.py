"""分支改进建议：把"静态结构分析"与"读者实际行为"融成可执行的改稿建议。

为什么单独一层
--------------
到目前为止我们有两条互不相干的事实来源：

- `core/branch_analysis.py`：**结构上**哪里写坏了（无后果选项、软锁、死循环、走不到的结局）；
- `services/playtest_telemetry`：**经验上**读者实际怎么选（没人选的选项、没人走到的结局、覆盖率）。

两者单独看都只是"事实"，作者真正要的是**该怎么办**。举一个只有融合才看得见的例子：

    某个选项静态上完全合法（条件可满足、路径可达），但 12 次试玩里 **0 次**被选。
    只看静态分析 → 没问题；只看读者数据 → "这个选项没人选"（然后呢？）。
    融起来才能给出可执行的判断：**要么它其实不可见（条件过严/被别的选项挤掉），
    要么它本来就没意义（和另一个选项后果相同）**——这两条改法完全不同。

排序与置信度
------------
每条建议都带 ``priority``（确定性打分）与 ``confidence``：

- ``priority`` = 严重度基数 + 经验证据强度。例如"没人选"在只有 3 次试玩时不该和
  200 次试玩时一样大声，所以按样本量加成。
- ``confidence`` 明确区分 ``evidence``（有读者数据支撑）与 ``static``（只有静态推断）。
  **没有读者数据时绝不假装有**：``basis`` 字段会写 ``script-only``，
  且所有依赖读者数据的建议都不会出现（而不是给个 0% 让人误读）。

全部是纯函数、纯本地计算：给定同样输入永远产出同样结果（含排序），因此可进单测与 CI。
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional, Tuple

from app.domain.types import VnProject

#: 低于这个试玩次数就不做经验判断：3 次试玩里"没人选"什么也说明不了。
MIN_RUNS_FOR_EVIDENCE = 10

#: 低覆盖率的判定线（读者走过的可用选项 / 剧本可用选项）。
LOW_COVERAGE_RATIO = 0.5

#: 某个选项占比超过它、而别的选项几乎没人选时，提示"这其实不是选择"。
DOMINANT_SHARE = 0.9

_SEVERITY_BASE: Dict[str, int] = {"error": 100, "warn": 50, "info": 20}


def _rec(
    code: str,
    severity: str,
    title: str,
    why: str,
    action: str,
    *,
    evidence: Optional[Dict[str, Any]] = None,
    confidence: str = "static",
    boost: int = 0,
    where: str = "",
) -> Dict[str, Any]:
    """构造一条建议。``why`` 说清依据，``action`` 说清**具体怎么改**。"""
    return {
        "code": code,
        "severity": severity,
        "priority": _SEVERITY_BASE.get(severity, 20) + max(0, int(boost)),
        "confidence": confidence,
        "title": title,
        "why": why,
        "action": action,
        "where": where,
        "evidence": evidence or {},
    }


def _menu_key(menu: Mapping[str, Any]) -> str:
    return f"{menu.get('chapterId') or ''}/{menu.get('menuId') or 'menu'}"


def _effect_signature(menu: Mapping[str, Any]) -> Tuple[str, ...]:
    """菜单的"后果签名"：每个选项（效果类型, 目标, 改动变量）拼起来。

    与 `branch_analysis._choice_effect` 同源，但这里只在**已算好的结果**上做聚合，
    不重新解析剧本——两处各解析一遍，迟早会出现建议与体检报告互相打架。
    """
    sig: List[str] = []
    for opt in menu.get("choices") or []:
        if not isinstance(opt, Mapping):
            continue
        vars_modified = sorted(str(v) for v in (opt.get("varsModified") or []))
        sig.append(
            f"{opt.get('effect')}:{opt.get('target') or ''}|{','.join(vars_modified)}"
        )
    return tuple(sig)


# ---------------------------------------------------------------- 静态类建议


def _static_recommendations(branch: Mapping[str, Any]) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []

    for cyc in branch.get("cycles") or []:
        if not isinstance(cyc, Mapping) or not cyc.get("canLoopForever"):
            continue
        labels = " → ".join(str(x) for x in (cyc.get("labels") or []))
        out.append(
            _rec(
                "loop_no_exit",
                "error",
                "存在玩家出不去的死循环",
                f"「{labels}」这条回路既没有变量变化、也没有条件出口。",
                "在回路上加一个能真正改变状态的变量赋值（例如计数 +1），"
                "或给其中一个选项加条件，让读者有办法离开这一段。",
                evidence={"labels": list(cyc.get("labels") or [])},
            )
        )

    for menu in branch.get("menus") or []:
        if not isinstance(menu, Mapping):
            continue
        where = _menu_key(menu)
        options = [o for o in (menu.get("choices") or []) if isinstance(o, Mapping)]
        labels = [str(f.get("code")) for f in (menu.get("findings") or []) if isinstance(f, Mapping)]
        if "menu_always_empty" in labels:
            out.append(
                _rec(
                    "softlock_menu",
                    "error",
                    "存在没有可选项的菜单",
                    f"菜单「{where}」所有选项的条件都恒不成立，读者走到这里会卡住。",
                    "检查这些条件引用的变量有没有在别处被赋过值；"
                    "至少要留一个无条件选项兜底。",
                    where=where,
                )
            )
        sig = _effect_signature(menu)
        if len(sig) >= 2 and len(set(sig)) == 1:
            out.append(
                _rec(
                    "no_effect_menu",
                    "warn",
                    "这个菜单选哪个都一样",
                    f"菜单「{where}」的 {len(sig)} 个选项后果完全相同（同一种出口、都不改变量）。",
                    "让至少一个选项产生真实差异：改一个变量（好感/旗标），"
                    "或让它跳向不同的 label——否则这一屏可以删掉，或者改成纯演出。",
                    evidence={"options": len(sig), "signature": sig[0] if sig else ""},
                    where=where,
                )
            )
        if len(options) == 1:
            out.append(
                _rec(
                    "single_option_menu",
                    "info",
                    "只有一个选项的「选择」",
                    f"菜单「{where}」只有 1 个选项，读者没有真正的选择。",
                    "考虑改写成正文（去掉 menu），把这一屏还给叙事节奏。",
                    where=where,
                )
            )

    for e in (branch.get("endings") or {}).get("declared") or []:
        if not isinstance(e, Mapping) or e.get("reachable"):
            continue
        if not e.get("exists"):
            continue
        name = str(e.get("name") or e.get("label") or "")
        out.append(
            _rec(
                "unreachable_ending",
                "error",
                f"结局「{name}」写在剧本里但走不到",
                "它登记在案的 label 存在，但从入口顺着 jump / 选项都到不了。",
                "检查通往它的选项条件是否永远不成立、或上游某个 label 本身不可达；"
                "先修控制流，再谈读者分布。",
                evidence={"label": str(e.get("label") or "")},
                where=str(e.get("label") or ""),
            )
        )
    return out


# ---------------------------------------------------------------- 经验类建议


def _evidence_ready(analytics: Optional[Mapping[str, Any]], min_runs: int) -> bool:
    if not analytics:
        return False
    runs = _as_int((analytics.get("sample") or {}).get("runs"))
    return runs >= max(1, int(min_runs))


def _as_int(value: Any, default: int = 0) -> int:
    try:
        return int(value)
    except (TypeError, ValueError):
        return default


def _as_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _reader_recommendations(
    branch: Mapping[str, Any],
    analytics: Mapping[str, Any],
    *,
    min_runs: int,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    runs = _as_int((analytics.get("sample") or {}).get("runs"))
    choices = analytics.get("choices") or {}
    static_menus = {
        _menu_key(m): m
        for m in (branch.get("menus") or [])
        if isinstance(m, Mapping)
    }
    static_no_effect = {
        key
        for key, menu in static_menus.items()
        if len(_effect_signature(menu)) >= 2
        and len(set(_effect_signature(menu))) == 1
    }

    for report in choices.get("menus") or []:
        if not isinstance(report, Mapping):
            continue
        where = f"{report.get('chapterId') or ''}/{report.get('menuId') or 'menu'}"
        selections = _as_int(report.get("selections"))
        options = [o for o in (report.get("options") or []) if isinstance(o, Mapping)]
        if not options:
            continue
        # 经验证据按样本量加成，但设上限：200 次和 2000 次试玩不该差出一个量级
        boost = min(20, selections // 5) if selections else 0

        never = [o for o in options if o.get("neverSelected") and o.get("available")]
        for opt in never:
            idx = _as_int(opt.get("index"))
            same_as_siblings = where in static_no_effect
            if same_as_siblings:
                why = (
                    f"{selections} 次选择里第 {idx + 1} 个选项被选 0 次，"
                    "而静态分析显示它和其它选项后果完全相同——它多半本来就没有意义。"
                )
                action = "直接删掉它，或者给它一个真实后果（改变量 / 换出口）让它值得被选。"
            else:
                cond = str(opt.get("condition") or "").strip()
                why = (
                    f"{selections} 次选择里第 {idx + 1} 个选项被选 0 次"
                    + (f"（它的条件是「{cond}」）" if cond else "（它没有条件）")
                    + "。"
                )
                action = (
                    f"先确认它到底可不可见：把条件「{cond}」在试玩里逐个试一遍；"
                    "若确实可见却没人选，多半是选项文案没有吸引力或代价太明显，"
                    "把它的收益写得更明确一些。"
                    if cond
                    else "它无条件却没人选：检查它是否被排在最不显眼的位置，"
                    "或它的文案读起来像「坏选项」。"
                )
            out.append(
                _rec(
                    "never_selected_option",
                    "warn",
                    f"第 {idx + 1} 个选项从没人选过",
                    why,
                    action,
                    evidence={
                        "menuId": report.get("menuId"),
                        "index": idx,
                        "selections": selections,
                        "share": _as_float(opt.get("share")),
                        "runs": runs,
                    },
                    confidence="evidence",
                    boost=boost,
                    where=where,
                )
            )

        # 伪二元选择：一个选项吃掉了绝大多数选择
        if selections and len(options) >= 2:
            shares = [(o, _as_float(o.get("share"))) for o in options]
            top = max(shares, key=lambda kv: kv[1])
            others = [s for _o, s in shares if _o is not top[0]]
            if top[1] >= DOMINANT_SHARE and others and max(others) <= (1 - DOMINANT_SHARE):
                top_idx = _as_int(top[0].get("index"))
                # 区间（Dror et al.）：这个"占 X%"是从**同一次试玩内的选择**里算的，
                # 样本少时区间很宽。区间宽到横跨大半个单位区间时，把"共识"当结论就是过度解读，
                # 所以把它写进 evidence 与 why 里，让作者自己看到不确定度。
                ci = top[0].get("shareCi") if isinstance(top[0], Mapping) else None
                thin = bool(
                    isinstance(ci, Mapping) and (ci.get("thin") or ci.get("wide"))
                )
                why = (
                    f"第 {top_idx + 1} 个选项占了 {top[1]:.0%} 的选择，"
                    f"其余选项合计不到 {(1 - DOMINANT_SHARE):.0%}。"
                )
                if thin and isinstance(ci, Mapping):
                    why += (
                        f"注意样本：这个比例来自 {ci.get('n')} 次选择，"
                        f"区间是 {float(ci.get('lo') or 0):.0%}–{float(ci.get('hi') or 0):.0%}"
                        "，还不足以说明读者真的达成了共识。"
                    )
                out.append(
                    _rec(
                        "dominant_option",
                        "info",
                        "这屏其实只有一个「真选项」",
                        why,
                        "两条路：要么承认读者已经达成共识、把它改成正文以加快节奏；"
                        "要么给冷门选项一个读者现在看得见的好处（信息量、角色反应、道具），"
                        "让它进入权衡。",
                        evidence={
                            "menuId": report.get("menuId"),
                            "topIndex": top_idx,
                            "topShare": round(top[1], 4),
                            "selections": selections,
                            "shareCi": dict(ci) if isinstance(ci, Mapping) else None,
                            "smallSample": thin,
                        },
                        confidence="evidence",
                        boost=boost,
                        where=where,
                    )
                )

    coverage = analytics.get("coverage") or {}
    ratio = coverage.get("ratio")
    if ratio is not None and _as_float(ratio) < LOW_COVERAGE_RATIO:
        never_touched = [str(m) for m in (coverage.get("menusNeverTouched") or [])]
        out.append(
            _rec(
                "low_reader_coverage",
                "warn",
                "读者没走到多少分支",
                f"读者实际走过的可用选项只占 {_as_float(ratio):.0%}"
                + (f"，还有 {len(never_touched)} 个菜单从没被碰到" if never_touched else "")
                + "。",
                "这不一定是坏事（可能只是剧情还没写到），但如果这些分支是有意设计的，"
                "就要检查它们的入口：是否藏得太深、是否被上游某个高占比选项吃掉了。",
                evidence={
                    "ratio": round(_as_float(ratio), 4),
                    "menusNeverTouched": never_touched[:10],
                    "runs": runs,
                },
                confidence="evidence",
                boost=min(20, runs // 5),
            )
        )

    endings = analytics.get("endings") or {}
    for row in endings.get("neverReached") or []:
        if not isinstance(row, Mapping):
            continue
        if not row.get("reachableInScript"):
            # 静态就不可达的已经在静态建议里报过，这里不重复
            continue
        name = str(row.get("name") or row.get("label") or "")
        out.append(
            _rec(
                "never_reached_ending",
                "warn",
                f"结局「{name}」写得到、但没人走到",
                f"{runs} 次试玩里没有一次以这个结局结束，而静态分析显示它是可达的。",
                "回溯通往它的选项链：多半是某个前置选项在真实读者手里总被另一个选项压过。"
                "把那条链上的一个关键选项做得更显眼，或把它的收益提前透给读者。",
                evidence={"label": str(row.get("label") or ""), "runs": runs},
                confidence="evidence",
                boost=min(20, runs // 5),
                where=str(row.get("label") or ""),
            )
        )
    return out


# ------------------------------------------------------------------ 入口


def recommend_branch_improvements(
    project: VnProject,
    *,
    branch: Optional[Mapping[str, Any]] = None,
    analytics: Optional[Mapping[str, Any]] = None,
    min_runs: int = MIN_RUNS_FOR_EVIDENCE,
) -> Dict[str, Any]:
    """融合静态分支分析与读者行为数据，产出**可执行**的改稿建议（按优先级排序）。

    ``branch`` 省略时现场计算（`analyze_branches`）；``analytics`` 省略时只出静态建议，
    并在 ``basis`` 里如实标注 ``script-only``。
    """
    if branch is None:
        from app.core.branch_analysis import analyze_branches

        branch = analyze_branches(project)

    rows = _static_recommendations(branch)
    # 选项分类（Dunyazad 三分法的结构代理，见 core/choice_poetics.py）：报"缺哪一类"，
    # 只出 info——没有两难选择不是错误，日常系作品的轻松选择是有意为之。
    from app.core.choice_poetics import analyze_choice_variety, variety_recommendations

    variety = analyze_choice_variety(project, branch=branch)
    for item in variety_recommendations(variety):
        rows.append(_rec(**item))
    basis = "script-only"
    sample_note = (
        "只有静态分析：读者数据要么没开、要么样本还不够（"
        f"至少需要 {min_runs} 次试玩）。依赖读者行为的建议本轮不会出现——"
        "不是「没问题」，是「还看不出来」。"
    )
    if analytics is None:
        pass
    elif _evidence_ready(analytics, min_runs):
        basis = "script+readers"
        runs = _as_int((analytics.get("sample") or {}).get("runs"))
        rows.extend(_reader_recommendations(branch, analytics, min_runs=min_runs))
        sample_note = f"静态分析 + {runs} 次试玩的实际选择。"
    else:
        runs = _as_int(((analytics or {}).get("sample") or {}).get("runs"))
        basis = "script-only"
        sample_note = (
            f"读者数据只有 {runs} 次试玩（低于 {min_runs} 次的门槛），"
            "因此只出静态建议：小样本下的「没人选」说明不了任何事，"
            "报出来只会让人误改剧本。"
        )

    rows.sort(key=lambda r: (-int(r["priority"]), str(r["code"]), str(r["where"])))
    counts: Dict[str, int] = {"error": 0, "warn": 0, "info": 0}
    for r in rows:
        counts[str(r["severity"])] = counts.get(str(r["severity"]), 0) + 1
    return {
        "basis": basis,
        "sampleNote": sample_note,
        "minRuns": min_runs,
        "recommendations": rows,
        "counts": {**counts, "total": len(rows)},
        "summary": {
            "static": sum(1 for r in rows if r["confidence"] == "static"),
            "evidence": sum(1 for r in rows if r["confidence"] == "evidence"),
            "topCode": (rows[0]["code"] if rows else None),
        },
        "coverage": (branch.get("coverage") or {}),
        "choiceVariety": variety,
        "notes": [
            "每条建议都带 why（依据）与 action（具体改法），不做「建议优化剧情」这种空话。",
            "没有任何建议不等于剧本没问题：语义层面的问题（动机、反转、潜台词）不在这里的射程内。",
            "选项分类（怎么选都一样 / 意图明确 / 两难）是**结构启发式**：看选项把玩家送去哪、"
            "改了哪些状态，不判断玩家心理，也不给「这个选项写得好不好」打分。",
        ],
    }
