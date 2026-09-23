"""卷级 / 全局记忆层：把"故事到目前为止发生了什么"压成一份可注入的压缩表示。

为什么需要这一层
----------------
现有记忆只有两级：每章抽取式摘要（``core/chapter_digest.py``）+ 每 10 章归档
（``core/novel_memory.py``，``DEFAULT_SPAN=10``）。两者之间**缺一层**：四十章之后，
Agent 要么拿到一堆逐章摘要（长、碎、看不出主线），要么拿到"第 31–40 章"这种等宽切片
（切片边界跟故事结构毫无关系）。而且全仓没有"重要性"这个概念——谁在故事里更重要、
哪条钩子埋得最久，都只能靠模型自己从一堆文本里猜。

这一层补的就是这两件事：**按卷（故事自己的单位）聚合** + **给出可解释的重要性排序**。

重要性公式（以及为什么这么算）
------------------------------
    base       = 出场章数 + HOOK_SUBJECT_WEIGHT × 承担章末钩子的章数
    recency    = RECENCY_FLOOR + (1 - RECENCY_FLOOR) × 0.5 ** (距最后一次出场过了几章 / 半衰期)
    importance = base × recency

- **出场章数为主项**：戏份是"这个角色在故事里有多重"最不容易出错的代理指标，
  而且是纯客观计数，作者一眼能核对。
- **章末钩子是第二项**：章末钩子是"读者记住这一章的原因"，也常常是下一章的驱动者。
  一个只出现一章却扛着该章的钩子的角色，比出现两章但从不承担钩子的角色更"重"。
  取 1.5 是让"两章出场 ≈ 一次钩子"，既抬得起关键客串，又压不过主角。
- **加时间衰减**：不加衰减时重要性是**静态累加**——一个第 3 章退场的角色，
  到了第 40 章分数还是原样，于是"谁现在还重要"答不准（这是这一层此前最明显的缺口）。
  现在按"距最后一次出场隔了几章"做半衰：默认半衰期 `RECENCY_HALF_LIFE` 章，
  半衰到 `RECENCY_FLOOR` 就不再掉——**不是抹掉他**，退场角色可能回来，
  只是"当下这卷里他没那么重"。
- **不加台词字数**：字数受写作习惯影响太大（话密的配角会凭空变大），而"出场章数"
  与"钩子主体"都是结构性的，跨卷可比。
- 排序键带上首次出场章号与名字，保证**同分时的顺序也是确定的**（可复现，不随字典序抖动）。
- 衰减**只在真的发生衰减时**才写进 `formula`：角色在档内最后一章还出场时，
  算式与加衰减之前逐字相同（作者不必看一堆 ×1.00）。

不做的事：**不调模型、不编造内容**。每一句总述都由章摘要 / 钩子 / 账本拼出来，
拼不出来就如实写"还没有内容"。代价是没有语义压缩（"主线到底是什么"仍要读者自己看
关键事件），收益是可复现、零成本、不会把模型幻觉写进记忆层。

预算与保真
----------
``format_global_memory_for_agent`` 在超预算时**优先保留全局总述与未回收伏笔**——
这两样是"写下一章必须先知道"的东西，被截掉等于记忆层失效；分卷明细可以省。
省了哪一部分会**如实写在注入块里**，不做静默截断。
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence

from app.core.blocks import iter_dialogue
from app.core.chapter_digest import digest_all_chapters
from app.core.novel_memory import DEFAULT_SPAN
from app.core.pipeline.ledger import foreshadow_report
from app.domain.types import VnProject

#: 章末钩子主体的加权（见模块 docstring 的公式说明）。
HOOK_SUBJECT_WEIGHT = 1.5

#: 时间衰减的半衰期（章）。距最后一次出场过了这么多章，recency 掉到一半。
RECENCY_HALF_LIFE = 8.0

#: recency 的下限。**不抹掉退场角色**：他可能回来，只是"当下这卷里没那么重"。
RECENCY_FLOOR = 0.25

MAX_KEY_EVENTS = 6
"""每卷最多列几条关键事件：再多就退化成"逐章摘要"，违背压缩的初衷。"""

MAX_VOLUME_CHARACTERS = 6
MAX_AGENT_HOOKS = 12
"""注入块里最多列几条未回收伏笔（全量照抄会把预算吃光）。"""

EVENT_CLIP = 90
HOOK_CLIP = 80

DEFAULT_AGENT_BUDGET = 2400
MIN_AGENT_BUDGET = 400
"""预算下限：保证"总述 ≤ 预算−120、伏笔清单 ≥ 120 字"两者都留得下。"""

OMIT_NOTE_RESERVE = 96
"""给"省略了哪一部分"这行说明预留的位置——不预留就必然会为了塞明细而挤掉它。"""

HOOK_MIN_CHARS = 120

_CJK_RE = re.compile(r"[\u4e00-\u9fff]")
_LATIN_RE = re.compile(r"[A-Za-z0-9]+")


def _clip(text: Any, cap: int) -> str:
    value = " ".join(str(text or "").split())
    if len(value) <= cap:
        return value
    return value[: cap - 1] + "…"


def count_words(text: str) -> int:
    """字数口径与 ``services.writing_stats`` / ``novel_memory`` 一致。"""
    value = str(text or "")
    return len(_CJK_RE.findall(value)) + len(_LATIN_RE.findall(value))


def _chapter_words(chapter: Any) -> int:
    """一章的字数：**prose 优先，没有正文才数 blocks**。

    与 ``services/writing_stats.count_chapter_words`` 完全同规则。core 不反向 import
    services（那里还挂着 sqlalchemy），所以这里复刻同一套规则；两边一旦分叉，
    "面板字数"和"记忆字数"就会对不上，作者只会觉得工具在胡说。
    """
    prose = str(getattr(chapter, "prose", None) or "")
    if prose.strip():
        return count_words(prose)
    total = 0
    for block in getattr(chapter, "blocks", None) or []:
        if not isinstance(block, dict):
            continue
        kind = block.get("type")
        if kind in ("narration", "dialogue"):
            total += count_words(str(block.get("text") or ""))
        elif kind == "raw":
            total += count_words(str(block.get("code") or ""))
        elif kind == "menu":
            for choice in block.get("choices") or []:
                if isinstance(choice, dict):
                    total += count_words(str(choice.get("text") or ""))
    return total


def _name_terms(char: Any) -> List[str]:
    values = [
        getattr(char, "displayName", ""),
        getattr(char, "defineName", ""),
        *(getattr(char, "aliases", None) or []),
    ]
    return [v for v in (str(x or "").strip() for x in values) if len(v) >= 2]


def _display_name(project: VnProject, character_id: str) -> str:
    for char in getattr(project, "characters", None) or []:
        if str(getattr(char, "id", "")) == str(character_id):
            return str(getattr(char, "displayName", "") or character_id)
    return str(character_id)


def _chapter_rows(project: VnProject) -> List[Dict[str, Any]]:
    """按章序整理一行一章：标题、字数、摘要、起迄钩子、归属卷。"""
    digests = {d.chapterId: d for d in digest_all_chapters(project)}
    rows: List[Dict[str, Any]] = []
    for index, chapter in enumerate(getattr(project, "chapters", None) or [], start=1):
        digest = digests.get(chapter.id)
        words = _chapter_words(chapter)
        synopsis = str(getattr(digest, "synopsis", "") or "") if digest else ""
        open_hook = str(getattr(digest, "openHook", "") or "") if digest else ""
        close_hook = str(getattr(digest, "closeHook", "") or "") if digest else ""
        speakers = list(getattr(digest, "speakers", None) or []) if digest else []
        # 空章的 beatSummary 会是"（空章）"这种占位串。照抄进关键事件，作者会看到一堆
        # 假事件；所以先判断"这一章到底有没有写出内容"，没有就把摘要清空。
        # 判据只看**文字**：字数、出场角色、章节简介。刻意不把起迄钩子算进来——
        # 只有 label / scene 标签的章（新建工程的默认章就是这样）也会生成
        # "[label start]" 这种"钩子"，把它当成事件等于把空章包装成有剧情。
        has_content = bool(words or speakers or synopsis)
        rows.append(
            {
                "index": index,
                "chapterId": str(chapter.id),
                "title": str(chapter.title or f"第{index}章"),
                "volumeId": str(getattr(chapter, "volumeId", None) or ""),
                "words": words,
                "hasContent": has_content,
                "beatSummary": (
                    str(getattr(digest, "beatSummary", "") or "") if has_content else ""
                ),
                "openHook": open_hook,
                "closeHook": close_hook,
                "speakers": speakers,
            }
        )
    return rows


def _speaker_index(project: VnProject) -> Dict[str, Dict[str, int]]:
    """章 id → {角色 id: 台词数}。用角色 id（而不是显示名）做键，改名不会丢归属。"""
    out: Dict[str, Dict[str, int]] = {}
    for chapter_id, character_id, _text in iter_dialogue(project):
        if not character_id:
            continue
        bucket = out.setdefault(str(chapter_id), {})
        key = str(character_id)
        bucket[key] = bucket.get(key, 0) + 1
    return out


def _hook_subjects(project: VnProject, close_hook: str) -> set:
    """章末钩子里出现的角色 id（名字/别名/defineName 命中，且名字至少 2 字避免误命中）。"""
    text = str(close_hook or "")
    if not text:
        return set()
    out = set()
    for char in getattr(project, "characters", None) or []:
        if any(term in text for term in _name_terms(char)):
            out.add(str(getattr(char, "id", "")))
    return out


def recency_factor(chapters_since_last: int) -> float:
    """时间衰减系数：距最后一次出场隔了几章 → 乘数（``RECENCY_FLOOR`` ~ 1.0）。

    为什么是"半衰 + 下限"而不是线性扣分：
    - 半衰符合直觉（隔一个半衰期，分量减半），且**永远为正**——不会出现"负分角色"；
    - 下限 `RECENCY_FLOOR` 保证退场角色**不会被抹掉**：记忆层的作用是提醒作者
      "这个人曾经重要"，而不是替他决定"这个人物可以删了"。
    """
    if chapters_since_last <= 0:
        return 1.0
    decay = 0.5 ** (float(chapters_since_last) / max(0.5, float(RECENCY_HALF_LIFE)))
    return float(RECENCY_FLOOR + (1.0 - RECENCY_FLOOR) * decay)


def _volume_characters(
    project: VnProject,
    rows: Sequence[Dict[str, Any]],
    speaker_index: Dict[str, Dict[str, int]],
) -> List[Dict[str, Any]]:
    """某一档里出场角色的重要性排序（公式见模块 docstring）。"""
    stats: Dict[str, Dict[str, Any]] = {}
    for row in rows:
        lines_by_char = speaker_index.get(row["chapterId"]) or {}
        subjects = _hook_subjects(project, row.get("closeHook") or "")
        for character_id, line_count in lines_by_char.items():
            entry = stats.setdefault(
                character_id,
                {
                    "characterId": character_id,
                    "appearedChapters": 0,
                    "hookChapters": 0,
                    "dialogueLines": 0,
                    "chapters": [],
                },
            )
            entry["appearedChapters"] += 1
            entry["dialogueLines"] += int(line_count)
            entry["chapters"].append(row["index"])
            if character_id in subjects:
                entry["hookChapters"] += 1

    out: List[Dict[str, Any]] = []
    # 这一档的"截止点"：本档最后一章的序号。衰减是相对它算的——
    # 也就是"读到这一卷末尾时，这个角色已经多久没出现了"。
    as_of = max((int(r["index"]) for r in rows), default=0)
    for character_id, entry in stats.items():
        appeared = int(entry["appearedChapters"])
        hooks = int(entry["hookChapters"])
        base = appeared + HOOK_SUBJECT_WEIGHT * hooks
        chapters = sorted(entry["chapters"])
        last = chapters[-1] if chapters else 0
        since = max(0, as_of - int(last))
        recency = recency_factor(since)
        score = base * recency
        formula = (
            f"出场 {appeared} 章 + 章末钩子 {hooks} 次 × {HOOK_SUBJECT_WEIGHT}"
            f" = {round(base, 2)}"
        )
        if recency < 1.0:
            formula += (
                f"，再按「距上次出场 {since} 章」衰减 × {round(recency, 2)}"
                f" → {round(score, 2)}"
            )
        out.append(
            {
                "characterId": character_id,
                "name": _display_name(project, character_id),
                "score": round(score, 2),
                "baseScore": round(base, 2),
                "recency": round(recency, 4),
                "chaptersSinceLast": since,
                "appearedChapters": appeared,
                "hookChapters": hooks,
                "dialogueLines": int(entry["dialogueLines"]),
                "firstChapter": chapters[0] if chapters else None,
                "lastChapter": last or None,
                "chapters": chapters,
                # 把算式一并交出去：作者要能核对"为什么他排在前面"，而不是只能信这个数。
                "formula": formula,
            }
        )
    out.sort(
        key=lambda r: (
            -float(r["score"]),
            -int(r["appearedChapters"]),
            int(r["firstChapter"] or 0),
            str(r["name"]),
        )
    )
    return out


def _key_events(rows: Sequence[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """关键事件：优先"带钩子"的章（有钩子=这一章确实发生了事），不足再按章序补。

    只认有 ``beatSummary`` 的章：摘要已被抽成"这一章有没有写出内容"的判据
    （见 ``_chapter_rows``），因此只有 label/scene 标签的空章不会混进来。
    """
    filled = [r for r in rows if r["beatSummary"]]
    if not filled:
        return []
    picked = [r for r in filled if r["closeHook"] or r["openHook"]][:MAX_KEY_EVENTS]
    picked_ids = {r["chapterId"] for r in picked}
    for row in filled:
        if len(picked) >= MAX_KEY_EVENTS:
            break
        if row["chapterId"] not in picked_ids:
            picked.append(row)
            picked_ids.add(row["chapterId"])
    picked.sort(key=lambda r: int(r["index"]))
    return [
        {
            "chapterId": row["chapterId"],
            "index": row["index"],
            "title": row["title"],
            "beatSummary": _clip(row["beatSummary"], EVENT_CLIP),
            "openHook": _clip(row["openHook"], HOOK_CLIP),
            "closeHook": _clip(row["closeHook"], HOOK_CLIP),
        }
        for row in picked
    ]


def _open_foreshadows(project: VnProject) -> List[Dict[str, Any]]:
    """未回收伏笔：复用 ``ledger.foreshadow_report``，只留 status == "open" 的。

    按"埋了多久"倒序——最久没回收的那条最该被推进，排在前面才显眼。
    """
    try:
        report = foreshadow_report(project)
    except Exception:  # noqa: BLE001 — 账本脏数据不该让记忆层崩掉
        return []
    out: List[Dict[str, Any]] = []
    for row in report or []:
        if not isinstance(row, dict):
            continue
        if str(row.get("status") or "open") != "open":
            continue
        age = row.get("ageChapters")
        out.append(
            {
                "id": row.get("id"),
                "hook": _clip(row.get("hook"), HOOK_CLIP),
                "plantedChapter": str(row.get("plantedChapter") or ""),
                "plantedChapterTitle": str(row.get("plantedChapterTitle") or ""),
                "ageChapters": age if isinstance(age, int) else None,
                "note": _clip(row.get("note"), 60),
            }
        )
    out.sort(key=lambda r: (-(r["ageChapters"] or 0), str(r.get("plantedChapter") or "")))
    return out


def _volume_bands(
    project: VnProject, rows: Sequence[Dict[str, Any]]
) -> List[Dict[str, Any]]:
    """分档：有卷就按卷聚合，没卷就按 ``novel_memory.DEFAULT_SPAN`` 等宽分档。

    两种情况下**每一章都必须落进某一档**：没有任何一章会被静默丢掉（分卷作品里
    没挂卷的章节会进"未分卷章节"档，而不是消失）。
    """
    volumes = [v for v in (getattr(project, "volumes", None) or [])]
    bands: List[Dict[str, Any]] = []
    if volumes:
        used: set = set()
        for index, volume in enumerate(volumes, start=1):
            volume_id = str(getattr(volume, "id", "") or "")
            group = [r for r in rows if r["volumeId"] == volume_id]
            used.update(r["chapterId"] for r in group)
            bands.append(
                {
                    "index": index,
                    "title": str(getattr(volume, "title", "") or f"第{index}卷"),
                    "volumeId": volume_id,
                    "synthetic": False,
                    "note": str(getattr(volume, "note", "") or ""),
                    "rows": group,
                }
            )
        loose = [r for r in rows if r["chapterId"] not in used]
        if loose:
            bands.append(
                {
                    "index": len(volumes) + 1,
                    "title": "未分卷章节",
                    "volumeId": None,
                    "synthetic": True,
                    "note": "",
                    "rows": loose,
                }
            )
        return bands

    for band_index, start in enumerate(range(0, len(rows), DEFAULT_SPAN), start=1):
        group = list(rows[start : start + DEFAULT_SPAN])
        if not group:
            continue
        bands.append(
            {
                "index": band_index,
                "title": f"第{band_index}档",
                "volumeId": None,
                "synthetic": True,
                "note": "",
                "span": DEFAULT_SPAN,
                "rows": group,
            }
        )
    return bands


def _build_volume(
    project: VnProject,
    band: Dict[str, Any],
    hooks: Sequence[Dict[str, Any]],
    speaker_index: Dict[str, Dict[str, int]],
) -> Dict[str, Any]:
    """把一档（一卷或一等宽跨度）聚合成记忆条目。``speaker_index`` 由调用方复用，
    避免每档都重扫全项目 blocks（那会退化成 O(档数 × 全文)）。"""
    rows = list(band["rows"])
    chapter_ids = {r["chapterId"] for r in rows}
    words = sum(int(r["words"]) for r in rows)
    characters = _volume_characters(project, rows, speaker_index)
    return {
        "index": band["index"],
        "title": band["title"],
        "volumeId": band.get("volumeId"),
        "synthetic": bool(band.get("synthetic")),
        "note": band.get("note") or "",
        "chapterFrom": rows[0]["index"] if rows else None,
        "chapterTo": rows[-1]["index"] if rows else None,
        "chapterCount": len(rows),
        "chapterIds": [r["chapterId"] for r in rows],
        "chapterTitles": [r["title"] for r in rows],
        "wordCount": words,
        "characters": characters[:MAX_VOLUME_CHARACTERS],
        "keyEvents": _key_events(rows),
        "openForeshadows": [
            h for h in hooks if str(h.get("plantedChapter") or "") in chapter_ids
        ],
        "empty": words == 0 and not characters,
    }


def _overall(
    project: VnProject,
    rows: Sequence[Dict[str, Any]],
    volumes: Sequence[Dict[str, Any]],
    hooks: Sequence[Dict[str, Any]],
    speaker_index: Dict[str, Dict[str, int]],
) -> Dict[str, Any]:
    """全局总述：全部由模板从既有数据拼出来，**不编造任何情节**。"""
    title = str(getattr(project, "title", "") or "未命名剧本")
    words = sum(int(r["words"]) for r in rows)
    top = _volume_characters(project, rows, speaker_index)[:3]
    lines: List[str] = []

    if not rows:
        lines.append(f"《{title}》还没有任何章节。")
    else:
        lines.append(
            f"《{title}》已写 {len(rows)} 章（{len(volumes)} 卷/档），约 {words} 字。"
        )
        if top:
            who = "、".join(
                f"{c['name']}（出场 {c['appearedChapters']} 章"
                + (f"、章末钩子 {c['hookChapters']} 次" if c["hookChapters"] else "")
                + "）"
                for c in top
            )
            lines.append(f"主要角色：{who}。")
        else:
            lines.append("主要角色：（还没有对白出场记录，判断不出主线人物）。")

    last = next((r for r in reversed(list(rows)) if r["beatSummary"]), None)
    progress: Optional[Dict[str, Any]] = None
    if last is not None:
        # 摘要本身常以句号结尾，这里去掉尾部标点再补句号，免得出现"。。"
        detail = (last["beatSummary"] or last["closeHook"]).rstrip("。．.！!？?")
        lines.append(
            f"主线推进到：第 {last['index']} 章《{last['title']}》——{_clip(detail, 120)}。"
        )
        progress = {
            "chapterId": last["chapterId"],
            "index": last["index"],
            "title": last["title"],
            "detail": _clip(detail, 120),
        }
    elif rows:
        lines.append("主线推进到：（章节都还是空的，还没有内容可概括）。")

    if hooks:
        oldest = max(hooks, key=lambda h: int(h.get("ageChapters") or 0))
        where = oldest.get("plantedChapterTitle") or oldest.get("plantedChapter") or "?"
        age = oldest.get("ageChapters")
        age_bit = f"，已过 {age} 章" if isinstance(age, int) else ""
        lines.append(
            f"还有 {len(hooks)} 条钩子没收：最久的一条「{oldest.get('hook')}」"
            f"埋于《{where}》{age_bit}。"
        )
    else:
        lines.append("目前没有登记未回收的钩子（伏笔账本为空，或已全部回收）。")

    return {
        "text": "\n".join(lines),
        "chapterCount": len(rows),
        "wordCount": words,
        "topCharacters": top,
        "progress": progress,
        "openHookCount": len(hooks),
        "openHooks": list(hooks),
    }


def build_global_memory(project: VnProject) -> Dict[str, Any]:
    """卷级 + 全局记忆（**纯本地、不调模型**）。

    数据不足时安全返回：没有章节 → 空的 volumes 与"还没有任何章节"的总述；
    全是空章 → 字数 0、角色为空、关键事件为空；没有角色 → 角色列表为空。
    任何一步都不该抛异常——记忆层挂了不该让写作链路跟着挂。
    """
    rows = _chapter_rows(project)
    speaker_index = _speaker_index(project)
    hooks = _open_foreshadows(project)
    volumes = [
        _build_volume(project, band, hooks, speaker_index)
        for band in _volume_bands(project, rows)
    ]
    overall = _overall(project, rows, volumes, hooks, speaker_index)
    return {
        "title": str(getattr(project, "title", "") or "未命名剧本"),
        "chapterCount": len(rows),
        "wordCount": overall["wordCount"],
        "span": DEFAULT_SPAN,
        "groupedBy": "volume" if (getattr(project, "volumes", None) or []) else "span",
        "hookSubjectWeight": HOOK_SUBJECT_WEIGHT,
        "volumes": volumes,
        "overall": overall,
        "notes": [
            "纯本地聚合：不含模型调用，可复现（同一项目每次结果一致）",
            f"重要性 = 出场章数 + {HOOK_SUBJECT_WEIGHT} × 章末钩子主体章数（见 formula 字段）",
            f"无卷作品按每 {DEFAULT_SPAN} 章分档，与 novel_memory 的归档跨度一致",
        ],
    }


# ------------------------------------------------------------------ 注入块


def _collect_hooks(memory: Dict[str, Any]) -> List[Dict[str, Any]]:
    """注入块用的伏笔清单：从各卷收集并按 id 去重（同一伏笔只出现在它被埋的那一卷）。"""
    out: List[Dict[str, Any]] = []
    seen: set = set()
    for volume in memory.get("volumes") or []:
        for hook in volume.get("openForeshadows") or []:
            key = str(hook.get("id") or hook.get("hook") or "")
            if not key or key in seen:
                continue
            seen.add(key)
            out.append(hook)
    out.sort(key=lambda r: (-(r.get("ageChapters") or 0), str(r.get("plantedChapter") or "")))
    return out


def _fit(block: str, limit: int, label: str) -> str:
    """把一段内容压进 limit 字符；压不下就截断并**如实标注**截断了什么。"""
    text = str(block or "").strip()
    if not text or limit <= 0:
        return ""
    if len(text) <= limit:
        return text
    note = f"\n…（{label}过长，已截断）"
    if len(note) + 8 > limit:
        note = "…（截断）"
    if len(note) >= limit:
        return ""
    return text[: limit - len(note)].rstrip() + note


def _range_label(volume: Dict[str, Any]) -> str:
    start, end = volume.get("chapterFrom"), volume.get("chapterTo")
    if start is None:
        return "无章节"
    if start == end:
        return f"第{start}章"
    return f"第{start}–{end}章"


def _overall_block(overall: Dict[str, Any]) -> str:
    text = str((overall or {}).get("text") or "").strip()
    if not text:
        return ""
    return "## 全局总述（到目前为止）\n" + text


def _hooks_block(memory: Dict[str, Any]) -> str:
    hooks = _collect_hooks(memory)
    if not hooks:
        return ""
    lines = ["## 未回收伏笔（写新章时应推进或回收）"]
    for hook in hooks[:MAX_AGENT_HOOKS]:
        age = hook.get("ageChapters")
        where = hook.get("plantedChapterTitle") or hook.get("plantedChapter") or "?"
        age_bit = f"，已埋 {age} 章" if isinstance(age, int) else ""
        lines.append(f"- {hook.get('hook')}（植于 {where}{age_bit}）")
    hidden = len(hooks) - MAX_AGENT_HOOKS
    if hidden > 0:
        lines.append(f"- …另有 {hidden} 条未列出（清单上限 {MAX_AGENT_HOOKS} 条）")
    return "\n".join(lines)


def _volume_block(volume: Dict[str, Any]) -> str:
    head = (
        f"### {volume.get('title')}（{_range_label(volume)} · "
        f"{int(volume.get('wordCount') or 0)} 字）"
    )
    lines = [head]
    if volume.get("note"):
        lines.append(f"- 卷备注：{_clip(volume.get('note'), 80)}")
    characters = volume.get("characters") or []
    if characters:
        who = "、".join(
            f"{c['name']}（{c['formula']}）" for c in characters[:MAX_VOLUME_CHARACTERS]
        )
        lines.append(f"- 出场角色（按重要性）：{who}")
    else:
        lines.append("- 出场角色：（本档没有对白出场记录）")
    events = volume.get("keyEvents") or []
    if events:
        lines.append("- 关键事件：")
        for event in events:
            hook = event.get("closeHook") or event.get("openHook")
            tail = f"（迄：{hook}）" if hook else ""
            lines.append(f"  - 第{event['index']}章《{event['title']}》：{event['beatSummary']}{tail}")
    else:
        lines.append("- 关键事件：（本档还没有写出内容）")
    hooks = volume.get("openForeshadows") or []
    if hooks:
        joined = "；".join(
            f"「{h.get('hook')}」（植于 {h.get('plantedChapterTitle') or h.get('plantedChapter')}）"
            for h in hooks[:4]
        )
        more = f"，另有 {len(hooks) - 4} 条" if len(hooks) > 4 else ""
        lines.append(f"- 未回收伏笔 {len(hooks)} 条：{joined}{more}")
    return "\n".join(lines)


def format_global_memory_for_agent(
    memory: Dict[str, Any], *, max_chars: int = DEFAULT_AGENT_BUDGET
) -> str:
    """给 Agent 用的紧凑注入块。

    超预算时的取舍是**写死的**：全局总述与未回收伏笔一定留下（写下一章必须先知道
    "故事到哪了"和"哪些坑还开着"），先牺牲分卷明细；省了哪几卷会写在末尾。
    预算下限 400 字，就是为了保证上面两样在极端情况下也能各留一段。
    """
    data = memory if isinstance(memory, dict) else {}
    budget = max(MIN_AGENT_BUDGET, int(max_chars or DEFAULT_AGENT_BUDGET))

    overall_block = _overall_block(data.get("overall") or {})
    hooks_block = _hooks_block(data)
    volume_blocks = [
        (str(volume.get("title") or f"第{volume.get('index')}卷"), _volume_block(volume))
        for volume in data.get("volumes") or []
    ]

    kept: List[str] = []
    used = 0

    # 1) 全局总述：最高优先级。太长时先压它，也要给伏笔留出 HOOK_MIN_CHARS。
    if overall_block:
        if len(overall_block) > budget - HOOK_MIN_CHARS:
            overall_block = _fit(
                overall_block, max(120, budget - HOOK_MIN_CHARS), "全局总述"
            )
        if overall_block:
            kept.append(overall_block)
            used += len(overall_block) + 1

    # 2) 未回收伏笔：第二优先级。预算下限保证了这里至少有 ~120 字可用。
    room = budget - used - 1
    fitted_hooks = _fit(hooks_block, room, "未回收伏笔清单") if hooks_block else ""
    if fitted_hooks:
        kept.append(fitted_hooks)
        used += len(fitted_hooks) + 1

    # 3) 分卷明细：有预算才放，放不下就如实记下省了哪几卷。
    omitted: List[str] = []
    for name, block in volume_blocks:
        if used + len(block) + 1 + OMIT_NOTE_RESERVE <= budget:
            kept.append(block)
            used += len(block) + 1
        else:
            omitted.append(name)
    if omitted:
        kept.append(
            f"…（预算 {budget} 字已用尽，省略了 {len(omitted)} 段分卷明细："
            f"{'、'.join(omitted[:6])}"
            + ("…" if len(omitted) > 6 else "")
            + "；需要时提高 max_chars）"
        )

    text = "\n\n".join(part for part in kept if part.strip())
    if not text.strip():
        return "（全局记忆为空：项目里还没有可汇总的章节内容）"
    return text
