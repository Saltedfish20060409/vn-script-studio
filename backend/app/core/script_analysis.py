"""剧本工程分析：分支覆盖、结局统计、变量使用、路线时长、文本重复率。

全部是纯函数、纯本地计算（不调模型），因此可以随便跑、可以进单元测试。

作者真正怕的三件事，这里都覆盖：
1. **分支写歪**：某个 label 永远走不到（死代码）、选项条件写错、跳转目标不存在；
2. **结局漏了**：写了 5 个结局，实际只能走到 3 个；
3. **估不准体量**：这条路线玩家要多久、有没有大量重复文本。
"""

from __future__ import annotations

import re
from collections import Counter
from typing import Any, Dict, Iterable, List, Optional, Set, Tuple

from app.core.conditions import ConditionError, condition_keys, parse_condition
from app.domain.types import VnProject

# 阅读速度估算（中文视觉小说）：约 4 字/秒，含旁白与对白。
# 这是**估算**：真人读速、演出停顿、语音长度都会影响实际时长。
CHARS_PER_SECOND = 4.0

_TEXT_MIN_LEN = 8
"""短于此长度的文本不计入重复率（"……""嗯。"这类重复是正常写法）。"""


def _walk(blocks: List[Any]) -> Iterable[Dict[str, Any]]:
    """深度遍历，包含菜单选项正文与 if 分支。"""
    for b in blocks or []:
        if not isinstance(b, dict):
            continue
        yield b
        for choice in b.get("choices") or []:
            if isinstance(choice, dict):
                yield from _walk(choice.get("blocks") or [])
        for branch in b.get("branches") or []:
            if isinstance(branch, dict):
                yield from _walk(branch.get("blocks") or [])


def _all_blocks(project: VnProject) -> List[Tuple[str, Dict[str, Any]]]:
    out: List[Tuple[str, Dict[str, Any]]] = []
    for ch in project.chapters or []:
        for b in _walk(ch.blocks or []):
            out.append((ch.id, b))
    return out


def _label_index(project: VnProject) -> Dict[str, Tuple[str, int]]:
    """label 名 → (chapterId, blockIndex)。跨章查找顺序与试玩器一致（同章优先）。"""
    index: Dict[str, Tuple[str, int]] = {}
    for ch in project.chapters or []:
        for i, b in enumerate(ch.blocks or []):
            if b.get("type") == "label" and b.get("name"):
                index.setdefault(str(b["name"]), (ch.id, i))
    return index


def _jump_targets(project: VnProject) -> List[Tuple[str, str]]:
    """(来源 chapterId, 目标 label) —— 含选项 jump 与线性 jump。"""
    out: List[Tuple[str, str]] = []
    for cid, b in _all_blocks(project):
        if b.get("type") == "jump" and b.get("target"):
            out.append((cid, str(b["target"])))
        if b.get("type") == "menu":
            for choice in b.get("choices") or []:
                if isinstance(choice, dict) and choice.get("jump"):
                    out.append((cid, str(choice["jump"])))
    return out


def reachable_labels(project: VnProject) -> Set[str]:
    """从 start（或首章第一个 label）出发，顺着 jump / 选项可达的 label 集合。

    只做 label 级可达性：菜单选项正文与 if 分支里的正文都算在同一条路径上。
    """
    index = _label_index(project)
    if not index:
        return set()
    root = "start" if "start" in index else next(iter(index))
    # 每个 label 能跳到哪些 label
    edges: Dict[str, Set[str]] = {}
    for cid, target in _jump_targets(project):
        # 找到该 jump 所在 label（同章内往前找最近的 label）
        src = _enclosing_label(project, cid, target)
        edges.setdefault(src, set()).add(target)
    seen: Set[str] = {root}
    stack = [root]
    while stack:
        cur = stack.pop()
        for nxt in edges.get(cur, ()):  # noqa: B007
            if nxt in index and nxt not in seen:
                seen.add(nxt)
                stack.append(nxt)
    return seen


def _enclosing_label(project: VnProject, chapter_id: str, _target: str) -> str:
    """该章最后一个 label（jump 通常写在某个 label 段落里）。

    简化处理：把同一章里所有 jump 都算作"从本章各 label 出发"，因此取本章 label 列表。
    这里返回章内首个 label：配合 edges 的并集使用，等价于"章内可达"。
    """
    for ch in project.chapters or []:
        if ch.id != chapter_id:
            continue
        for b in ch.blocks or []:
            if b.get("type") == "label" and b.get("name"):
                return str(b["name"])
    return "start"


def collect_conditions(project: VnProject) -> List[Dict[str, Any]]:
    """收集所有条件（选项条件 + if 分支），并标出语法错误。"""
    out: List[Dict[str, Any]] = []
    for cid, b in _all_blocks(project):
        if b.get("type") == "menu":
            for i, choice in enumerate(b.get("choices") or []):
                if not isinstance(choice, dict):
                    continue
                raw = (choice.get("condition") or "").strip()
                if raw:
                    out.append(
                        {
                            "chapterId": cid,
                            "where": "choice",
                            "text": raw,
                            "detail": choice.get("text") or f"选项 {i + 1}",
                            "error": _cond_error(raw),
                        }
                    )
        elif b.get("type") == "if":
            for branch in b.get("branches") or []:
                if not isinstance(branch, dict):
                    continue
                raw = (branch.get("condition") or "").strip()
                if raw:
                    out.append(
                        {
                            "chapterId": cid,
                            "where": "if",
                            "text": raw,
                            "detail": "",
                            "error": _cond_error(raw),
                        }
                    )
    return out


def _cond_error(raw: str) -> Optional[str]:
    try:
        parse_condition(raw)
        return None
    except ConditionError as exc:
        return str(exc)


def variable_usage(project: VnProject) -> Dict[str, Any]:
    """变量三态：声明未用 / 使用未声明 / 两种情况都列出来。"""
    declared = [v.key for v in (project.variables or []) if getattr(v, "key", None)]
    used: Set[str] = set()
    for cond in collect_conditions(project):
        try:
            for key in condition_keys(parse_condition(cond["text"])):
                used.add(key)
        except ConditionError:
            continue
    for _cid, b in _all_blocks(project):
        if b.get("type") == "set" and b.get("key"):
            used.add(str(b["key"]))
    return {
        "declared": declared,
        "used": sorted(used),
        "unused": [k for k in declared if k not in used],
        "undeclared": sorted(k for k in used if k not in declared),
    }


def estimate_duration(project: VnProject) -> Dict[str, Any]:
    """按字数与显式等待估算通关时长（分钟）。"""
    total_chars = 0
    wait_seconds = 0.0
    for _cid, b in _all_blocks(project):
        btype = b.get("type")
        if btype in ("dialogue", "narration"):
            total_chars += len(str(b.get("text") or ""))
        elif btype == "wait":
            try:
                wait_seconds += float(b.get("seconds") or 0)
            except (TypeError, ValueError):
                pass
    read_seconds = total_chars / CHARS_PER_SECOND
    total_seconds = read_seconds + wait_seconds
    return {
        "chars": total_chars,
        "readSeconds": int(read_seconds),
        "waitSeconds": int(wait_seconds),
        "totalSeconds": int(total_seconds),
        "minutes": round(total_seconds / 60, 1),
        "assumption": f"按 {CHARS_PER_SECOND:g} 字/秒阅读速度估算（不含语音长度与玩家思考时间）",
    }


def repetition_report(project: VnProject, limit: int = 20) -> Dict[str, Any]:
    """文本重复率：同一句台词/旁白出现多次（忽略空白与标点差异）。"""
    counter: Counter = Counter()
    sample: Dict[str, str] = {}
    total_chars = 0
    for _cid, b in _all_blocks(project):
        if b.get("type") not in ("dialogue", "narration"):
            continue
        raw = str(b.get("text") or "").strip()
        total_chars += len(raw)
        key = _normalize_text(raw)
        if len(key) < _TEXT_MIN_LEN:
            continue
        counter[key] += 1
        sample.setdefault(key, raw)
    dup_items = [(k, n) for k, n in counter.items() if n > 1]
    dup_chars = sum(len(k) * (n - 1) for k, n in dup_items)
    top = sorted(dup_items, key=lambda kv: (-kv[1], -len(kv[0])))[:limit]
    return {
        "totalChars": total_chars,
        "duplicateChars": dup_chars,
        "ratio": round(dup_chars / total_chars, 3) if total_chars else 0.0,
        "uniqueDuplicated": len(dup_items),
        "top": [
            {"text": sample[k][:120], "count": n, "chars": len(k)} for k, n in top
        ],
    }


def _normalize_text(text: str) -> str:
    t = re.sub(r"\s+", "", text or "")
    t = re.sub(r"[，。！？…、；：\"'“”‘’（）()【】\[\]—\-~～!?.,]", "", t)
    return t


def _flow_ends(project: VnProject) -> List[Dict[str, Any]]:
    """结局点：从某个 label 段落出发，走到 return 或本章末尾且没有后继跳转。

    只报"可达的"结局；不可达的会被单列为死代码问题。
    """
    ends: List[Dict[str, Any]] = []
    for ch in project.chapters or []:
        blocks = ch.blocks or []
        current: Optional[str] = None
        has_exit = False
        for i, b in enumerate(blocks):
            btype = b.get("type")
            if btype == "label":
                if current is not None and not has_exit:
                    ends.append({"chapterId": ch.id, "label": current, "via": "fallthrough"})
                current = str(b.get("name") or "")
                has_exit = False
                continue
            if btype in ("jump", "return"):
                has_exit = True
                if btype == "return" and current is not None:
                    ends.append({"chapterId": ch.id, "label": current, "via": "return"})
                    has_exit = True
            elif btype == "menu":
                # 所有选项都 jump 走 → 这一段的控制流确实离开了（是有出口的）；
                # 只要有一个选项是内联正文，就有"落回菜单之后"的可能。
                choices = [c for c in (b.get("choices") or []) if isinstance(c, dict)]
                if choices and all(c.get("jump") for c in choices):
                    has_exit = True
        if current is not None and not has_exit:
            ends.append({"chapterId": ch.id, "label": current, "via": "fallthrough"})
    # 去重（同一 label 只留一条）
    seen = set()
    uniq = []
    for e in ends:
        key = (e["chapterId"], e["label"])
        if key in seen:
            continue
        seen.add(key)
        uniq.append(e)
    return uniq


def analyze_script(project: VnProject) -> Dict[str, Any]:
    """一次性给出剧本工程体检结果。"""
    index = _label_index(project)
    reachable = reachable_labels(project)
    conditions = collect_conditions(project)
    ends = _flow_ends(project)
    for e in ends:
        e["reachable"] = e["label"] in reachable
    branch_points = []
    for cid, b in _all_blocks(project):
        if b.get("type") != "menu":
            continue
        choices = [c for c in (b.get("choices") or []) if isinstance(c, dict)]
        branch_points.append(
            {
                "chapterId": cid,
                "menuId": b.get("id") or "menu",
                "choices": len(choices),
                "conditional": sum(1 for c in choices if (c.get("condition") or "").strip()),
            }
        )
    dangling = [
        {"chapterId": cid, "target": target}
        for cid, target in _jump_targets(project)
        if target not in index
    ]
    return {
        "labels": {
            "total": len(index),
            "reachable": len(reachable),
            "unreachable": sorted(set(index) - reachable),
        },
        "endings": ends,
        "endingsReachable": sum(1 for e in ends if e["reachable"]),
        "branchPoints": branch_points,
        "conditions": conditions,
        "invalidConditions": [c for c in conditions if c["error"]],
        "danglingJumps": dangling,
        "variables": variable_usage(project),
        "duration": estimate_duration(project),
        "repetition": repetition_report(project),
        "counts": _block_counts(project),
    }


def _block_counts(project: VnProject) -> Dict[str, int]:
    c: Counter = Counter()
    for _cid, b in _all_blocks(project):
        c[str(b.get("type") or "?")] += 1
    return dict(c)
