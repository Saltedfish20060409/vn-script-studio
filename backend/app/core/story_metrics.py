"""故事层指标：伏笔回收率 与 情感弧线一致性。

为什么单独一层
--------------
前面几个模块量的是"结构"（分支图、环、覆盖）与"风格"（声线漂移），
但另有两个**轻小说/视觉小说作者真正会问**的指标此前完全没有：

1. **伏笔回收率**：我埋了那么多钩子，到底回收了几成？还有哪些挂了很久没收？
   账本（`core/pipeline/ledger.py`）其实已经在记 open / paid 的伏笔，
   但从没有人把它算成一个数——于是"埋了 20 个钩子只回收了 6 个"这种事，
   作者只能靠翻账本一条条数。
2. **情感弧线一致性**：节拍表在规划阶段就声明了每个角色这一场的
   `emotionStart` / `emotionEnd`（`pipeline/orchestrator.stage_plan`），
   写完之后却没人核对"实际写出来的情绪走向"与声明是否一致。
   弧线断裂（说好从平静到愤怒，实际从头平静到尾）是读者最能察觉的一类问题。

两个指标都是**纯本地计算**（不调模型），因此可进单测、可在保存路径上随手跑。

诚实边界
--------
- 情绪是从台词里**关键词推断**的（复用 `pipeline/ledger._infer_speaker_state` 的口径），
  不是语义判断：反讽、压抑、言不由衷都可能被读错。因此它只报"与声明明显不符"，
  并且**永远带着证据原句**，让作者自己判断。
- 伏笔的 open/paid 状态由账本维护；本模块只做统计，不改账本。
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Dict, List, Optional, Sequence, Tuple

from app.core.blocks import iter_dialogue
from app.core.pipeline.ledger import _infer_speaker_state, foreshadow_report
from app.domain.types import VnProject

#: 推断出的情绪 → 粗略的"激活度"刻度，用来判断弧线是上升还是下降。
#: 这不是心理学量表，只是把 5 个离散标签排出一个可比较的顺序：
#: 低落 < 平静 < 疑惑 < 担忧 < 愉悦 < 激动（越靠后越"外放/有推动力"）。
EMOTION_ORDER: Dict[str, int] = {
    "低落": 0,
    "平静": 1,
    "疑惑": 2,
    "担忧": 3,
    "愉悦": 4,
    "激动": 5,
}

#: 判定"弧线断裂"的最小刻度差：差 1 格不算，噪声而已。
MIN_ARC_DELTA = 2

#: 某一章里该角色至少说这么多句，才评估**该章**的情绪走向。
#: 一句话推不出走向：拿单句去判"这一章情绪写反了"只会制造假警报。
MIN_CHAPTER_LINES = 2


@dataclass
class EmotionPoint:
    character: str
    start: str
    end: str
    delta: int

    def as_dict(self) -> Dict[str, Any]:
        return {
            "character": self.character,
            "start": self.start,
            "end": self.end,
            "delta": self.delta,
        }


# ------------------------------------------------------------------ 伏笔回收


def foreshadow_resolution(project: VnProject) -> Dict[str, Any]:
    """伏笔回收率：埋了多少、回收了多少、最老的未回收钩子挂了多久。

    "挂了多久"直接用账本的 ``ageChapters``（它已经算好了：埋点章 → 已回收看回收章、
    未回收看全书最后一章），不在这里另算一遍——同一件事两处各算一次，
    迟早会出现"界面说 12 章、导出说 15 章"。
    """
    rows = foreshadow_report(project) or []
    total = len(rows)
    open_rows = [r for r in rows if str(r.get("status") or "open") == "open"]
    paid_rows = [r for r in rows if str(r.get("status")) == "paid"]

    open_details: List[Dict[str, Any]] = []
    for r in open_rows:
        open_details.append(
            {
                "hook": str(r.get("hook") or r.get("id") or "")[:120],
                "plantedChapter": str(r.get("plantedChapter") or ""),
                "plantedChapterTitle": str(r.get("plantedChapterTitle") or ""),
                "chaptersOpen": int(r.get("ageChapters") or 0),
            }
        )
    open_details.sort(key=lambda r: (-int(r["chaptersOpen"]), str(r["plantedChapter"])))

    return {
        "total": total,
        "paid": len(paid_rows),
        "open": len(open_rows),
        # 分母是 0 时返回 None 而不是 0.0：没有伏笔不等于"回收率 0%"
        "resolutionRate": (round(len(paid_rows) / total, 3) if total else None),
        "openHooks": open_details,
        "oldestOpenChapters": (open_details[0]["chaptersOpen"] if open_details else 0),
        "chapters": len(project.chapters or []),
        "note": (
            "伏笔状态由写作账本维护（保存章节时自动更新）；这里只做统计。"
            + ("作品还没有记录任何伏笔。" if total == 0 else "")
        ),
    }


# ------------------------------------------------------------------ 情感弧线


def _emotion_track(name: str, texts: Sequence[str]) -> Optional[Tuple[str, str, List[str]]]:
    """一串台词 → (开头情绪, 结尾情绪, 证据句)。样本太少返回 None。

    注意这里**必须**把台词重新拼成 `角色名：台词` 的形式再交给
    `_infer_speaker_state`：那个函数是按"某人的台词行"来定位的，
    传空名字进去它会一行都匹配不到，于是**永远返回「平静」**——
    一个恒返回默认值的量具比没有量具更糟，它会让人以为"全篇情绪平稳"。
    """
    lines = [t for t in (str(x or "").strip() for x in texts) if t]
    if len(lines) < 2:
        return None
    prefix = f"{name or '角色'}："
    head = "\n".join(prefix + t for t in lines[: max(1, len(lines) // 3)])
    tail = "\n".join(prefix + t for t in lines[-max(1, len(lines) // 3) :])
    start, _ = _infer_speaker_state(head, name or "角色")
    end, _ = _infer_speaker_state(tail, name or "角色")
    return start, end, [lines[0][:80], lines[-1][:80]]


def emotion_arcs(project: VnProject) -> Dict[str, Any]:
    """逐角色推断情感弧线，并（在能对应到节拍表时）与声明的弧线对账。

    实现取巧但诚实：`_infer_speaker_state` 原本是"从台词里抠情绪"的私有函数，
    这里复用它，口径与账本里的 `characterStates[].emotion` 完全一致——
    两处若各写一套关键词表，作者会看到两个互相打架的"角色情绪"。
    """
    by_char: Dict[str, List[str]] = {}
    names = {str(c.id): (c.displayName or str(c.id)) for c in (project.characters or [])}
    for _cid, char_id, text in iter_dialogue(project):
        if char_id:
            by_char.setdefault(char_id, []).append(text)

    rows: List[EmotionPoint] = []
    for char_id, texts in by_char.items():
        who = names.get(char_id, char_id)
        track = _emotion_track(who, texts)
        if track is None:
            continue
        start, end, _evidence = track
        delta = EMOTION_ORDER.get(end, 1) - EMOTION_ORDER.get(start, 1)
        rows.append(EmotionPoint(character=who, start=start, end=end, delta=delta))
    rows.sort(key=lambda r: (-abs(r.delta), r.character))

    flat = [r for r in rows if abs(r.delta) < MIN_ARC_DELTA]
    return {
        "characters": [r.as_dict() for r in rows],
        # 从头到尾情绪没动过：不是错，但值得作者看一眼（尤其是主角）
        "flatArcs": [r.as_dict() for r in flat],
        "note": (
            "情绪由台词关键词推断，不是语义判断：反讽/压抑/言不由衷都可能读错。"
            "它只用来提示「这里可能没写出变化」，请结合原文判断。"
        ),
    }


def chapter_emotion_rows(project: VnProject) -> List[Dict[str, Any]]:
    """**逐章**的情绪走向：(角色, 章) → 开头情绪 / 结尾情绪 / 刻度差。

    为什么需要逐章：整部作品级的弧线能回答"这个角色有没有变化"，但答不出
    "哪一章把他写反了"——而后者才是作者拿着稿子能直接改的东西。
    逐章行还能被基准按章归因（见 `core/eval_longrange.py` 的情感弧线埋点）。
    """
    order = {
        str(getattr(ch, "id", "") or ""): i for i, ch in enumerate(project.chapters or [])
    }
    titles = {
        str(getattr(ch, "id", "") or ""): str(getattr(ch, "title", "") or "")
        for ch in (project.chapters or [])
    }
    names = {str(c.id): (c.displayName or str(c.id)) for c in (project.characters or [])}

    grouped: Dict[Tuple[str, str], List[str]] = {}
    for cid, char_id, text in iter_dialogue(project):
        if char_id and cid:
            grouped.setdefault((char_id, cid), []).append(text)

    rows: List[Dict[str, Any]] = []
    for (char_id, chapter_id), texts in grouped.items():
        if len(texts) < MIN_CHAPTER_LINES:
            continue
        who = names.get(char_id, char_id)
        track = _emotion_track(who, texts)
        if track is None:
            continue
        start, end, evidence = track
        rows.append(
            {
                "characterId": char_id,
                "character": who,
                "chapterId": chapter_id,
                "chapterTitle": titles.get(chapter_id, chapter_id),
                "chapterIndex": order.get(chapter_id, -1),
                "start": start,
                "end": end,
                "delta": EMOTION_ORDER.get(end, 1) - EMOTION_ORDER.get(start, 1),
                "lines": len(texts),
                "evidence": evidence,
            }
        )
    rows.sort(key=lambda r: (str(r["character"]), int(r["chapterIndex"])))
    return rows


def emotion_arc_breaks(project: VnProject) -> Dict[str, Any]:
    """找出**局部走向与全篇走向相反**的那些章（"这一章把角色情绪写反了"）。

    判定是保守的：只在"全篇有明确走向（|delta| ≥ 2）"且"该章也有明确走向（|delta| ≥ 2）"
    且两者**符号相反**时才报。全篇本来就平的、或者该章本来就平的，都不报——
    前者是另一条提示（`flatArcs`），后者属于"这一章没写情绪"，不是写反。
    """
    overall = {
        row["character"]: int(row["delta"])
        for row in emotion_arcs(project)["characters"]
    }
    rows = chapter_emotion_rows(project)
    breaks: List[Dict[str, Any]] = []
    for row in rows:
        base = overall.get(str(row["character"]))
        if base is None or abs(base) < MIN_ARC_DELTA:
            continue
        delta = int(row["delta"])
        if abs(delta) < MIN_ARC_DELTA:
            continue
        if delta * base >= 0:
            continue
        breaks.append(
            {
                "character": row["character"],
                "chapterId": row["chapterId"],
                "chapterTitle": row["chapterTitle"],
                "issue": "emotion_arc_break",
                "overallDelta": base,
                "chapterDelta": delta,
                "actual": f"{row['start']} → {row['end']}",
                "message": (
                    f"「{row['character']}」全篇情绪是往上走的，但在"
                    f"{row['chapterTitle']} 这一章却从 {row['start']} 掉到 {row['end']}"
                    "——局部走向和全篇相反，检查这一章是不是写反了（或少了过渡）"
                ),
            }
        )
    breaks.sort(key=lambda r: (str(r["chapterId"]), str(r["character"])))
    return {"rows": rows, "breaks": breaks}


def declared_arc_mismatches(
    project: VnProject, beat_sheets: Sequence[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """把节拍表**声明**的 emotionStart/End 与写成之后的实际弧线逐角色对账。

    ``beat_sheets``：历次 plan 阶段产出的节拍表（形如
    ``{"emotionStart": {"角色": "..."}, "emotionEnd": {...}}``）。
    只报"方向相反"或"声明有变化但实际没变"这两类**明显**不一致，并附证据。
    """
    actual = {r["character"]: r for r in emotion_arcs(project)["characters"]}
    out: List[Dict[str, Any]] = []
    for sheet in beat_sheets or []:
        if not isinstance(sheet, dict):
            continue
        starts = sheet.get("emotionStart") or {}
        ends = sheet.get("emotionEnd") or {}
        if not isinstance(starts, dict) or not isinstance(ends, dict):
            continue
        for who, declared_end in ends.items():
            name = str(who).strip()
            row = actual.get(name)
            if row is None:
                continue
            declared_start = str(starts.get(name) or "").strip()
            want = _declared_delta(declared_start, str(declared_end or "").strip())
            got = int(row["delta"])
            if want is None:
                continue
            if want != 0 and got == 0:
                out.append(
                    {
                        "character": name,
                        "issue": "arc_flat",
                        "declared": f"{declared_start} → {declared_end}",
                        "actual": f"{row['start']} → {row['end']}",
                        "message": (
                            f"节拍表声明「{name}」这一场从 {declared_start} 走到 {declared_end}，"
                            f"但台词推断出来前后都是「{row['start']}」——弧线可能没写出来"
                        ),
                    }
                )
            elif want * got < 0:
                out.append(
                    {
                        "character": name,
                        "issue": "arc_reversed",
                        "declared": f"{declared_start} → {declared_end}",
                        "actual": f"{row['start']} → {row['end']}",
                        "message": (
                            f"节拍表声明「{name}」的情绪往上走，实际却是反的"
                            f"（{row['start']} → {row['end']}）"
                        ),
                    }
                )
    return out


def _declared_delta(start: str, end: str) -> Optional[int]:
    """把节拍表里的中文情绪词折算成刻度差；认不出来的返回 None（不猜）。"""
    a = _match_emotion(start)
    b = _match_emotion(end)
    if a is None or b is None:
        return None
    return b - a


def _match_emotion(word: str) -> Optional[int]:
    """节拍表里写的是自由文本（"压抑""紧张"…），只认能明确对上的几个词。

    对不上就返回 None：**不猜**。把"紧张"硬映射成某个刻度，只会造出假警报。
    """
    if not word:
        return None
    plain = re.sub(r"\s+", "", word)
    mapping = (
        ("低落", ("低落", "消沉", "悲伤", "难过", "失望", "压抑")),
        ("平静", ("平静", "冷静", "淡然", "如常", "平稳")),
        ("疑惑", ("疑惑", "困惑", "不解", "迟疑", "狐疑")),
        ("担忧", ("担忧", "担心", "紧张", "不安", "警惕", "害怕", "恐惧")),
        ("愉悦", ("愉悦", "轻松", "放松", "开心", "高兴", "释然", "温柔")),
        ("激动", ("激动", "愤怒", "暴怒", "失控", "崩溃", "歇斯底里", "兴奋")),
    )
    for label, keys in mapping:
        if any(k in plain for k in keys):
            return EMOTION_ORDER[label]
    return None


# ------------------------------------------------------------------ 汇总入口


def analyze_story_metrics(
    project: VnProject, *, beat_sheets: Optional[Sequence[Dict[str, Any]]] = None
) -> Dict[str, Any]:
    """故事层体检：伏笔回收 + 情感弧线（+ 可选：与节拍表声明对账）。"""
    foreshadow = foreshadow_resolution(project)
    arcs = emotion_arcs(project)
    mismatches = declared_arc_mismatches(project, beat_sheets or [])
    findings: List[Dict[str, Any]] = []
    if foreshadow["total"] and (foreshadow["resolutionRate"] or 0) < 0.5:
        findings.append(
            {
                "severity": "warn",
                "code": "foreshadow_low_resolution",
                "message": (
                    f"伏笔回收率偏低：{foreshadow['paid']}/{foreshadow['total']} 已回收，"
                    f"最老的一条挂了 {foreshadow['oldestOpenChapters']} 章"
                ),
                "source": "story",
            }
        )
    for row in arcs["flatArcs"]:
        findings.append(
            {
                "severity": "info",
                "code": "emotion_arc_flat",
                "message": f"「{row['character']}」全篇情绪推断为「{row['start']}」没有变化",
                "source": "story",
            }
        )
    for m in mismatches:
        findings.append(
            {
                "severity": "warn",
                "code": m["issue"],
                "message": m["message"],
                "source": "story",
            }
        )
    # 逐章弧线断裂：带 chapterId，因此能按章归因（其它端点/前端也按这个字段定位）
    for brk in emotion_arc_breaks(project)["breaks"]:
        findings.append(
            {
                "severity": "warn",
                "code": brk["issue"],
                "message": brk["message"],
                "source": "story",
                "chapterId": brk["chapterId"],
                "character": brk["character"],
            }
        )
    # 每条未回收伏笔单列一条（带埋点章），便于按章展示与在基准里按章归因；
    # 上限 20 条：几十条未回收时列表会淹没其它建议，总量另有 foreshadow_low_resolution 兜底。
    for hook in foreshadow["openHooks"][:20]:
        findings.append(
            {
                "severity": "info",
                "code": "foreshadow_unresolved",
                "message": (
                    f"伏笔「{hook['hook'] or '(未命名)'}」埋在 "
                    f"{hook['plantedChapterTitle'] or hook['plantedChapter']}，"
                    f"已过 {hook['chaptersOpen']} 章仍未回收"
                ),
                "source": "story",
                "chapterId": hook["plantedChapter"],
            }
        )
    return {
        "foreshadow": foreshadow,
        "emotionArcs": arcs,
        "emotionArcBreaks": emotion_arc_breaks(project),
        "declaredArcMismatches": mismatches,
        "findings": findings,
        "counts": {
            "error": 0,
            "warn": sum(1 for f in findings if f["severity"] == "warn"),
            "info": sum(1 for f in findings if f["severity"] == "info"),
        },
    }
