"""读者/玩家行为建模：把试玩中的选择落库，并给出作者视角的行为分析。

设计取舍（为什么是这样，而不是别的样子）
======================================

**1. 默认关闭，且关闭时显式拒绝。**
``project_telemetry_settings.enabled`` 默认 False，**没有设置行也视为关闭**。
这是"记录别人怎么玩我的作品"的采集行为，作者必须显式同意；默认开启等于让所有存量
工程在升级瞬间开始采集。关闭时 record 端点返回 **403**（而不是静默丢弃）——
静默丢弃会让"前端一直在上报、表里却什么都没有"变成一个查不出来的谜；显式拒绝能让
前端立刻停手、也能在日志里留下痕迹。

**2. 表里没有任何自由文本列（隐私红线的实现方式）。**
``playtest_runs`` / ``playtest_choices`` 的每一个字符串列都只放**标识符**
（client_run_id / chapter_id / label / menu_id / ending_label），写库前一律过
``sanitize_identifier`` 的 ASCII 标识符白名单，不合格的落成空串。于是"台词、选项
文案、旁白"在物理上没有容器可放 —— 不是靠"记得别写进去"，而是靠**列宽 + 字符集 +
白名单**三重结构性约束。未知字段（有人试图塞 ``text`` / ``prose`` / ``user_agent``）
在 ``sanitize_*`` 里被丢弃并计数，绝不落库。IP / UA / 指纹 / user_id 一概不存。

**3. 幂等：唯一键 + 只补缺失的 seq。**
``(project_id, client_run_id)`` 唯一（一次试玩最多一行 run），``(run_id, seq)`` 唯一
（同一 run 内每个 seq 最多一行 choice）。重复上报时只插入库里没有的 seq
（``missing_choices``），run 的标量字段只做单向合并（补空 / 取较大值），所以重复上报
既不产生重复行，也不会把已有统计越写越脏。并发首次上报由数据库唯一约束兜底：
IntegrityError → 回滚 → 重新选中已有行继续合并。

**4. 分析逻辑是纯函数。**
``build_reader_analytics`` 的输入只有若干 dict / row-like 和 ``branch_analysis`` 的
输出，不碰 DB、不碰网络，因此在没有 PostgreSQL 的环境里也能完整回归
（tests/test_playtest_analytics.py）。API 层只负责取数、调用、返回。

**5. 响应里也不回正文。**
``build_reader_analytics`` 的输出只含 menu_id / choice_index / 计数 / 占比 / 条件表达式，
刻意**不带选项文案**：作者要还原"第 3 个选项"是哪一个，用 menu_id + index 回编辑器定位
即可。这样整条遥测链路（表 + 响应）都是可机检的"零正文"。
"""

from __future__ import annotations

import logging
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Mapping, Optional, Sequence, Set, Tuple

from fastapi import HTTPException
from sqlalchemy import func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

logger = logging.getLogger(__name__)

# --------------------------------------------------------------------- 参数

MIN_SAMPLE_RUNS = 10
"""低于这个试玩次数时，所有比例都只提示"不足以下结论"（调用方可覆盖）。"""

MAX_CHOICES_PER_RUN = 2000
"""单次上报的选择条数上限（与试玩器 2000 步上限对齐）。"""

MAX_ANALYTICS_RUNS = 5000
"""单次分析最多取多少次试玩；超出会在 notes 里如实说明被截断。"""

_MAX_CHAPTERS = 5000
_MAX_DROPPED_KEYS = 12
_MAX_KEY_LEN = 40

# 标识符白名单：ASCII 标识符，最长 64。
# 这是隐私红线的第一道闸 —— 含空格 / 中文 / 标点的值（也就是任何"文案"）在这里就没了。
_IDENTIFIER_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_.:-]{0,63}$")
# 客户端随机 id：>=8 位（更短的话没有足够熵做幂等键），只允许 URL 安全字符。
_CLIENT_RUN_RE = re.compile(r"^[A-Za-z0-9_-]{8,64}$")

_RUN_KEYS = frozenset(
    {
        "client_run_id",
        "started_at",
        "ended_at",
        "chapter_count",
        "choice_count",
        "ending_label",
    }
)
_CHOICE_KEYS = frozenset(
    {"seq", "chapter_id", "label", "menu_id", "choice_index", "condition_passed"}
)


# ------------------------------------------------------------- 白名单净化


def sanitize_identifier(value: Any) -> str:
    """标识符白名单：只接受 ASCII 标识符，否则返回空串。

    ``chapter_id`` / ``menu_id`` / ``label`` / ``ending_label`` 四个"字符串"列都要过
    这里。代价：作者若用非 ASCII 名字给 label 命名（例如中文 label 名），该字段会丢失
    —— 但同一行还有 seq / choice_index / menu_id / chapter_id 可以定位，统计不受影响；
    而换来的是"任何文案都不可能在物理上进库"这一条硬保证。
    """
    if not isinstance(value, str):
        return ""
    text = value.strip()
    if not text or len(text) > 64:
        return ""
    return text if _IDENTIFIER_RE.match(text) else ""


def sanitize_client_run_id(value: Any) -> str:
    """客户端试玩 id：随机、不可反查个人，是幂等键的一半。"""
    if not isinstance(value, str):
        return ""
    text = value.strip()
    return text if _CLIENT_RUN_RE.match(text) else ""


def _as_int(value: Any, default: int = 0) -> int:
    if isinstance(value, bool):
        return default
    if isinstance(value, int):
        return value
    if isinstance(value, float):
        return int(value)
    if isinstance(value, str):
        try:
            return int(value.strip())
        except ValueError:
            return default
    return default


def _as_bool(value: Any, default: bool) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, int) and value in (0, 1):
        return bool(value)
    if isinstance(value, str):
        low = value.strip().lower()
        if low in ("true", "1", "yes"):
            return True
        if low in ("false", "0", "no"):
            return False
    return default


def _clamp(value: int, low: int, high: int) -> int:
    return max(low, min(high, value))


def _as_datetime(value: Any) -> Optional[datetime]:
    """把上报的时间解析成 tz-aware UTC；解析不出来就返回 None（不猜、不落库里）。"""
    if isinstance(value, datetime):
        dt = value
    elif isinstance(value, bool):
        return None
    elif isinstance(value, (int, float)):
        try:
            dt = datetime.fromtimestamp(float(value), tz=timezone.utc)
        except (OverflowError, OSError, ValueError):
            return None
    elif isinstance(value, str):
        raw = value.strip()
        if not raw:
            return None
        iso = raw[:-1] + "+00:00" if raw.endswith("Z") else raw
        try:
            dt = datetime.fromisoformat(iso)
        except ValueError:
            return None
    else:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    # 时间戳同样要白名单：离谱的时间只会污染时长统计
    now = datetime.now(timezone.utc)
    if dt < datetime(2000, 1, 1, tzinfo=timezone.utc) or dt > now + timedelta(days=1):
        return None
    return dt


def dropped_field_names(keys: Iterable[Any]) -> List[str]:
    """去掉的字段名（只留名字，且截断 —— 名字本身也可能被用来夹带内容）。"""
    out: List[str] = []
    for key in keys:
        name = str(key)[:_MAX_KEY_LEN]
        if name not in out:
            out.append(name)
        if len(out) >= _MAX_DROPPED_KEYS:
            break
    return out


def sanitize_run_payload(payload: Any) -> Tuple[Dict[str, Any], List[str]]:
    """把上报的 run 对象压成白名单字段。

    返回 ``(净化后的字典, 被丢弃的字段名列表)``。未知字段一律丢弃并记名，
    目的是让"有人试图塞 text"这件事可观测，而不是悄悄消失。
    """
    if not isinstance(payload, Mapping):
        return {}, ["<run>"]
    dropped = dropped_field_names(k for k in payload if k not in _RUN_KEYS)
    clean = {
        "client_run_id": sanitize_client_run_id(payload.get("client_run_id")),
        "started_at": _as_datetime(payload.get("started_at")),
        "ended_at": _as_datetime(payload.get("ended_at")),
        "chapter_count": _clamp(_as_int(payload.get("chapter_count"), 0), 0, _MAX_CHAPTERS),
        "choice_count": _clamp(
            _as_int(payload.get("choice_count"), 0), 0, MAX_CHOICES_PER_RUN
        ),
        "ending_label": sanitize_identifier(payload.get("ending_label")),
    }
    if clean["ended_at"] and clean["started_at"] and clean["ended_at"] < clean["started_at"]:
        clean["ended_at"] = None  # 时间倒流：宁可当成"没结束"，也不要污染时长统计
    return clean, dropped


def sanitize_choice(payload: Any) -> Tuple[Optional[Dict[str, Any]], List[str]]:
    """净化单条选择。返回 ``(净化后的字典或 None, 被丢弃的字段名)``。

    ``seq`` 缺失或不合法时整条丢弃：没有 seq 就无法做"只补缺失 seq"的幂等合并，
    硬塞进去只会产生重复行。
    """
    if not isinstance(payload, Mapping):
        return None, ["<choice>"]
    dropped = dropped_field_names(k for k in payload if k not in _CHOICE_KEYS)
    seq = _as_int(payload.get("seq"), -1)
    if seq < 0 or seq > MAX_CHOICES_PER_RUN:
        return None, dropped
    return (
        {
            "seq": seq,
            "chapter_id": sanitize_identifier(payload.get("chapter_id")),
            "label": sanitize_identifier(payload.get("label")),
            "menu_id": sanitize_identifier(payload.get("menu_id")),
            "choice_index": _clamp(_as_int(payload.get("choice_index"), -1), -1, 9999),
            "condition_passed": _as_bool(payload.get("condition_passed"), True),
        },
        dropped,
    )


def sanitize_choices(
    items: Any, *, limit: int = MAX_CHOICES_PER_RUN
) -> Tuple[List[Dict[str, Any]], int, List[str]]:
    """批量净化选择序列 → ``(行, 被拒绝条数, 被丢弃字段名)``。

    同一次上报内 ``seq`` 重复时保留最后一条（客户端重试时常见），按 seq 排序后返回。
    """
    if not isinstance(items, (list, tuple)):
        return [], 0, []
    rows: Dict[int, Dict[str, Any]] = {}
    dropped: List[str] = []
    rejected = max(0, len(items) - limit)
    for item in list(items)[:limit]:
        row, keys = sanitize_choice(item)
        dropped.extend(k for k in keys if k not in dropped)
        if row is None:
            rejected += 1
            continue
        rows[row["seq"]] = row
    return [rows[k] for k in sorted(rows)], rejected, dropped_field_names(dropped)


def missing_choices(
    existing_seqs: Iterable[Any], incoming: Sequence[Mapping[str, Any]]
) -> List[Dict[str, Any]]:
    """只保留库里还没有的 seq —— 幂等的核心纯函数。

    重复上报同一份 payload 时，第二次返回空列表 ⇒ 不写任何行。
    """
    seen: Set[int] = set()
    for raw in existing_seqs:
        seen.add(_as_int(raw, -1))
    out: List[Dict[str, Any]] = []
    for row in incoming:
        seq = _as_int(row.get("seq"), -1)
        if seq < 0 or seq in seen:
            continue
        seen.add(seq)
        out.append(dict(row))
    return out


def is_telemetry_enabled(setting: Any) -> bool:
    """读取开关的纯函数口径：**没有设置行 = 关闭**。"""
    if setting is None:
        return False
    if isinstance(setting, Mapping):
        return bool(setting.get("enabled", False))
    return bool(getattr(setting, "enabled", False))


# ----------------------------------------------------------- 行为分析（纯）


def _leaf(row: Any, key: str, default: Any = None) -> Any:
    """从 dict 或 ORM 行里取一个叶子字段（两者都支持，纯函数可直接吃 ORM 行）。"""
    if isinstance(row, Mapping):
        return row.get(key, default)
    return getattr(row, key, default)


def _stats(values: Sequence[float]) -> Dict[str, float]:
    """计数类统计：次数 / 平均 / 中位 / 极值。空输入返回全 0（不抛）。"""
    if not values:
        return {"count": 0.0, "sum": 0.0, "avg": 0.0, "median": 0.0, "min": 0.0, "max": 0.0}
    ordered = sorted(float(v) for v in values)
    n = len(ordered)
    mid = n // 2
    median = (
        ordered[mid] if n % 2 else (ordered[mid - 1] + ordered[mid]) / 2
    )
    total = sum(ordered)
    return {
        "count": float(n),
        "sum": round(total, 3),
        "avg": round(total / n, 3),
        "median": round(median, 3),
        "min": round(ordered[0], 3),
        "max": round(ordered[-1], 3),
    }


def _run_view(row: Any) -> Dict[str, Any]:
    return {
        "id": str(_leaf(row, "id", "") or ""),
        "client_run_id": str(_leaf(row, "client_run_id", "") or ""),
        "chapter_count": max(0, _as_int(_leaf(row, "chapter_count", 0), 0)),
        "choice_count": max(0, _as_int(_leaf(row, "choice_count", 0), 0)),
        "ending_label": sanitize_identifier(_leaf(row, "ending_label", "")),
        "started_at": _as_datetime(_leaf(row, "started_at")),
        "ended_at": _as_datetime(_leaf(row, "ended_at")),
    }


def _choice_view(row: Any) -> Dict[str, Any]:
    return {
        "run_id": str(_leaf(row, "run_id", "") or ""),
        "seq": _as_int(_leaf(row, "seq", -1), -1),
        "chapter_id": sanitize_identifier(_leaf(row, "chapter_id", "")),
        "label": sanitize_identifier(_leaf(row, "label", "")),
        "menu_id": sanitize_identifier(_leaf(row, "menu_id", "")),
        "choice_index": _as_int(_leaf(row, "choice_index", -1), -1),
        "condition_passed": _as_bool(_leaf(row, "condition_passed", True), True),
    }


def _script_view(branch: Any) -> Dict[str, Any]:
    """把 branch_analysis 的输出拆成分析需要的三块（容错：缺字段不炸）。"""
    script: Mapping[str, Any] = branch if isinstance(branch, Mapping) else {}
    endings = script.get("endings")
    if not isinstance(endings, Mapping):
        endings = {}
    menus = [m for m in (script.get("menus") or []) if isinstance(m, Mapping)]
    declared = [d for d in (endings.get("declared") or []) if isinstance(d, Mapping)]
    terminals = [str(t) for t in (endings.get("undeclaredTerminals") or [])]
    return {"menus": menus, "declared": declared, "terminals": terminals}


def _chapter_order(
    chapter_order: Sequence[str],
    menus: Sequence[Mapping[str, Any]],
    choice_rows: Sequence[Mapping[str, Any]],
) -> List[str]:
    """章节顺序：优先用工程里的真实顺序，缺失时退回菜单/选择记录里的出现顺序。"""
    order: List[str] = []
    seen: Set[str] = set()
    for raw in chapter_order:
        cid = str(raw or "")
        if cid and cid not in seen:
            seen.add(cid)
            order.append(cid)
    if order:
        return order
    for menu in menus:
        cid = str(menu.get("chapterId") or "")
        if cid and cid not in seen:
            seen.add(cid)
            order.append(cid)
    if order:
        return order
    for row in sorted(choice_rows, key=lambda r: r["seq"]):
        cid = str(row["chapter_id"])
        if cid and cid not in seen:
            seen.add(cid)
            order.append(cid)
    return order


def _menu_section(
    menus: Sequence[Mapping[str, Any]],
    choice_rows: Sequence[Mapping[str, Any]],
    by_menu: Dict[str, List[Dict[str, Any]]],
    unattributed: int,
) -> Tuple[Dict[str, Any], Set[Tuple[str, int]], Dict[str, Set[int]], Set[str]]:
    """按 menu_id 汇总每个选项被选次数与占比，并标出从未被选的选项。"""
    all_menu_ids = Counter(str(m.get("menuId") or "menu") for m in menus)
    duplicate_menu_ids = sorted(mid for mid, n in all_menu_ids.items() if n > 1)
    reports: List[Dict[str, Any]] = []
    available_pairs: Set[Tuple[str, int]] = set()
    option_indices: Dict[str, Set[int]] = {}
    for menu in menus:
        mid = str(menu.get("menuId") or "menu")
        options_in = [o for o in (menu.get("choices") or []) if isinstance(o, Mapping)]
        rows = by_menu.get(mid, [])
        counts = Counter(r["choice_index"] for r in rows)
        blocked = Counter(r["choice_index"] for r in rows if not r["condition_passed"])
        total = len(rows)
        indices: Set[int] = set()
        options: List[Dict[str, Any]] = []
        for pos, opt in enumerate(options_in):
            idx = _as_int(opt.get("index", pos), pos)
            indices.add(idx)
            available = bool(opt.get("available", True))
            if available:
                available_pairs.add((mid, idx))
            picked = counts.get(idx, 0)
            options.append(
                {
                    "index": idx,
                    "selected": picked,
                    "share": round(picked / total, 4) if total else 0.0,
                    "neverSelected": picked == 0,
                    "available": available,
                    "condition": str(opt.get("condition") or ""),
                    "conditionBlockedSelections": blocked.get(idx, 0),
                }
            )
        option_indices.setdefault(mid, set()).update(indices)
        reports.append(
            {
                "menuId": mid,
                "chapterId": str(menu.get("chapterId") or ""),
                "label": str(menu.get("label") or ""),
                "selections": total,
                "optionCount": len(options),
                "options": options,
                "neverSelected": [o["index"] for o in options if o["neverSelected"]],
            }
        )
    known = set(option_indices)
    unknown_menus = [
        {"menuId": mid, "selections": len(rows)}
        for mid, rows in sorted(by_menu.items())
        if mid not in known
    ]
    section = {
        "totalSelections": len(choice_rows),
        "menus": reports,
        "menuCount": len(reports),
        "unknownMenus": unknown_menus,
        "unattributedSelections": unattributed,
        "duplicateMenuIds": duplicate_menu_ids,
    }
    return section, available_pairs, option_indices, known


def _funnel_section(
    order: Sequence[str],
    run_rows: Sequence[Mapping[str, Any]],
    choice_rows: Sequence[Mapping[str, Any]],
) -> Dict[str, Any]:
    """按章到达 / 流失漏斗。

    "到达第 i 章"的口径：客户端上报的 ``chapter_count`` 与选择记录里出现的最大章序号
    取较大者，再折算成前缀（到达过第 5 章就认为到达过第 1~5 章）。这样得到的漏斗
    **天然单调不增**，不会出现"后面章比前面章人还多"的假象；代价是客户端少报章数会
    让漏斗整体偏低（notes 里说明）。
    """
    index_of = {cid: i for i, cid in enumerate(order)}
    per_run: Dict[str, List[Dict[str, Any]]] = {}
    for row in choice_rows:
        per_run.setdefault(str(row["run_id"]), []).append(row)

    n_runs = len(run_rows)
    reached = [0] * len(order)
    choosing = [0] * len(order)
    for run in run_rows:
        rows = per_run.get(str(run["id"]), [])
        idxs: List[int] = []
        if order and run["chapter_count"] > 0:
            idxs.append(min(int(run["chapter_count"]), len(order)) - 1)
        hit_chapters: Set[str] = set()
        for row in rows:
            cid = str(row["chapter_id"])
            pos = index_of.get(cid)
            if pos is None:
                continue
            idxs.append(pos)
            hit_chapters.add(cid)
        max_idx = max(idxs) if idxs else -1
        for i in range(max_idx + 1):
            reached[i] += 1
        for cid in hit_chapters:
            choosing[index_of[cid]] += 1

    chapters: List[Dict[str, Any]] = []
    for i, cid in enumerate(order):
        prev = reached[i - 1] if i > 0 else n_runs
        drop = prev - reached[i]
        chapters.append(
            {
                "index": i,
                "chapterId": cid,
                "reached": reached[i],
                "choosingRuns": choosing[i],
                "dropFromPrevious": drop,
                "dropRate": round(drop / prev, 4) if prev else 0.0,
                "retention": round(reached[i] / n_runs, 4) if n_runs else 0.0,
            }
        )
    drop_candidates = [c for c in chapters if c["dropFromPrevious"] > 0]
    biggest = (
        max(drop_candidates, key=lambda c: (c["dropFromPrevious"], -c["index"]))
        if drop_candidates
        else None
    )
    deepest = ""
    for chapter in chapters:
        if chapter["reached"] > 0:
            deepest = chapter["chapterId"]
    seen_chapters = Counter(
        str(r["chapter_id"]) for r in choice_rows if r["chapter_id"]
    )
    unknown_chapters = [
        {"chapterId": cid, "selections": n}
        for cid, n in sorted(seen_chapters.items())
        if cid not in index_of
    ]
    return {
        "startedRuns": n_runs,
        "chapters": chapters,
        "biggestDrop": biggest,
        "deepestChapterId": deepest,
        "unknownChapters": unknown_chapters,
    }


def _endings_section(
    run_rows: Sequence[Mapping[str, Any]],
    declared: Sequence[Mapping[str, Any]],
    terminals: Sequence[str],
) -> Dict[str, Any]:
    """玩家实际走到的结局分布，并与声明结局对账（哪些结局从没人走到）。"""
    n_runs = len(run_rows)
    counts = Counter(str(r["ending_label"]) for r in run_rows if r["ending_label"])
    unfinished = sum(1 for r in run_rows if not r["ending_label"])

    by_label: Dict[str, Mapping[str, Any]] = {}
    declared_without_label: List[Dict[str, str]] = []
    for item in declared:
        label = sanitize_identifier(item.get("label"))
        if not label:
            declared_without_label.append(
                {
                    "name": str(item.get("name") or ""),
                    "route": str(item.get("route") or ""),
                }
            )
            continue
        by_label.setdefault(label, item)

    terminal_set = {str(t) for t in terminals}
    reached: List[Dict[str, Any]] = []
    for label, count in sorted(counts.items(), key=lambda kv: (-kv[1], kv[0])):
        item = by_label.get(label)
        reached.append(
            {
                "label": label,
                "name": str((item or {}).get("name") or label),
                "runs": count,
                "share": round(count / n_runs, 4) if n_runs else 0.0,
                "declared": item is not None,
                "declaredReachable": bool((item or {}).get("reachable", False)),
                "declaredExists": bool((item or {}).get("exists", False)),
                "isStaticTerminal": label in terminal_set,
            }
        )
    never_reached = [
        {
            "label": label,
            "name": str(item.get("name") or label),
            "route": str(item.get("route") or ""),
            "reachableInScript": bool(item.get("reachable", False)),
        }
        for label, item in sorted(by_label.items())
        if label not in counts
    ]
    undeclared = [row for row in reached if not row["declared"]]
    return {
        "reached": reached,
        "declaredTotal": len(by_label),
        "declaredReached": sum(1 for row in reached if row["declared"]),
        "neverReached": never_reached,
        "undeclared": undeclared,
        "unknownEndingLabels": [row for row in undeclared if not row["isStaticTerminal"]],
        "declaredWithoutLabel": declared_without_label,
        "unfinishedRuns": unfinished,
    }


def _runs_section(
    run_rows: Sequence[Mapping[str, Any]], choice_rows: Sequence[Any]
) -> Dict[str, Any]:
    """运行次数 / 平均与中位选择数 / 平均章数 / 时长。"""
    n_runs = len(run_rows)
    observed = Counter(str(r["run_id"]) for r in choice_rows)
    reported_choices = [float(r["choice_count"]) for r in run_rows]
    observed_choices = [float(observed.get(str(r["id"]), 0)) for r in run_rows]
    chapters_played = [float(r["chapter_count"]) for r in run_rows]
    durations = [
        (r["ended_at"] - r["started_at"]).total_seconds()
        for r in run_rows
        if r["ended_at"] and r["started_at"] and r["ended_at"] >= r["started_at"]
    ]
    return {
        "total": n_runs,
        "finished": sum(1 for r in run_rows if r["ended_at"] is not None),
        "withEnding": sum(1 for r in run_rows if r["ending_label"]),
        # reported = 客户端自报，observed = 库里真实落下的行数；两者不一致说明有丢报
        "choicesReported": _stats(reported_choices),
        "choicesObserved": _stats(observed_choices),
        "chaptersPlayed": _stats(chapters_played),
        "durationSeconds": _stats(durations) if durations else None,
    }


def _notes(
    *,
    n_runs: int,
    n_choices: int,
    min_sample: int,
    menus: Sequence[Mapping[str, Any]],
    choices_section: Mapping[str, Any],
    funnel: Mapping[str, Any],
    endings: Mapping[str, Any],
    coverage: Mapping[str, Any],
    runs_section: Mapping[str, Any],
) -> List[str]:
    """口径说明 + 样本量提示（中文，给作者直接看）。"""
    notes: List[str] = [
        "口径：只统计已落库的选择记录，不含任何正文；同一 (project_id, client_run_id) "
        "重复上报只补缺失的 seq，不会重复计数。",
    ]
    if n_runs == 0:
        notes.append("还没有任何试玩记录：打开试玩器并完成一次上报后，这里才会有数据。")
    if not menus:
        notes.append(
            "剧本结构分析不可用（没有解析到任何菜单）：choices / coverage 只能列出玩家"
            "实际选了哪个 menu_id 的第几项，无法判断「哪些选项从没被选」——因为不知道"
            "剧本里本来有哪些选项。"
        )
    if 0 < n_runs < min_sample:
        notes.append(
            f"样本量不足：只有 {n_runs} 次试玩（建议至少 {min_sample} 次），"
            "下面的比例只代表少数玩家，不足以下结论。"
        )
    elif n_runs >= min_sample:
        notes.append(
            f"样本量：{n_runs} 次试玩、{n_choices} 次选择，达到统计口径下限（{min_sample}）。"
        )
    chapters = list(funnel.get("chapters") or [])
    if chapters:
        notes.append(
            "漏斗的「到达」由客户端上报的 chapter_count 与选择记录里出现的最大章序号共同"
            "推断（取较大者的前缀）：客户端少报章数会让漏斗整体偏低。"
        )
        if all(int(c["choosingRuns"]) == 0 for c in chapters):
            notes.append(
                "所有章节都没有选择记录：这批试玩可能没经过任何菜单（纯阅读），"
                "此时覆盖率恒为 0，不代表分支没人走。"
            )
    biggest = funnel.get("biggestDrop")
    if biggest:
        notes.append(
            f"流失最多的一章：{biggest['chapterId']}（流失 {biggest['dropFromPrevious']} 次，"
            f"流失率 {biggest['dropRate']:.0%}）。"
        )
    if n_runs > 0 and endings.get("neverReached"):
        names = "、".join(f"「{row['name']}」" for row in list(endings["neverReached"])[:8])
        notes.append(
            f"有 {len(endings['neverReached'])} 个已登记的结局没有任何玩家走到：{names}。"
            "要么入口太难找，要么条件写死了（可对照分支体检的「条件恒不成立」）。"
        )
    if endings.get("unknownEndingLabels"):
        notes.append(
            f"有 {len(endings['unknownEndingLabels'])} 个 ending_label 既没登记为结局、"
            "也不在静态分析的终点集合里：可能漏登记，也可能是客户端上报了自造的名字。"
        )
    if endings.get("declaredWithoutLabel"):
        notes.append(
            f"有 {len(endings['declaredWithoutLabel'])} 个已登记结局没有 label，"
            "无法与玩家实际走到的结局对账。"
        )
    if choices_section.get("unknownMenus"):
        notes.append(
            f"有 {len(choices_section['unknownMenus'])} 个 menu_id 在剧本里找不到"
            "（剧本改过？）：这些选择只参与总数与章级漏斗，无法判断选项含义。"
        )
    if choices_section.get("unattributedSelections"):
        notes.append(
            f"有 {choices_section['unattributedSelections']} 条选择没有 menu_id，"
            "只参与总数与章级漏斗，无法归到具体菜单。"
        )
    if choices_section.get("duplicateMenuIds"):
        names = "、".join(str(m) for m in list(choices_section["duplicateMenuIds"])[:8])
        notes.append(
            f"剧本里有重复的 menu_id（{names}）：同名菜单的选择会被合并统计，"
            "建议给菜单分配唯一 id。"
        )
    if funnel.get("unknownChapters"):
        notes.append(
            f"有 {len(funnel['unknownChapters'])} 个 chapter_id 不在当前章节顺序里"
            "（章节被删或改名？）：它们不计入漏斗。"
        )
    if coverage.get("selectedUnavailableOptions"):
        names = "、".join(
            f"{row['menuId']}#{row['index']}"
            for row in list(coverage["selectedUnavailableOptions"])[:8]
        )
        notes.append(
            "静态分析判定下面这些选项「不可选」，但玩家实际选了它们："
            f"{names}。优先检查条件求值（实际运行时的状态可能比分析器认为的更宽松）。"
        )
    reported = runs_section.get("choicesReported") or {}
    observed = runs_section.get("choicesObserved") or {}
    if int(reported.get("sum", 0)) != int(observed.get("sum", 0)):
        notes.append(
            f"客户端自报选择数合计 {int(reported.get('sum', 0))}，库里实际落下 "
            f"{int(observed.get('sum', 0))} 条：差额来自重复 seq 被幂等合并或上报中断。"
        )
    return notes


def build_reader_analytics(
    runs: Sequence[Any],
    choices: Sequence[Any],
    branch: Optional[Mapping[str, Any]] = None,
    chapter_order: Sequence[str] = (),
    *,
    min_sample: int = MIN_SAMPLE_RUNS,
) -> Dict[str, Any]:
    """把「玩家实际做了什么」对齐到「剧本写了什么」，产出作者能用的行为分析。

    ``branch`` 是 ``app.core.branch_analysis.analyze_branches(project)`` 的输出（可为
    None，此时只报玩家实际行为、不做对齐）。输入全是 row-like 或 dict，纯函数、不碰
    DB，因此可在无 PostgreSQL 的环境里完整回归。

    返回分五块：``choices``（按 menu_id 的选项占比与「从未被选的选项」）、``funnel``
    （按章到达与流失）、``endings``（结局分布 + 声明结局对账）、``runs``（次数 / 平均与
    中位选择数 / 平均章数）、``coverage``（读者视角的分支覆盖率），外加 ``sample`` 与
    中文 ``notes``。
    """
    run_rows = [_run_view(r) for r in runs]
    choice_rows = [_choice_view(c) for c in choices]
    script = _script_view(branch)
    menus = script["menus"]
    order = _chapter_order(chapter_order, menus, choice_rows)

    by_menu: Dict[str, List[Dict[str, Any]]] = {}
    unattributed = 0
    for row in choice_rows:
        if not row["menu_id"]:
            unattributed += 1
            continue
        by_menu.setdefault(str(row["menu_id"]), []).append(row)
    choices_section, available_pairs, option_indices, known_menus = _menu_section(
        menus, choice_rows, by_menu, unattributed
    )

    observed_any = {
        (str(r["menu_id"]), int(r["choice_index"])) for r in choice_rows if r["menu_id"]
    }
    mapped = {
        pair for pair in observed_any if pair[1] in option_indices.get(pair[0], set())
    }
    observed_available = mapped & available_pairs
    selected_unavailable = [
        {
            "menuId": mid,
            "index": idx,
            "selections": sum(
                1 for r in by_menu.get(mid, []) if int(r["choice_index"]) == idx
            ),
        }
        for mid, idx in sorted(mapped - available_pairs)
    ]
    touched = {mid for mid, _idx in observed_available}
    choices_section["observedMenuCount"] = len(touched)
    choices_section["selectedUnavailableOptions"] = selected_unavailable

    coverage = {
        "availableOptions": len(available_pairs),
        "observedOptions": len(observed_available),
        "ratio": (
            round(len(observed_available) / len(available_pairs), 4)
            if available_pairs
            else 0.0
        ),
        "menusTotal": len(menus),
        "menusTouched": len(touched),
        "menusNeverTouched": sorted(mid for mid in known_menus if mid not in touched),
        "unmappedSelections": len(observed_any - mapped) + unattributed,
        "selectedUnavailableOptions": selected_unavailable,
    }

    funnel = _funnel_section(order, run_rows, choice_rows)
    endings = _endings_section(run_rows, script["declared"], script["terminals"])
    runs_section = _runs_section(run_rows, choice_rows)
    notes = _notes(
        n_runs=len(run_rows),
        n_choices=len(choice_rows),
        min_sample=min_sample,
        menus=menus,
        choices_section=choices_section,
        funnel=funnel,
        endings=endings,
        coverage=coverage,
        runs_section=runs_section,
    )
    return {
        "sample": {
            "runs": len(run_rows),
            "choices": len(choice_rows),
            "minSample": min_sample,
            "sufficient": len(run_rows) >= min_sample,
            "truncated": False,
        },
        "choices": choices_section,
        "funnel": funnel,
        "endings": endings,
        "runs": runs_section,
        "coverage": coverage,
        "notes": notes,
    }


# --------------------------------------------------------------- 持久化


async def get_telemetry_enabled(db: AsyncSession, project_id: str) -> bool:
    """读开关：没有设置行 = 关闭（默认关闭是刻意的，见模块 docstring）。"""
    from app.models import ProjectTelemetrySetting

    row = await db.get(ProjectTelemetrySetting, project_id)
    return is_telemetry_enabled(row)


async def set_telemetry_enabled(db: AsyncSession, project_id: str, enabled: bool) -> bool:
    """写开关（幂等）：同一个值重复写不会失败，也不会写出多行。"""
    from app.models import ProjectTelemetrySetting

    now = datetime.now(timezone.utc)
    row = await db.get(ProjectTelemetrySetting, project_id)
    if row is None:
        db.add(
            ProjectTelemetrySetting(
                project_id=project_id, enabled=bool(enabled), updated_at=now
            )
        )
        try:
            await db.commit()
            return bool(enabled)
        except IntegrityError:
            # 并发首写：另一个请求先插了 —— 回滚后改为更新，而不是把 500 抛给作者
            await db.rollback()
            row = await db.get(ProjectTelemetrySetting, project_id)
            if row is None:
                raise
    row.enabled = bool(enabled)
    row.updated_at = now
    await db.commit()
    return bool(enabled)


async def record_playtest(
    db: AsyncSession, *, project_id: str, payload: Mapping[str, Any]
) -> Dict[str, Any]:
    """落库一次试玩上报（批量：run 信息 + 选择序列）。

    幂等策略：``(project_id, client_run_id)`` 唯一键定位 run，``(run_id, seq)`` 唯一键
    定位选择行；重复上报只**补缺失的 seq**，标量字段只做单向合并（补空 / 取较大值），
    因此重复上报不会产生重复行，也不会把已有统计越写越脏。

    隐私策略：所有字段过白名单；未知字段丢弃并计数；文案类字符串在
    ``sanitize_identifier`` 处就没了。未开启遥测时抛 403 **且不落任何行**。
    """
    from app.models import PlaytestChoice, PlaytestRun

    if not isinstance(payload, Mapping):
        raise HTTPException(status_code=400, detail="上报体必须是 JSON 对象")

    if not await get_telemetry_enabled(db, project_id):
        # 显式拒绝而不是静默丢弃：静默丢弃会让"前端一直在上报、表里什么都没有"
        # 变成查不出来的谜；显式 403 能让前端立刻停手并留下痕迹。
        raise HTTPException(
            status_code=403,
            detail={
                "code": "telemetry_disabled",
                "message": "该工程未开启读者行为采集（默认关闭，需作者显式开启）",
            },
        )

    clean_run, dropped_run = sanitize_run_payload(payload.get("run"))
    client_run_id = clean_run["client_run_id"]
    if not client_run_id:
        raise HTTPException(
            status_code=400,
            detail={
                "code": "invalid_client_run_id",
                "message": "client_run_id 缺失或格式不合法（8~64 位 URL 安全字符）",
            },
        )

    clean_choices, rejected, dropped_choices = sanitize_choices(payload.get("choices"))

    now = datetime.now(timezone.utc)
    run = await db.scalar(
        select(PlaytestRun).where(
            PlaytestRun.project_id == project_id,
            PlaytestRun.client_run_id == client_run_id,
        )
    )
    created = False
    if run is None:
        run = PlaytestRun(
            project_id=project_id,
            client_run_id=client_run_id,
            started_at=clean_run["started_at"] or now,
            ended_at=clean_run["ended_at"],
            chapter_count=clean_run["chapter_count"],
            choice_count=0,  # 落库后再按真实行数回填，保证与库内一致
            ending_label=clean_run["ending_label"] or None,
            created_at=now,
        )
        db.add(run)
        try:
            await db.flush()
            created = True
        except IntegrityError:
            await db.rollback()
            run = await db.scalar(
                select(PlaytestRun).where(
                    PlaytestRun.project_id == project_id,
                    PlaytestRun.client_run_id == client_run_id,
                )
            )
            if run is None:
                raise HTTPException(status_code=409, detail="试玩记录写入冲突，请重试")

    existing_seqs: List[Any] = []
    if not created:
        res = await db.execute(
            select(PlaytestChoice.seq).where(PlaytestChoice.run_id == run.id)
        )
        existing_seqs = list(res.scalars().all())

    to_add = missing_choices(existing_seqs, clean_choices)
    for row in to_add:
        db.add(
            PlaytestChoice(
                run_id=run.id,
                seq=row["seq"],
                chapter_id=row["chapter_id"],
                label=row["label"],
                menu_id=row["menu_id"],
                choice_index=row["choice_index"],
                condition_passed=row["condition_passed"],
                created_at=now,
            )
        )
    await db.flush()

    stored = await db.scalar(
        select(func.count())
        .select_from(PlaytestChoice)
        .where(PlaytestChoice.run_id == run.id)
    )
    run.choice_count = int(stored or 0)
    # 单向合并：只补空 / 取较大值，重复上报不会把已有信息写坏
    run.chapter_count = max(int(run.chapter_count or 0), int(clean_run["chapter_count"]))
    if clean_run["ended_at"] and run.ended_at is None:
        run.ended_at = clean_run["ended_at"]
    if clean_run["ending_label"] and not run.ending_label:
        run.ending_label = clean_run["ending_label"]
    await db.commit()

    dropped = dropped_field_names([*dropped_run, *dropped_choices])
    if dropped:
        logger.debug("playtest: dropped non-whitelisted fields %s", dropped)
    return {
        "ok": True,
        "runId": run.id,
        "created": created,
        "accepted": len(to_add),
        "duplicates": len(clean_choices) - len(to_add),
        "rejected": rejected,
        "droppedFields": dropped,
    }


async def load_reader_analytics(
    db: AsyncSession,
    project_id: str,
    *,
    branch: Optional[Mapping[str, Any]] = None,
    chapter_order: Sequence[str] = (),
    min_sample: int = MIN_SAMPLE_RUNS,
    max_runs: int = MAX_ANALYTICS_RUNS,
) -> Dict[str, Any]:
    """取数 → 调用纯函数。API 层只负责鉴权与把结果返回。"""
    from app.models import PlaytestChoice, PlaytestRun

    total_runs = int(
        await db.scalar(
            select(func.count())
            .select_from(PlaytestRun)
            .where(PlaytestRun.project_id == project_id)
        )
        or 0
    )
    stmt = (
        select(PlaytestRun)
        .where(PlaytestRun.project_id == project_id)
        .order_by(PlaytestRun.started_at.desc(), PlaytestRun.id.desc())
        .limit(max_runs)
    )
    runs = list((await db.execute(stmt)).scalars().all())
    run_ids = [row.id for row in runs]
    choices: List[Any] = []
    if run_ids:
        cstmt = (
            select(PlaytestChoice)
            .where(PlaytestChoice.run_id.in_(run_ids))
            .order_by(PlaytestChoice.run_id.asc(), PlaytestChoice.seq.asc())
        )
        choices = list((await db.execute(cstmt)).scalars().all())

    result = build_reader_analytics(
        runs, choices, branch, chapter_order, min_sample=min_sample
    )
    if total_runs > len(runs):
        result["sample"]["truncated"] = True
        result["notes"].insert(
            0,
            f"数据量超过单次分析上限：只取最近 {len(runs)} 次试玩（共 {total_runs} 次），"
            "下面的比例是这批样本的口径。",
        )
    return result
