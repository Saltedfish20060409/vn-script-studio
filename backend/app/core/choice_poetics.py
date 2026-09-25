"""选项分类：把 Dunyazad 的三分法落成**结构上可判的**信号。

## 依据

- **Towards a Theory of Choice Poetics**（FDG 2014,
  https://cs.wellesley.edu/~pmwh/research/papers/towards-choice-poetics-fdg-2014.pdf）：
  选择的意义来自**玩家放弃了什么**——没有取舍的选择不是选择。
- **Intentionally Generating Choices in Interactive Narratives**（ICCC 2015,
  https://computationalcreativity.net/iccc2015/proceedings/13_4Mateas.pdf）与
  **Dunyazad**（AIIDE, https://ojs.aaai.org/index.php/AIIDE/article/view/12791）：
  作者应当**有意识地混用**三类选择——relaxed（怎么选都行）、obvious（意图明确）、
  dilemma（两难：两边都要付出代价）。

## 我们只能判结构，不能判心理

三篇讲的都是"玩家的体验"，而体验需要真人。剧本里能**客观判**的只有结构：
选项把玩家送去了哪里、改了哪些状态。所以这里的分类是**结构代理**，
命名上照搬那套词汇，但判据写死在这段代码里，报告里也如实标注"结构启发式"：

| 类 | 结构判据 |
|---|---|
| `relaxed` | 与其他选项的后果**完全相同**（同目标、同变量改动）→ 选谁都一样 |
| `obvious` | 后果与其他选项不同，但**不涉及同一变量上的互斥取值** → 意图明确、代价不明 |
| `dilemma` | 与同菜单的另一个选项在**同一个变量上取互斥的值**（或一边设值、另一边设另一个值）→ 真正的取舍：选了 A 就拿不到 B |

判"两难"用"同一变量互斥取值"而不是"分支不再汇合"：后者要看跨 label 的可达性，
在剧本规模上容易把"两条线走了很久又合流"误判成永久分叉；而"同一状态位取了互斥的值"
是**玩家真的拿不到两样东西**的直接证据，也能在结构上确定地判出来。

## 我们不做的事

- 不判"选项文案写得好不好""玩家会不会犹豫"——那需要真人，模型打分也不可靠
  （见 Art or Artifice?，docs/references.md）。
- 不把"没有 dilemma"当成错误：日常系作品的 relaxed 选择是有意为之。
  所以这类提示一律只报 info，并且**给出"缺哪一类、有几个菜单"的量**，由作者决定。
"""

from __future__ import annotations

from typing import Any, Dict, List, Mapping, Optional

from app.core.branch_analysis import analyze_branches, build_graph, reachable_from
from app.domain.types import VnProject

CLASS_RELAXED = "relaxed"
CLASS_OBVIOUS = "obvious"
CLASS_DILEMMA = "dilemma"

#: 类名给界面看的解释（用作者的语言，不用论文术语）。
CLASS_LABELS: Dict[str, str] = {
    CLASS_RELAXED: "怎么选都一样",
    CLASS_OBVIOUS: "意图明确（后果可预期，但没有代价）",
    CLASS_DILEMMA: "两难（两边都要付出代价）",
}


def _vars_of(choice: Mapping[str, Any]) -> Dict[str, str]:
    """选项改动的变量。缺失时为 None（不是空字典）：**不知道**与**没改**要分得开。"""
    raw = choice.get("varsModified")
    if raw is None:
        return {}
    return {str(v): "" for v in raw if str(v)}


def _signature(choice: Mapping[str, Any]) -> str:
    return f"{choice.get('effect')}:{choice.get('target') or ''}"


def classify_choice_menu(menu: Mapping[str, Any]) -> Dict[str, Any]:
    """给一个菜单里的每个选项分类，并给出菜单级结论。

    返回 ``{choices: [{index, text, klass, reason}], counts, verdict}``。
    ``verdict`` 取：
    - ``all_relaxed``：所有选项后果相同（玩家选谁都一样）
    - ``has_dilemma``：至少有一个两难选项（有取舍）
    - ``no_dilemma``：选项之间有差别，但没有一处取舍
    """
    options = [c for c in (menu.get("choices") or []) if isinstance(c, Mapping)]
    if not options:
        return {"choices": [], "counts": {}, "verdict": "empty"}

    sigs = [_signature(c) for c in options]
    vars_by_choice = [_vars_of(c) for c in options]

    # 同一变量在菜单里被赋了"不同的值" → 互斥。只知道改了哪些 key 时，
    # 用"分属不同选项"本身作为互斥的保守近似（同一选项里改两个 key 不算取舍）。
    var_owners: Dict[str, set] = {}
    for idx, keys in enumerate(vars_by_choice):
        for key in keys:
            var_owners.setdefault(key, set()).add(idx)
    exclusive_keys = {k for k, owners in var_owners.items() if len(owners) >= 2}

    classified: List[Dict[str, Any]] = []
    for idx, choice in enumerate(options):
        sig = sigs[idx]
        shared = sum(1 for other in sigs if other == sig)
        keys = set(vars_by_choice[idx]) & exclusive_keys

        if shared >= 2 and not keys:
            klass = CLASS_RELAXED
            reason = "这个选项的后果与菜单里另一个选项完全相同（同目标、同变量），选了没有区别"
        elif keys:
            klass = CLASS_DILEMMA
            reason = (
                "与同菜单的另一个选项在「"
                + "、".join(sorted(keys))
                + "」上取不同的值：选了这边就拿不到那边"
            )
        else:
            klass = CLASS_OBVIOUS
            reason = "后果与其它选项不同，但不与任何选项争同一个状态位（意图清楚、没有代价）"
        classified.append(
            {
                "index": idx,
                "text": str(choice.get("text") or "").strip(),
                "klass": klass,
                "reason": reason,
                "target": choice.get("target"),
                "varsModified": sorted(vars_by_choice[idx]),
            }
        )

    counts: Dict[str, int] = {CLASS_RELAXED: 0, CLASS_OBVIOUS: 0, CLASS_DILEMMA: 0}
    for row in classified:
        counts[row["klass"]] += 1
    if counts[CLASS_DILEMMA]:
        verdict = "has_dilemma"
    elif len(set(sigs)) == 1:
        verdict = "all_relaxed"
    else:
        verdict = "no_dilemma"
    return {"choices": classified, "counts": counts, "verdict": verdict}


def analyze_choice_variety(
    project: VnProject, *, branch: Optional[Mapping[str, Any]] = None
) -> Dict[str, Any]:
    """整本书的选项分类与"缺哪一类"的量。

    与 `branch_recommendations` 一样，优先复用**已经算好的**分支分析结果
    （``branch``），避免两处各解析一遍剧本。
    """
    data = branch if branch is not None else analyze_branches(project)
    menus_out: List[Dict[str, Any]] = []
    counts: Dict[str, int] = {CLASS_RELAXED: 0, CLASS_OBVIOUS: 0, CLASS_DILEMMA: 0}
    all_relaxed_menus: List[str] = []

    for menu in data.get("menus") or []:
        if not isinstance(menu, Mapping):
            continue
        result = classify_choice_menu(menu)
        if not result["choices"]:
            continue
        where = f"{menu.get('chapterId') or ''}/{menu.get('menuId') or 'menu'}"
        for key, value in result["counts"].items():
            counts[key] = counts.get(key, 0) + value
        if result["verdict"] == "all_relaxed":
            all_relaxed_menus.append(where)
        menus_out.append(
            {
                "where": where,
                "prompt": str(menu.get("prompt") or "").strip(),
                "verdict": result["verdict"],
                "counts": result["counts"],
                "choices": result["choices"],
            }
        )

    notes = [
        "分类是**结构启发式**（看选项把玩家送去哪、改了哪些状态），不是对玩家心理的判断。",
        "「怎么选都一样」用同目标同变量判；「两难」用同一状态位上取互斥值判——"
        "玩家真的拿不到两样东西，这是结构上能确定的事实。",
        "没有两难选择不是错误：日常系作品的轻松选择是有意为之，所以只报 info。",
    ]
    return {
        "menus": menus_out,
        "counts": {**counts, "menus": len(menus_out)},
        "classLabels": CLASS_LABELS,
        "allRelaxedMenus": all_relaxed_menus,
        "notes": notes,
    }


def variety_recommendations(variety: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """把分类结果变成两条可执行的建议（供 branch_recommendations 合并进现有列表）。

    只做两条，都指向**具体改法**：
    - 整菜单怎么选都一样 → 给出是哪个菜单，怎么让它有区别；
    - 整本书没有一个两难选择 → 说明"缺哪一类"，并给一个可落地的写法。
    """
    out: List[Dict[str, Any]] = []
    counts = variety.get("counts") or {}
    relaxed_menus = list(variety.get("allRelaxedMenus") or [])
    if relaxed_menus:
        out.append(
            {
                "code": "menu_all_relaxed",
                "severity": "info",
                "title": f"有 {len(relaxed_menus)} 个菜单「怎么选都一样」",
                "why": "这些菜单里所有选项的目标与状态改动完全相同，玩家选谁都不影响后面。"
                "（判据是结构：同目标、同变量）",
                "action": "给其中一个选项加一个状态位（例如好感度或一条「记住了什么」的标记），"
                "或让它跳到不同的 label；本书里已经有别的菜单可以照着写。",
                "where": relaxed_menus[0],
                "evidence": {"menus": relaxed_menus[:8], "count": len(relaxed_menus)},
            }
        )
    if (counts.get("menus") or 0) >= 3 and not counts.get(CLASS_DILEMMA):
        out.append(
            {
                "code": "no_dilemma_choice",
                "severity": "info",
                "title": f"全书 {counts.get('menus')} 个菜单里没有一处真正的取舍",
                "why": "每个菜单的选项都只影响各自的分支，没有出现「选了 A 就拿不到 B」的情况。"
                "选择的意义来自玩家放弃了什么（Choice Poetics）；全是意图明确的选项时，"
                "读者不会觉得在决定什么。",
                "action": "挑一个剧情转折点，让两个选项改同一个状态位的互斥值"
                "（例如「告诉她自己听见了」把信任设为 1、隐瞒设为 0），"
                "后文再按这个状态位分岔。",
                "where": "",
                "evidence": {"menus": counts.get("menus"), "counts": dict(counts)},
            }
        )
    return out


# --------------------------------------------------------- 后果分层（结构代理）
#
# 依据（2026-09 核对，见 docs/references.md 的「视觉小说 / 轻小说实务（参考层）」）：
# - JSET 2024 那篇把「**按正解 / 部分正解 / 不正解分别决定结果的展开**」列为分支设计的一步
#   （原文第 4 条：正解、部分的正解、不正解に即した結果のストーリー展開を決める）。
# - ビジュアルノベル先行研究サーベイ（デジタルゲーム学研究）把 VN 的表达力归到
#   「用选项操作故事 / 坏结局 / 别的路线 → 只有玩家站在超越视角反复经历」这一类结构上。
#
# 我们能判的只有**结构**：某个选项把玩家送到哪、后面还有多少内容、是否走到结局、
# 是否与同菜单的别的选项汇合。所以这里是**后果形态**的描述，不是"这个结局好不好"。

CONSEQUENCE_CONTINUES = "continues"
CONSEQUENCE_REJOINS = "rejoins"
CONSEQUENCE_SHORT_END = "short_end"
CONSEQUENCE_UNKNOWN = "unknown"

#: 给界面看的解释（作者语言）。
CONSEQUENCE_LABELS: Dict[str, str] = {
    CONSEQUENCE_CONTINUES: "继续往下走（与别的选项不汇合）",
    CONSEQUENCE_REJOINS: "与同菜单的别的选项汇合（差在状态上）",
    CONSEQUENCE_SHORT_END: "只走到一个很短的结局（坏结局/提前收场）",
    CONSEQUENCE_UNKNOWN: "看不出后果（原地写正文 / 目标解析不出来）",
}

#: "很短的结局"阈值：目标之后只有 ≤ 这么多个 label 就结束。
SHORT_TAIL_NODES = 3
#: 后果分量悬殊的倍数阈值（手调）：最大 / 最小 ≥ 这个值且都 ≥ 1 才算悬殊。
IMBALANCE_RATIO = 4.0

CONSEQUENCE_BASIS = (
    "JSET 2024《正解・部分的正解・不正解に即した結果のストーリー展開を決める》；"
    "ビジュアルノベル先行研究サーベイ（デジタルゲーム学研究）——"
    "两者都把「选项把玩家送到哪、走到哪个结局」当成可设计的结构"
)


def _ending_labels(project: VnProject, graph: Any) -> set:
    """判定"走到结局"用的 label 集合：作者声明的结局 + 图里的**终端** label。

    终端 = 没有任何出边的 label（`graph.edges` 是按边存的，`labels[...]["edges"]` 是空的——
    踩过一次：按后者算会把每个 label 都当成结局，于是"是否走到结局"永远为真）。
    """
    labels: set = set()
    for e in project.endings or []:
        target = str(getattr(e, "label", None) or getattr(e, "target", None) or "").strip()
        if target:
            labels.add(target)
    has_outgoing = {
        str(edge.src)
        for edge in (getattr(graph, "edges", None) or [])
        if getattr(edge, "dst", None)
    }
    for name in (getattr(graph, "labels", {}) or {}):
        if name not in has_outgoing:
            labels.add(name)
    return labels


def analyze_consequence_tiers(
    project: VnProject, *, branch: Optional[Mapping[str, Any]] = None
) -> Dict[str, Any]:
    """每个选项的**后果形态**：继续 / 汇合 / 短结局 / 看不出，以及全书分布。

    与 `analyze_choice_variety` 互补：那个判"这个菜单是不是白选"，这个判
    "选下去之后玩家各自被送到哪"（后果是否真的分层）。两者都只给结构事实。
    """
    data = branch if branch is not None else analyze_branches(project)
    graph = build_graph(project)
    endings = _ending_labels(project, graph)

    menus_out: List[Dict[str, Any]] = []
    counts: Dict[str, int] = {
        CONSEQUENCE_CONTINUES: 0,
        CONSEQUENCE_REJOINS: 0,
        CONSEQUENCE_SHORT_END: 0,
        CONSEQUENCE_UNKNOWN: 0,
    }
    tails: List[int] = []

    for menu in data.get("menus") or []:
        if not isinstance(menu, Mapping):
            continue
        options = [c for c in (menu.get("choices") or []) if isinstance(c, Mapping)]
        if not options:
            continue
        # 先算每个选项的可达集合，才能判"是否与别人汇合"
        reach: List[Optional[set]] = []
        for choice in options:
            target = str(choice.get("target") or "").strip()
            if str(choice.get("effect") or "") == "inline" or not target:
                reach.append(None)  # 原地写正文：没有独立后果，不猜
            elif target not in graph.labels:
                reach.append(None)
            else:
                reach.append(reachable_from(graph, target))

        rows: List[Dict[str, Any]] = []
        for idx, choice in enumerate(options):
            nodes = reach[idx]
            if nodes is None:
                tier = CONSEQUENCE_UNKNOWN
                size = 0
                reaches = False
                rejoins = False
            else:
                size = len(nodes)
                reaches = bool(nodes & endings)
                # "汇合"要看**非结局**的公共后续：所有路最终走到同一个结局是常态，
                # 那不算"走了弯路又回来"（否则每个菜单都会被判成汇合）。
                rejoins = any(
                    other is not None and bool((nodes & other) - endings)
                    for j, other in enumerate(reach)
                    if j != idx
                )
                if reaches and size <= SHORT_TAIL_NODES:
                    tier = CONSEQUENCE_SHORT_END
                elif rejoins:
                    tier = CONSEQUENCE_REJOINS
                else:
                    tier = CONSEQUENCE_CONTINUES
                tails.append(size)
            counts[tier] += 1
            rows.append(
                {
                    "index": idx,
                    "text": str(choice.get("text") or "").strip(),
                    "tier": tier,
                    "tierLabel": CONSEQUENCE_LABELS[tier],
                    "target": choice.get("target"),
                    "reachableNodes": size,
                    "reachesEnding": reaches,
                    "rejoins": rejoins,
                    "available": bool(choice.get("available", True)),
                }
            )
        menus_out.append(
            {
                "where": f"{menu.get('chapterId') or ''}/{menu.get('menuId') or 'menu'}",
                "prompt": str(menu.get("prompt") or "").strip(),
                "choices": rows,
            }
        )

    imbalance: Optional[Dict[str, Any]] = None
    resolved = [n for n in tails if n >= 1]
    if len(resolved) >= 2:
        smallest, largest = min(resolved), max(resolved)
        ratio = round(largest / smallest, 2)
        if ratio >= IMBALANCE_RATIO:
            imbalance = {"min": smallest, "max": largest, "ratio": ratio, "options": len(resolved)}

    return {
        "menus": menus_out,
        "counts": {**counts, "menus": len(menus_out), "optionsResolved": len(resolved)},
        "tierLabels": CONSEQUENCE_LABELS,
        "imbalance": imbalance,
        "basis": CONSEQUENCE_BASIS,
        "notes": [
            "后果形态是**结构读数**：看选项把玩家送到哪、后面还有多少内容、是否走到结局、"
            "是否与同菜单别的选项汇合——不判断这个结局写得好不好。",
            "「继续往下走」与「汇合」的区分依据是可达集合是否与别的选项相交："
            "汇合是「部分对 / 走了弯路又回来」的结构形态。",
            "看不到后果（原地写正文 / 目标解析不出来）一律记 unknown，不猜。",
        ],
    }


def consequence_recommendations(tiers: Mapping[str, Any]) -> List[Dict[str, Any]]:
    """后果分层的可执行建议（目前只出一条：分量悬殊）。

    为什么只出一条：JSET 那套"正解/部分正解/不正解"要求作者**有意识地分层**，
    而"该不该有坏结局"是设计选择（kinetic 作品一个结局也没有问题）。
    所以只有"同一菜单里选项分量差 4 倍以上"这种**通常不是有意**的形态才提示。
    """
    out: List[Dict[str, Any]] = []
    imbalance = tiers.get("imbalance")
    if isinstance(imbalance, Mapping):
        out.append(
            {
                "code": "consequence_imbalance",
                "severity": "info",
                "title": (
                    f"有几个选项的后果分量悬殊：最长的一条要到 {imbalance.get('max')} 个节点，"
                    f"最短的只到 {imbalance.get('min')} 个（相差 {imbalance.get('ratio')} 倍）"
                ),
                "why": "分支设计里，选项之间的'分量'应当与它代表的取舍相当"
                "（JSET 2024：按正解/部分正解/不正解分别决定结果的展开）。"
                "相差数倍通常不是有意的，而是某条线只写了一句就跳回主线。",
                "action": "给那条最短的分支补一小段收束（它的后果值得一点展开），"
                "或者把它改成不额外分支的 inline 选项——两种都比「点进去只有一句话」好。",
                "where": "",
                "evidence": dict(imbalance),
            }
        )
    return out
