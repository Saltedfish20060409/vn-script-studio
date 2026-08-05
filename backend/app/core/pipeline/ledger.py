"""Project writing ledger — hard anchors for memory-aware generation."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from app.core.agent_context import _blocks_to_plain
from app.core.chapter_digest import make_chapter_digest
from app.domain.types import VnProject


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def empty_ledger() -> Dict[str, Any]:
    return {
        "chapterFacts": [],
        "characterStates": [],
        "foreshadows": [],
        "events": [],
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
            "updatedAt": raw.get("updatedAt") or _now(),
        }
    return empty_ledger()


def set_ledger(project: VnProject, ledger: Dict[str, Any]) -> VnProject:
    data = project.model_dump()
    ledger = {**ledger, "updatedAt": _now()}
    data["writingLedger"] = ledger
    return VnProject.model_validate(data)


def format_ledger_for_agent(ledger: Dict[str, Any], *, limit: int = 2800) -> str:
    """Hard-anchor block injected into write/check prompts."""
    parts: List[str] = ["## 项目硬锚（写作账本·不得推翻已确认事实）"]
    facts = ledger.get("chapterFacts") or []
    if facts:
        parts.append("### 章节事实摘要")
        for f in facts[-8:]:
            title = f.get("title") or f.get("chapterId") or "?"
            lines = f.get("facts") or []
            quote = f.get("keyQuotes") or []
            body = "；".join(str(x) for x in lines[:6])
            q = " / ".join(str(x) for x in quote[:2])
            parts.append(f"- [{title}] {body}" + (f"｜对白锚：{q}" if q else ""))
    states = ledger.get("characterStates") or []
    if states:
        parts.append("### 角色状态快照（最近）")
        for s in states[-12:]:
            parts.append(
                f"- {s.get('characterName') or s.get('characterId')}@"
                f"{s.get('chapterTitle') or s.get('chapterId')}："
                f"情={s.get('emotion') or '—'}；身={s.get('body') or '—'}；"
                f"关系={s.get('relations') or '—'}"
            )
    fores = [x for x in (ledger.get("foreshadows") or []) if x.get("status") != "paid"]
    if fores:
        parts.append("### 未回收伏笔")
        for fo in fores[-10:]:
            parts.append(
                f"- [{fo.get('status') or 'open'}] {fo.get('hook') or fo.get('id')}"
                + (f"（植于 {fo.get('plantedChapter')}）" if fo.get("plantedChapter") else "")
            )
    events = ledger.get("events") or []
    if events:
        parts.append("### 关键事件")
        for ev in events[-10:]:
            parts.append(f"- {ev.get('summary') or ev.get('id')}")
    text = "\n".join(parts)
    if len(text) > limit:
        return text[: limit - 12] + "\n…(截断)"
    return text if len(parts) > 1 else ""


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
    plain = _blocks_to_plain(ch.blocks, project.characters)
    ledger = get_ledger(project)

    facts = list(llm_facts or [])
    if not facts:
        if dig.beatSummary:
            facts.append(dig.beatSummary)
        if dig.speakers:
            facts.append("出场：" + "、".join(dig.speakers[:8]))
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
    ledger["chapterFacts"] = chapter_facts[-40:]

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
        for name in dig.speakers[:6]:
            char = next(
                (c for c in project.characters if c.displayName == name or c.defineName == name),
                None,
            )
            states.append(
                {
                    "id": str(uuid4()),
                    "chapterId": chapter_id,
                    "chapterTitle": ch.title,
                    "characterId": char.id if char else "",
                    "characterName": name,
                    "emotion": "（待流水线充实）",
                    "body": "—",
                    "relations": (char.relationships[:80] if char and char.relationships else "—"),
                    "updatedAt": _now(),
                }
            )
    ledger["characterStates"] = states[-60:]

    # foreshadows from close/open hooks
    fores = list(ledger.get("foreshadows") or [])
    if llm_foreshadows:
        for fo in llm_foreshadows:
            fores.append(
                {
                    "id": str(uuid4()),
                    "hook": fo.get("hook") or "",
                    "plantedChapter": chapter_id,
                    "status": fo.get("status") or "open",
                    "note": fo.get("note") or "",
                    "updatedAt": _now(),
                }
            )
    elif dig.closeHook and len(dig.closeHook) > 4:
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
    ledger["foreshadows"] = fores[-40:]

    # event
    events = list(ledger.get("events") or [])
    events.append(
        {
            "id": str(uuid4()),
            "chapterId": chapter_id,
            "summary": dig.beatSummary or f"完成章节「{ch.title}」摘要入库",
            "updatedAt": _now(),
        }
    )
    ledger["events"] = events[-50:]
    ledger["updatedAt"] = _now()
    return ledger
