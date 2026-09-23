"""自适应选项：让导出到 Ren'Py 的作品能**按读者自己的选择历史**调整分支。

问题
----
"自适应选项"（剧情随读者历史变化）此前完全没有。它需要两件东西：
① 引擎里要有**跨存档持续存在的读者状态**；② 作者能基于它写条件。
难点在于：让作者**先给每个选项打标签**，就要改数据模型 + 编辑器 UI，成本高且容易被忽略。

这里的做法是**从现有的 `set` 块自动派生**：
某个选项本来就改了 `affection`，那就说明"这个读者的选择体现了一种倾向"。
导出时在该选项体内自动追加一行

    $ persistent.reader_tendency_affection += 1

于是作者不需要任何新 UI，就能在后续选项的条件里直接写

    if persistent.reader_tendency_affection >= 3:

做到"老是心软的人更容易看到某条支线"这类自适应。

设计取舍
--------
1. **用 `persistent` 而不是普通变量**：普通变量随存档各自独立，
   `persistent` 才是"这个玩家在所有存档里的一贯倾向"。自适应要的正是后者。
2. **只在选项真的改了变量时才计数**：否则会给每个选项都造一个没意义的计数器。
3. **计数器名带 `reader_tendency_` 前缀**：与作者自己的变量隔离，避免撞名；
   并过一遍标识符白名单，防止变量 key 里的怪字符被写进 .rpy（那是代码位置）。
4. **默认关闭**：这是会改变导出产物语义的功能，必须显式开启（`adaptive_reader=True`），
   否则"同一份剧本导出两次、产物不同"会让作者困惑。
5. **不碰试玩器**：试玩器仍然按作者写死的条件演；自适应只作用于导出后的 Ren'Py。
   让试玩器也模拟 persistent 是另一件事（它没有跨局状态），没做，也不假装做了。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Mapping, Optional, Tuple

from app.core.blocks import iter_project_blocks, walk_blocks
from app.domain.types import VnProject

#: persistent 计数器前缀：与作者自己的变量隔离，一眼能看出是工具生成的。
TENDENCY_PREFIX = "reader_tendency_"

#: Ren'Py 标识符白名单（与 `renpy._safe_ident` 同风格：代码位置只允许这套字符）。
_IDENT_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")

#: 计数器首次出现时的初值。
DEFAULT_TENDENCY_VALUE = 0


def _safe_ident(value: Any, fallback: str = "var") -> str:
    """把变量 key 收敛成合法标识符；非法字符一律换成下划线。"""
    raw = str(value or "").strip()
    cleaned = re.sub(r"[^A-Za-z0-9_]", "_", raw)
    if not cleaned:
        cleaned = fallback
    if not cleaned[0].isalpha() and cleaned[0] != "_":
        cleaned = f"_{cleaned}"
    return cleaned if _IDENT_RE.match(cleaned) else fallback


def tendency_counter_name(key: Any) -> str:
    """变量 key → persistent 计数器名（可逆前缀，便于作者辨认）。**不含** `persistent.`。"""
    return f"{TENDENCY_PREFIX}{_safe_ident(key)}"


def tendency_counter_ref(key: Any) -> str:
    """变量 key → Ren'Py 里可直接读写的引用（``persistent.reader_tendency_x``）。

    ``persistent.`` 前缀不能省：省掉写进去的就是一个普通全局变量，**存档之间各自独立**，
    而"读者一贯的选择倾向"要的正是跨存档。实现时正是漏了这个前缀——
    导出后看着像在计数，实际每次读档都从 0 开始，"自适应"等于没做。
    """
    return f"persistent.{tendency_counter_name(key)}"


def choice_tendency_keys(choice: Mapping[str, Any]) -> List[str]:
    """一个选项 → 它在正文里改过的变量 key（去重、保序）。

    只认 ``set`` 块，且**包含菜单选项正文里嵌套的 set**（`if` / 内层 menu 里的也算）：
    只扫顶层会漏掉"满足条件才加好感"这种最常见的写法。
    """
    keys: List[str] = []
    for sub in walk_blocks(list(choice.get("blocks") or [])):
        if sub.get("type") == "set" and sub.get("key"):
            key = str(sub["key"])
            if key not in keys:
                keys.append(key)
    return keys


def choice_increment_lines(choice: Mapping[str, Any]) -> List[str]:
    """一个选项被选中时要插入的 Ren'Py 语句（可以是空列表）。

    这些行会被放在选项正文的**最前面**：无论后面是 jump 还是内联正文，
    都要保证"选了它就计数"，所以必须先于其它语句。
    """
    return [f"$ {tendency_counter_ref(key)} += 1" for key in choice_tendency_keys(choice)]


def tendency_counters(project: VnProject) -> Dict[str, str]:
    """全项目用到的倾向计数器：变量 key → 计数器名（按 key 排序，结果稳定）。"""
    keys: List[str] = []
    for _cid, block in iter_project_blocks(project):
        if block.get("type") != "menu":
            continue
        for choice in block.get("choices") or []:
            if not isinstance(choice, Mapping):
                continue
            for key in choice_tendency_keys(choice):
                if key not in keys:
                    keys.append(key)
    return {key: tendency_counter_name(key) for key in sorted(keys)}


def adaptive_prelude_lines(project: VnProject) -> List[str]:
    """放 .rpy 开头的声明：给每个倾向计数器一个 persistent 初值。"""
    return [
        f"default persistent.{counter} = {DEFAULT_TENDENCY_VALUE}"
        for _key, counter in tendency_counters(project).items()
    ]


def export_adaptive_prelude(project: VnProject) -> str:
    """声明块文本（没有可选计数的剧本返回空串，不制造空注释块）。"""
    lines = adaptive_prelude_lines(project)
    if not lines:
        return ""
    header = [
        "# --- 读者倾向计数器（VN Script Studio 自动生成）---",
        "# 每选定一个会改变量的选项，对应计数器 +1；它存在 persistent 里，",
        "# 因此跨存档保留——用来写「这个读者一贯怎么选」的自适应条件。",
    ]
    return "\n".join([*header, *lines])


def condition_recipes(project: VnProject, *, threshold: int = 3) -> List[Dict[str, Any]]:
    """给作者的自适应条件示例（照抄进选项条件即可）。

    只生成**库里真的存在**的计数器：凭空给一个变量编例子，作者粘进去会直接报错。
    """
    out: List[Dict[str, Any]] = []
    for key, counter in tendency_counters(project).items():
        out.append(
            {
                "variableKey": key,
                "counter": f"persistent.{counter}",
                "condition": f"persistent.{counter} >= {threshold}",
                "meaning": (
                    f"这个读者在之前的选项里至少有 {threshold} 次把「{key}」往上涨——"
                    "可以给他开一条更顺的支线。"
                ),
            }
        )
    return out


def analyze_adaptive_opportunities(
    project: VnProject,
    *,
    branch: Optional[Mapping[str, Any]] = None,
    analytics: Optional[Mapping[str, Any]] = None,
) -> Dict[str, Any]:
    """哪些菜单值得做成自适应：结合结构（无后果/一边倒）与读者数据（占比）。

    判定只看**已算好的结果**（不重新解析剧本），与建议引擎同一口径。
    """
    if branch is None:
        from app.core.branch_analysis import analyze_branches

        branch = analyze_branches(project)

    counters = tendency_counters(project)
    reader_share: Dict[Tuple[str, int], float] = {}
    for report in ((analytics or {}).get("choices") or {}).get("menus") or []:
        if not isinstance(report, Mapping):
            continue
        mid = str(report.get("menuId") or "menu")
        for opt in report.get("options") or []:
            if isinstance(opt, Mapping):
                try:
                    reader_share[(mid, int(opt.get("index", -1)))] = float(
                        opt.get("share") or 0.0
                    )
                except (TypeError, ValueError):
                    continue

    candidates: List[Dict[str, Any]] = []
    for menu in branch.get("menus") or []:
        if not isinstance(menu, Mapping):
            continue
        mid = str(menu.get("menuId") or "menu")
        options = [o for o in (menu.get("choices") or []) if isinstance(o, Mapping)]
        if len(options) < 2:
            continue
        signatures = {
            f"{o.get('effect')}:{o.get('target') or ''}|{','.join(sorted(str(v) for v in (o.get('varsModified') or [])))}"
            for o in options
        }
        no_effect = len(signatures) == 1
        shares = [reader_share.get((mid, int(o.get("index", i))), None) for i, o in enumerate(options)]
        known = [s for s in shares if s is not None]
        dominant = bool(known) and max(known) >= 0.9
        if not (no_effect or dominant):
            continue
        reason_bits = []
        if no_effect:
            reason_bits.append("所有选项后果完全相同（选哪个都一样）")
        if dominant:
            reason_bits.append("读者几乎总是选同一个选项")
        candidates.append(
            {
                "menuId": mid,
                "chapterId": str(menu.get("chapterId") or ""),
                "optionCount": len(options),
                "reason": "；".join(reason_bits),
                "suggestion": (
                    "把它做成自适应：让一侧按读者的历史倾向变化（"
                    + "、".join(f"persistent.{c}" for c in list(counters.values())[:2])
                    + "），另一侧不变——这样同一屏对不同读者有不同意义。"
                    if counters
                    else "先在某个选项里改变量（例如好感），工具就会为它生成读者倾向计数器，"
                    "然后你就能在这一屏写自适应条件。"
                ),
            }
        )

    return {
        "tendencyCounters": counters,
        "recipeThreshold": 3,
        "recipes": condition_recipes(project),
        "candidates": candidates,
        "prelude": export_adaptive_prelude(project),
        "notes": [
            "计数器存在 persistent 里，跨存档保留：它描述的是「这个读者一贯怎么选」。",
            "导出时加 adaptive_reader=True 才会把计数语句写进 .rpy；默认不加，"
            "以免同一份剧本两次导出的产物不一样。",
            "试玩器仍按作者写死的条件演出，不模拟 persistent。",
        ],
    }
