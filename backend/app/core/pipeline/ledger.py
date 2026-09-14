"""Project writing ledger — hard anchors for memory-aware generation.

两条写入路径：

1. ``digest_chapter_into_ledger`` —— 单章入库（手工端点 / 流水线 gate 用，可带 LLM 增强）；
2. ``auto_digest_ledger`` —— **保存时自动**跑，纯本地、按章节内容指纹增量更新。
   线上实测：需要用户主动下命令的能力（含账本）几乎没人用，而"保存时自动刷新"的
   章节摘要 159/159 全覆盖 —— 所以账本也走自动这条线（见 README/roadmap 讨论）。
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple
from uuid import uuid4

from app.core.agent_context import _blocks_to_plain
from app.core.chapter_digest import chapter_content_hash, make_chapter_digest
from app.domain.types import VnProject


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
    ledger["events"] = events[-50:]
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
            plain_len = len(_blocks_to_plain(ch.blocks, project.characters) or "")
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
