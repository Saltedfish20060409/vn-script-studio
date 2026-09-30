"""Project writing ledger — hard anchors for memory-aware generation.

两条写入路径：

1. ``digest_chapter_into_ledger`` —— 单章入库（手工端点 / 流水线 gate 用，可带 LLM 增强）；
2. ``auto_digest_ledger`` —— **保存时自动**跑，纯本地、按章节内容指纹增量更新。
   线上实测：需要用户主动下命令的能力（含账本）几乎没人用，而"保存时自动刷新"的
   章节摘要 159/159 全覆盖 —— 所以账本也走自动这条线（见 README/roadmap 讨论）。
"""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from app.core.agent_context import chapter_plain
from app.core.chapter_digest import chapter_content_hash, make_chapter_digest
from app.domain.types import VnProject

#: `chapter_digest` 会把结构块渲染成方括号标记（`[label start]` / `[scene bg_x]` /
#: `[选项] …` / `[音乐 …]`）。它们不是"钩子"，只是演出结构。
_MARKER_RE = re.compile(r"\[[^\]]*\]")


def _hook_has_prose(close_hook: str) -> bool:
    """章末钩子里必须含**真正的正文**才算一条伏笔。

    原来只判 `len(close_hook) > 4`，于是"只写了一个 label 的空章"也会被记成
    「章末钩子（自动）」——`[label start]` 有 13 个字符，轻松过线。后果有两层：
    ① 伏笔回收率被结构标记污染（空章也算"埋了没收"）；
    ② 那条假钩子会进 `format_ledger_for_agent` 的未回收清单，**当成事实喂给写作模型**。
    """
    stripped = _MARKER_RE.sub("", close_hook or "").strip()
    return len(stripped) > 4


#: 账本各列表的保留预算。这些数字是 **JSONB blob 的体积闸**，不是业务上限——
#: 所以每一次裁剪都必须留下痕迹（写进 ``ledger["retention"]``，见 `_retention_record`），
#: 否则就是 `docs/long-context-policy.md` 里明令禁止的那种"静默失忆"。
_MAX_CHAPTER_FACTS = 40
_MAX_CHARACTER_STATES = 60
#: 已回收伏笔的保留量。未回收的**另有独立上限**，不与它抢位置（见 `_retain_foreshadows`）。
_MAX_PAID_FORESHADOWS = 40
#: 未回收伏笔的硬上限：只用来保护 blob 体积，正常长篇远达不到。
_MAX_OPEN_FORESHADOWS = 120
_MAX_EVENTS = 50


def _retain_foreshadows(
    rows: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """裁剪伏笔列表：**未回收的优先于已回收的**，并如实报告丢了什么。

    为什么不能直接 `rows[-40:]`：这个列表是按**插入顺序**追加的，而唯一会被
    原地更新的是"同一个钩子再次被报出来"（见下方去重分支）。尾部截断因此丢掉的
    恰好是**最早埋下的那条**——而"埋了 25 章还没回收"正是这个功能存在的全部理由。
    一个每章一个钩子的工程，写到第 41 章时第 1 章的钩子就静默消失了。
    与之叠加的是 `global_memory.MAX_AGENT_HOOKS`（能进提示词的条数另有上限），
    所以"账本里丢了"实际等于"模型永远看不到"。而伏笔回收率
    （`story_metrics`）与未回收清单都是读这个列表算的，回收率会因此凭空变好。

    保留优先级：
    1. 未回收（``status != "paid"``）全部保留，直到硬上限 ``_MAX_OPEN_FORESHADOWS``。
       超上限时保留**挂得最久**的那些：`foreshadow_report` 按章龄倒序展示，
       最老的正是作者最该先处理的；被丢掉的条数与"最老的一条植于第几章"一并记进
       retention，作者能据此知道账本已经装不下了，而不是以为都收干净了。
    2. 已回收的填剩余预算，**最老的先淘汰**——它们已经完成了信息使命。
    """
    is_open = [str(r.get("status") or "open") != "paid" for r in rows]
    open_idx = [i for i, o in enumerate(is_open) if o]
    paid_idx = [i for i, o in enumerate(is_open) if not o]

    evicted: Dict[str, int] = {}
    if len(open_idx) > _MAX_OPEN_FORESHADOWS:
        evicted["open"] = len(open_idx) - _MAX_OPEN_FORESHADOWS
        open_idx = open_idx[:_MAX_OPEN_FORESHADOWS]
    if len(paid_idx) > _MAX_PAID_FORESHADOWS:
        evicted["paid"] = len(paid_idx) - _MAX_PAID_FORESHADOWS
        paid_idx = paid_idx[-_MAX_PAID_FORESHADOWS:]

    keep = set(open_idx) | set(paid_idx)
    # 保持原有相对顺序：下游（`_foreshadow_rows` / 前端列表）都按这个顺序读。
    return [r for i, r in enumerate(rows) if i in keep], evicted


def _retain_character_states(
    rows: List[Dict[str, Any]],
) -> Tuple[List[Dict[str, Any]], Dict[str, int]]:
    """裁剪角色状态：**每个角色至少保留最新一条**。

    为什么不能 `rows[-60:]`：states 是"每章 × 每出场角色"一行，尾部截断会让一个
    **只在早期出场过**的角色整条消失——而 `write_precheck` 正是靠这些状态判断
    "这个人是不是已经死了 / 还在不在场"。60 行大约只够 10 章 × 6 个出场角色，
    所以写到十几章，早期角色的状态就开始被后来的角色挤掉，而且**被挤掉的顺序
    取决于谁最近话多**，与实际重要性无关：一个第 3 章退场、后文只被提及的角色，
    他的"已死亡"记录会先于话多的配角消失。

    策略：先给每个角色保留最新一条（保底——这正是 `_latest_states_by_name`
    与 `format_ledger_for_agent` 真正要的东西），剩余预算再按时间倒序填历史行。
    历史能留多少留多少，但"每个人现在是什么状态"永远留得住。
    """

    def key(row: Dict[str, Any]) -> str:
        return str(row.get("characterName") or row.get("characterId") or "")

    latest: Dict[str, int] = {}
    for i, r in enumerate(rows):
        k = key(r)
        if k:
            latest[k] = i  # 后写覆盖先写 → 每人最后一次出现
    must = set(latest.values())

    evicted: Dict[str, int] = {}
    if len(must) >= _MAX_CHARACTER_STATES:
        # 角色数本身就超预算（极端）：保留最近出场的那批角色，其余计数上报。
        ordered = sorted(must, reverse=True)
        keep = set(ordered[:_MAX_CHARACTER_STATES])
        evicted["states"] = len(must) - len(keep)
    else:
        rest = [i for i in range(len(rows)) if i not in must]
        room = _MAX_CHARACTER_STATES - len(must)
        keep = must | set(rest[-room:]) if room > 0 else set(must)
        lost = max(0, len(rest) - room)
        if lost:
            evicted["states"] = lost

    return [r for i, r in enumerate(rows) if i in keep], evicted


def _retention_record(
    ledger: Dict[str, Any], evicted: Dict[str, int]
) -> Dict[str, Any]:
    """把本次裁剪记进账本，并累加"账本一共丢过多少条"。

    为什么要累加而不是只记本次：``auto_digest_ledger`` 每次保存都从**已经裁剪过**
    的列表上重算，所以第 41 章丢掉的那条钩子，到第 42 章再算时 `evicted` 是 0——
    只看"本次"会得出"从没丢过"的错误结论。累计值才是诚实的读数。
    """
    prev = ledger.get("retention") if isinstance(ledger.get("retention"), dict) else {}
    prev_total = prev.get("evictedTotal") if isinstance(prev.get("evictedTotal"), dict) else {}
    total = {k: int(prev_total.get(k) or 0) for k in set(prev_total) | set(evicted)}
    for k, v in (evicted or {}).items():
        total[k] = total.get(k, 0) + int(v or 0)

    record: Dict[str, Any] = {
        "evictedNow": dict(evicted or {}),
        "evictedTotal": total,
        "caps": {
            "chapterFacts": _MAX_CHAPTER_FACTS,
            "characterStates": _MAX_CHARACTER_STATES,
            "paidForeshadows": _MAX_PAID_FORESHADOWS,
            "openForeshadows": _MAX_OPEN_FORESHADOWS,
            "events": _MAX_EVENTS,
        },
        "updatedAt": _now(),
    }
    if any(total.values()):
        record["note"] = (
            "账本按体积预算裁剪过：未回收伏笔不会因为已回收的占位而被丢弃，"
            "每个角色也至少保留最新一条状态。evictedTotal 是累计丢失条数——"
            "不为 0 说明账本已经装不下这段历史，长程一致性会因此打折。"
        )
    return record


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _infer_speaker_state(plain: str, name: str) -> tuple[str, str]:
    """Pick emotion + body snippet from the speaker's last dialogue lines."""
    lines: List[str] = []
    for line in (plain or "").splitlines():
        s = line.strip()
        if not s:
            continue
        if s.startswith(f"{name}:") or s.startswith(f"{name}："):
            frag = s.split(":", 1)[-1].split("：", 1)[-1].strip()
            # strip quotes
            frag = frag.strip("\"「」''")
            if frag:
                lines.append(frag)
        elif f'{name} "' in s or f"{name} 「" in s:
            lines.append(s)
    last = lines[-1] if lines else ""
    body = (last[:48] + ("…" if len(last) > 48 else "")) if last else "出场"
    emotion = "平静"
    blob = "".join(lines[-3:]) if lines else ""
    if any(x in blob for x in ("！", "!", "啊", "混蛋", "该死")):
        emotion = "激动"
    elif any(x in blob for x in ("？", "?", "为什么", "难道")):
        emotion = "疑惑"
    elif any(x in blob for x in ("…", "...", "……", "算了", "没事")):
        emotion = "低落"
    elif any(x in blob for x in ("哈哈", "呵呵", "谢谢", "喜欢")):
        emotion = "愉悦"
    elif any(x in blob for x in ("怕", "担心", "别", "小心")):
        emotion = "担忧"
    return emotion, body or "—"


def _speakers_from_plain(plain: str, characters: List[Any]) -> List[str]:
    """Fallback speaker list when chapter only has raw lines."""
    names = []
    for c in characters or []:
        n = getattr(c, "displayName", None) or getattr(c, "defineName", None)
        if n:
            names.append(str(n))
    found: List[str] = []
    seen = set()
    for line in (plain or "").splitlines():
        s = line.strip()
        for name in names:
            if s.startswith(f"{name}:") or s.startswith(f"{name}："):
                if name not in seen:
                    seen.add(name)
                    found.append(name)
                break
    return found


def empty_ledger() -> Dict[str, Any]:
    return {
        "chapterFacts": [],
        "characterStates": [],
        "foreshadows": [],
        "events": [],
        #: 裁剪痕迹（见 `_retention_record`）。**必须在这里与 get_ledger 都放行**，
        #: 否则会被读路径规范化掉，"账本丢过东西"这件事就又变成不可见的了。
        "retention": {},
        "updatedAt": _now(),
    }


def get_ledger(project: VnProject) -> Dict[str, Any]:
    raw = getattr(project, "writingLedger", None)
    if isinstance(raw, dict) and raw:
        return {
            "chapterFacts": list(raw.get("chapterFacts") or []),
            "characterStates": list(raw.get("characterStates") or []),
            "foreshadows": list(raw.get("foreshadows") or []),
            "events": list(raw.get("events") or []),
            "retention": dict(raw.get("retention") or {}),
            "updatedAt": raw.get("updatedAt") or _now(),
        }
    return empty_ledger()


def set_ledger(project: VnProject, ledger: Dict[str, Any]) -> VnProject:
    data = project.model_dump()
    ledger = {**ledger, "updatedAt": _now()}
    data["writingLedger"] = ledger
    return VnProject.model_validate(data)


def _foreshadow_rows(
    ledger: Dict[str, Any], chapters: Optional[List[Any]] = None
) -> List[Dict[str, Any]]:
    """伏笔行（含"埋了多久"）。chapters 为空时 ageChapters 为 None。"""
    order = {str(getattr(c, "id", "")): i for i, c in enumerate(chapters or [])}
    last = len(order) - 1 if order else 0

    def title_of(cid: str) -> str:
        if not cid:
            return ""
        ch = next((c for c in (chapters or []) if str(getattr(c, "id", "")) == cid), None)
        return (getattr(ch, "title", "") or cid) if ch is not None else cid

    out: List[Dict[str, Any]] = []
    for fo in ledger.get("foreshadows") or []:
        planted = str(fo.get("plantedChapter") or "")
        paid_in = str(fo.get("paidInChapter") or "")
        status = str(fo.get("status") or "open")
        p_idx = order.get(planted)
        age = None
        if p_idx is not None and order:
            end_idx = order.get(paid_in, last) if status == "paid" else last
            age = max(0, end_idx - p_idx)
        out.append(
            {
                "id": fo.get("id"),
                "hook": fo.get("hook") or "",
                "status": status,
                "note": fo.get("note") or "",
                "plantedChapter": planted,
                "plantedChapterTitle": title_of(planted),
                "paidInChapter": paid_in or None,
                "paidChapterTitle": title_of(paid_in) if paid_in else None,
                "ageChapters": age,
            }
        )
    return out


def foreshadow_report(project: VnProject) -> List[Dict[str, Any]]:
    """伏笔清单（含"埋了多久"）：给界面与硬锚块共用同一套算法。

    ageChapters = 埋点章 →（已回收：回收章｜未回收：当前最后一章）隔了几章。
    有了它才能说"这条埋了 25 章还没回收"——只记 open/paid 是说不出来的。
    """
    return _foreshadow_rows(get_ledger(project), list(project.chapters or []))


#: 硬锚块各段的**输出顺序**。刻意沿用原顺序：提示词里的位置本身有讲究
#: （Lost in the Middle，见 `docs/long-context-policy.md`），不该顺手改。
_HARD_ANCHOR_OUTPUT_ORDER = ("facts", "states", "foreshadows", "events")
#: 硬锚块各段的**保留优先级**（高 → 低），只在超预算时决定"先让谁"。
#: 未回收伏笔与角色状态排在最前：它们每行都很短，却是这个块存在的理由——
#: 「埋了很久没收的钩子」和「这个人是不是已经死了」都靠它们。章节事实摘要体积最大
#: （8 章 × 6 条事实 + 对白锚）且与章节摘要层部分重复，关键事件与事实摘要最冗余。
_HARD_ANCHOR_PRIORITY = ("foreshadows", "states", "facts", "events")
_HARD_ANCHOR_LABELS = {
    "foreshadows": "未回收伏笔",
    "states": "角色状态快照",
    "facts": "章节事实摘要",
    "events": "关键事件",
}
#: 给块尾那句"省了什么"留的位置（与 `global_memory.OMIT_NOTE_RESERVE` 同一套做法）。
_OMIT_NOTE_RESERVE = 96


def _build_ledger_sections(
    ledger: Dict[str, Any], chapters: Optional[List[Any]]
) -> Dict[str, List[str]]:
    """把账本渲染成"段名 → 行列表"，让 `format_ledger_for_agent` 能整段取舍。"""
    sections: Dict[str, List[str]] = {}

    facts = ledger.get("chapterFacts") or []
    if facts:
        lines = ["### 章节事实摘要"]
        for f in facts[-8:]:
            title = f.get("title") or f.get("chapterId") or "?"
            body = "；".join(str(x) for x in (f.get("facts") or [])[:6])
            q = " / ".join(str(x) for x in (f.get("keyQuotes") or [])[:2])
            lines.append(f"- [{title}] {body}" + (f"｜对白锚：{q}" if q else ""))
        sections["facts"] = lines

    states = ledger.get("characterStates") or []
    if states:
        lines = ["### 角色状态快照（最近）"]
        for s in states[-12:]:
            lines.append(
                f"- {s.get('characterName') or s.get('characterId')}@"
                f"{s.get('chapterTitle') or s.get('chapterId')}："
                f"情={s.get('emotion') or '—'}；身={s.get('body') or '—'}；"
                f"关系={s.get('relations') or '—'}"
            )
        sections["states"] = lines

    fores = [x for x in (ledger.get("foreshadows") or []) if x.get("status") != "paid"]
    if fores:
        # 带上"埋了几章还没回收"：只写"未回收"，模型不会觉得这事有时限；
        # 写上"埋了 12 章"，它才会在这一轮真的去收。
        ages = {
            str(f.get("id")): f.get("ageChapters")
            for f in _foreshadow_rows(ledger, chapters)
        }

        # 取**挂得最久**的 10 条，而不是最后追加的 10 条。`fores[-10:]` 拿到的是最近
        # 埋下的钩子，而"埋了 25 章还没收"的那条恰好排在队首、永远进不了提示词——
        # 与上面那句注释（写上"埋了 12 章"，它才会去收）的用意正好相反。
        # ageChapters 取不到时（没传 chapters）记 -1，稳定排序后会落到末尾，
        # 等价于回落到原来的追加顺序。
        def _hook_age(fo: Dict[str, Any]) -> int:
            age = ages.get(str(fo.get("id")))
            return age if isinstance(age, int) else -1

        lines = ["### 未回收伏笔"]
        for fo in sorted(fores, key=_hook_age, reverse=True)[:10]:
            age = ages.get(str(fo.get("id")))
            age_bit = f"，已埋 {age} 章未回收" if isinstance(age, int) and age >= 3 else ""
            lines.append(
                f"- [{fo.get('status') or 'open'}] {fo.get('hook') or fo.get('id')}"
                + (f"（植于 {fo.get('plantedChapter')}）" if fo.get("plantedChapter") else "")
                + age_bit
            )
        sections["foreshadows"] = lines

    events = ledger.get("events") or []
    if events:
        lines = ["### 关键事件"]
        for ev in events[-10:]:
            lines.append(f"- {ev.get('summary') or ev.get('id')}")
        sections["events"] = lines

    return sections


def format_ledger_for_agent(
    ledger: Dict[str, Any],
    *,
    limit: int = 2800,
    chapters: Optional[List[Any]] = None,
) -> str:
    """Hard-anchor block injected into write/check prompts.

    超预算时**整段让位**，并把省掉的段名写在块尾——不再从文本中间切一刀。
    原来的 `text[:limit-12]` 会把排在后面的整段静默吃掉，而"章节事实摘要"体积最大
    且排在最前，于是最先被吃掉的恰好是**未回收伏笔**：一个写到几十章的工程，
    实测硬锚块里根本没有伏笔那一节（新加的测试就是这么红出来的）。
    这与 `global_memory` 的口径一致（那边同样是"预算不够时不静默截断：
    未回收伏笔必须留着，省了哪几卷要写出来"），也与
    `docs/long-context-policy.md` 的"整块让位 + 写进提示词"同一条规矩。
    """
    head = "## 项目硬锚（写作账本·不得推翻已确认事实）"
    sections = _build_ledger_sections(ledger, chapters)
    if not sections:
        return ""

    # 1) 先按优先级决定哪些段留下（预算里给块尾那句说明留位置）
    budget = max(0, limit - _OMIT_NOTE_RESERVE)
    used = len(head)
    survivors: set[str] = set()
    omitted: List[str] = []
    for key in _HARD_ANCHOR_PRIORITY:
        lines = sections.get(key) or []
        if not lines:
            continue
        cost = sum(len(x) + 1 for x in lines)
        if used + cost <= budget:
            survivors.add(key)
            used += cost
        else:
            omitted.append(key)

    # 最高优先级那段都装不下时不能什么都不给：留住它，交给最后那道字符级保险。
    if not survivors:
        top = next(k for k in _HARD_ANCHOR_PRIORITY if sections.get(k))
        survivors.add(top)
        omitted = [k for k in _HARD_ANCHOR_PRIORITY if sections.get(k) and k != top]

    # 2) 再按原有顺序输出（只有"谁留下"变了，"谁在前"没变）
    parts: List[str] = [head]
    for key in _HARD_ANCHOR_OUTPUT_ORDER:
        if key in survivors:
            parts.extend(sections[key])

    if omitted:
        names = [_HARD_ANCHOR_LABELS[k] for k in _HARD_ANCHOR_PRIORITY if k in omitted]
        parts.append(f"…（篇幅不足，已省去：{'、'.join(names)}）")

    text = "\n".join(parts)
    if len(text) > limit:
        text = text[: limit - 12] + "\n…(截断)"
    return text


def digest_chapter_into_ledger(
    project: VnProject,
    chapter_id: str,
    *,
    llm_facts: Optional[List[str]] = None,
    llm_states: Optional[List[Dict[str, Any]]] = None,
    llm_foreshadows: Optional[List[Dict[str, Any]]] = None,
) -> Dict[str, Any]:
    """Update ledger from chapter content (+ optional LLM enrichments)."""
    ch = next((c for c in project.chapters if c.id == chapter_id), None)
    if not ch:
        raise ValueError("章节不存在")
    dig = make_chapter_digest(ch, project.characters)
    # 账本记的是"这一章发生了什么"：走唯一口径（正文优先），只读 blocks 的话
    # 用正文档写作的章会进账本为空（伏笔/事实层跟着失忆）。
    plain = chapter_plain(ch, project.characters)
    ledger = get_ledger(project)

    facts = list(llm_facts or [])
    if not facts:
        if dig.beatSummary:
            facts.append(dig.beatSummary)
        speakers_for_facts = list(dig.speakers)
        if not speakers_for_facts:
            speakers_for_facts = _speakers_from_plain(plain, project.characters)
        if speakers_for_facts:
            facts.append("出场：" + "、".join(speakers_for_facts[:8]))
        if dig.openHook:
            facts.append(f"开场钩：{dig.openHook[:80]}")
        if dig.closeHook:
            facts.append(f"收束钩：{dig.closeHook[:80]}")
        # extractive quote anchors
    quotes: List[str] = []
    for line in plain.splitlines():
        if ":" in line or "：" in line:
            frag = line.strip()
            if 6 <= len(frag) <= 60:
                quotes.append(frag)
        if len(quotes) >= 4:
            break

    # replace existing fact row for chapter
    evicted: Dict[str, int] = {}
    chapter_facts = [
        f for f in ledger["chapterFacts"] if f.get("chapterId") != chapter_id
    ]
    chapter_facts.append(
        {
            "id": str(uuid4()),
            "chapterId": chapter_id,
            "title": ch.title,
            "facts": facts[:12],
            "keyQuotes": quotes[:4],
            "updatedAt": _now(),
        }
    )
    # 章节事实是"最近这段的逐章事实"，尾部窗口本身是对的（远期由 global_memory
    # 的卷级总述覆盖）；但丢了多少条要说出来，否则作者会以为账本记得全书。
    if len(chapter_facts) > _MAX_CHAPTER_FACTS:
        evicted["chapterFacts"] = len(chapter_facts) - _MAX_CHAPTER_FACTS
    ledger["chapterFacts"] = chapter_facts[-_MAX_CHAPTER_FACTS:]

    # character states
    states = [
        s
        for s in ledger["characterStates"]
        if not (s.get("chapterId") == chapter_id)
    ]
    if llm_states:
        for s in llm_states:
            states.append(
                {
                    "id": str(uuid4()),
                    "chapterId": chapter_id,
                    "chapterTitle": ch.title,
                    "characterId": s.get("characterId") or "",
                    "characterName": s.get("characterName") or "",
                    "emotion": s.get("emotion") or "",
                    "body": s.get("body") or "",
                    "relations": s.get("relations") or "",
                    "updatedAt": _now(),
                }
            )
    else:
        # Heuristic emotion/body from last lines spoken by each character
        speaker_names = list(dig.speakers) or _speakers_from_plain(
            plain, project.characters
        )
        for name in speaker_names[:6]:
            char = next(
                (
                    c
                    for c in project.characters
                    if c.displayName == name or c.defineName == name
                ),
                None,
            )
            emotion, body = _infer_speaker_state(plain, name)
            states.append(
                {
                    "id": str(uuid4()),
                    "chapterId": chapter_id,
                    "chapterTitle": ch.title,
                    "characterId": char.id if char else "",
                    "characterName": name,
                    "emotion": emotion,
                    "body": body,
                    "relations": (
                        char.relationships[:80]
                        if char and char.relationships
                        else "—"
                    ),
                    "updatedAt": _now(),
                }
            )
    kept_states, states_evicted = _retain_character_states(states)
    evicted.update(states_evicted)
    ledger["characterStates"] = kept_states

    # foreshadows from close/open hooks
    fores = list(ledger.get("foreshadows") or [])
    if llm_foreshadows:
        for fo in llm_foreshadows:
            hook = str(fo.get("hook") or "").strip()
            status = str(fo.get("status") or "open")
            note = str(fo.get("note") or "")
            # 同一个钩子只留一条：模型可能把"这一章把它回收了"当成新发现报上来，
            # 直接 append 会让同一个伏笔在账本里出现两遍（一条 open、一条 paid）。
            existing = next(
                (f for f in fores if str(f.get("hook") or "").strip() == hook and hook), None
            )
            if existing is not None:
                existing["status"] = status
                if note:
                    existing["note"] = note
                # 回收记在**哪一章**：没有这个字段，就永远说不出"埋了多久才收"，
                # 也算不出"埋了 25 章还没回收"。
                if status == "paid" and not existing.get("paidInChapter"):
                    existing["paidInChapter"] = chapter_id
                existing["updatedAt"] = _now()
                continue
            fores.append(
                {
                    "id": str(uuid4()),
                    "hook": hook,
                    "plantedChapter": chapter_id,
                    "status": status,
                    "note": note,
                    "paidInChapter": chapter_id if status == "paid" else None,
                    "updatedAt": _now(),
                }
            )
    elif dig.closeHook and _hook_has_prose(dig.closeHook):
        # avoid dup by hook text
        if not any(f.get("hook") == dig.closeHook for f in fores):
            fores.append(
                {
                    "id": str(uuid4()),
                    "hook": dig.closeHook[:120],
                    "plantedChapter": chapter_id,
                    "status": "open",
                    "note": "章末钩子（自动）",
                    "updatedAt": _now(),
                }
            )
    # 未回收优先于已回收（见 `_retain_foreshadows`：尾部截断丢掉的恰是最早埋的那条）。
    kept_fores, fores_evicted = _retain_foreshadows(fores)
    evicted.update(fores_evicted)
    ledger["foreshadows"] = kept_fores

    # event（幂等：同一章只保留一条，重复保存不会把 events 灌满）
    events = [e for e in (ledger.get("events") or []) if e.get("chapterId") != chapter_id]
    events.append(
        {
            "id": str(uuid4()),
            "chapterId": chapter_id,
            "summary": dig.beatSummary or f"完成章节「{ch.title}」摘要入库",
            "updatedAt": _now(),
        }
    )
    if len(events) > _MAX_EVENTS:
        evicted["events"] = len(events) - _MAX_EVENTS
    ledger["events"] = events[-_MAX_EVENTS:]
    ledger["retention"] = _retention_record(ledger, evicted)
    ledger["updatedAt"] = _now()
    return ledger


# 单次保存最多为多少章做入库，以及正文总量预算（防止导入几十章时拖慢保存）
AUTO_DIGEST_MAX_CHAPTERS = 20
AUTO_DIGEST_MAX_CHARS = 400_000


def _stamp_fact_hash(ledger: Dict[str, Any], chapter_id: str, content_hash: str) -> None:
    for row in ledger.get("chapterFacts") or []:
        if row.get("chapterId") == chapter_id:
            row["sourceHash"] = content_hash
            return


def auto_digest_ledger(project: VnProject, *, max_chapters: int = AUTO_DIGEST_MAX_CHAPTERS,
                       max_chars: int = AUTO_DIGEST_MAX_CHARS) -> VnProject:
    """保存时自动把"有改动/还没入库"的章节写进账本（纯本地，不调模型）。

    设计要点：
    - **增量**：用 ``chapter_content_hash`` 与账本里记录的 ``sourceHash`` 比对，
      内容没变的章节直接跳过，所以重复保存几乎零成本；
    - **幂等**：章节事实 / 角色状态 / 事件按 chapterId 覆盖，不会越存越多；
    - **会清理**：章节被删掉后，指向它的锚点（事实/状态/伏笔/事件）一起清掉，
      避免生成时读到已经不存在的章节；
    - **有预算**：一次保存最多处理 max_chapters 章、max_chars 字正文，超出的留到
      下次保存继续（状态仍是"待入库"，不会丢）；
    - **不抛异常**：任何意外都返回原项目 —— 记账失败绝不能连带保存失败。
    """
    try:
        chapters = list(project.chapters or [])
        if not chapters:
            return project
        live_ids = {c.id for c in chapters}
        ledger = get_ledger(project)

        # 1) 清理已被删除章节的锚点
        pruned = False
        for key, field in (
            ("chapterFacts", "chapterId"),
            ("characterStates", "chapterId"),
            ("foreshadows", "plantedChapter"),
            ("events", "chapterId"),
        ):
            rows = list(ledger.get(key) or [])
            kept = [r for r in rows if not r.get(field) or r.get(field) in live_ids]
            if len(kept) != len(rows):
                ledger[key] = kept
                pruned = True

        # 2) 找出内容变了或还没入库的章节（按叙事顺序处理）
        known = {
            r.get("chapterId"): r.get("sourceHash")
            for r in (ledger.get("chapterFacts") or [])
        }
        pending: List[Tuple[str, str, int]] = []
        for ch in chapters:
            h = chapter_content_hash(ch)
            if known.get(ch.id) == h:
                continue
            plain_len = len(chapter_plain(ch, project.characters) or "")
            pending.append((ch.id, h, plain_len))

        if not pending and not pruned:
            return project

        cur = set_ledger(project, ledger) if pruned else project
        budget = max_chars
        done = 0
        for chapter_id, content_hash, plain_len in pending:
            if done >= max_chapters or budget <= 0:
                break
            ledger = digest_chapter_into_ledger(cur, chapter_id)
            _stamp_fact_hash(ledger, chapter_id, content_hash)
            cur = set_ledger(cur, ledger)
            budget -= plain_len
            done += 1
        return cur
    except Exception:  # noqa: BLE001 —— 记账是附带能力，绝不能把保存搞挂
        return project
