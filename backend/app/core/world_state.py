"""Structured WorldState — atomic facts with validity intervals + provenance.

Replaces the "natural-language ledger as truth" path for consistency checks.
Legacy ``writingLedger`` fields (chapterFacts / characterStates / …) remain for
UI and soft recall; ``worldState`` inside the same blob is the machine-checkable
source of truth (FactTrack-style intervals + SEEM provenance pointers).

Storage: nested under ``writingLedger.worldState`` (JSONB on the project).
No separate graph DB / CLIPS — keep it in-process and auditable.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Tuple
from uuid import uuid4

# --------------------------------------------------------------------------- schema

WORLD_STATE_SCHEMA_VERSION = 1

#: Relations we treat as single-valued (new value supersedes old; overlapping
#: intervals with conflicting values → contradiction).
SINGLE_VALUED_RELATIONS = frozenset(
    {
        "status",  # alive / dead / absent / …
        "location",
        "alive",
        "dead",
    }
)

#: Body/emotion blobs that imply "not present / dead" for status projection.
_DEAD_MARKERS = ("死", "身亡", "已故", "阵亡", "遇害", "牺牲", "去世", "毙命", "亡故", "永眠")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def empty_world_state() -> Dict[str, Any]:
    return {
        "schemaVersion": WORLD_STATE_SCHEMA_VERSION,
        "facts": [],
        "eventFrames": [],
        "version": 0,
        "updatedAt": _now(),
    }


def get_world_state(ledger_or_project: Any) -> Dict[str, Any]:
    """Read WorldState from a ledger dict or a VnProject."""
    raw: Any = None
    if isinstance(ledger_or_project, dict):
        raw = ledger_or_project.get("worldState")
        if raw is None and "facts" in ledger_or_project and "schemaVersion" in ledger_or_project:
            raw = ledger_or_project
    else:
        ledger = getattr(ledger_or_project, "writingLedger", None)
        if isinstance(ledger, dict):
            raw = ledger.get("worldState")
    if not isinstance(raw, dict):
        return empty_world_state()
    return {
        "schemaVersion": int(raw.get("schemaVersion") or WORLD_STATE_SCHEMA_VERSION),
        "facts": list(raw.get("facts") or []),
        "eventFrames": list(raw.get("eventFrames") or []),
        "version": int(raw.get("version") or 0),
        "updatedAt": raw.get("updatedAt") or _now(),
    }


def set_world_state_on_ledger(
    ledger: Dict[str, Any], world: Dict[str, Any]
) -> Dict[str, Any]:
    out = dict(ledger)
    world = {
        **empty_world_state(),
        **world,
        "updatedAt": _now(),
        "version": int(world.get("version") or 0) + 1,
    }
    out["worldState"] = world
    return out


def make_fact(
    *,
    subject: str,
    relation: str,
    value: str,
    chapter_id: str,
    chapter_index: int = 0,
    quote: str = "",
    polarity: str = "assert",
    confidence: float = 0.85,
    category: str = "factual",
    valid_to: Optional[int] = None,
    fact_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Build one atomic fact with a half-open validity interval on chapter index."""
    return {
        "id": fact_id or str(uuid4()),
        "subject": (subject or "").strip(),
        "relation": (relation or "").strip(),
        "value": (value or "").strip(),
        "polarity": polarity if polarity in ("assert", "negate") else "assert",
        "validFrom": int(chapter_index),
        "validTo": valid_to,  # None = still open
        "confidence": float(confidence),
        "category": category,
        "source": {
            "chapterId": chapter_id,
            "quote": (quote or "")[:160],
        },
        "updatedAt": _now(),
    }


def make_event_frame(
    *,
    chapter_id: str,
    summary: str,
    participants: Optional[Sequence[str]] = None,
    preconditions: Optional[Sequence[str]] = None,
    postconditions: Optional[Sequence[str]] = None,
    frame_id: Optional[str] = None,
) -> Dict[str, Any]:
    return {
        "id": frame_id or str(uuid4()),
        "chapterId": chapter_id,
        "summary": (summary or "")[:200],
        "participants": [str(p) for p in (participants or []) if str(p).strip()][:12],
        "preconditions": [str(x) for x in (preconditions or []) if str(x).strip()][:8],
        "postconditions": [str(x) for x in (postconditions or []) if str(x).strip()][:8],
        "updatedAt": _now(),
    }


def chapter_index_map(chapters: Sequence[Any]) -> Dict[str, int]:
    return {
        str(getattr(c, "id", "") or ""): i
        for i, c in enumerate(chapters or [])
        if getattr(c, "id", None)
    }


def fact_active_at(fact: Dict[str, Any], chapter_index: int) -> bool:
    """Half-open [validFrom, validTo): validTo None means open-ended."""
    start = int(fact.get("validFrom") or 0)
    end = fact.get("validTo")
    if chapter_index < start:
        return False
    if end is None:
        return True
    return chapter_index < int(end)


def active_facts(
    world: Dict[str, Any],
    *,
    at_index: int,
    subject: Optional[str] = None,
    relation: Optional[str] = None,
) -> List[Dict[str, Any]]:
    out: List[Dict[str, Any]] = []
    for f in world.get("facts") or []:
        if not isinstance(f, dict):
            continue
        if not fact_active_at(f, at_index):
            continue
        if subject and str(f.get("subject") or "") != subject:
            continue
        if relation and str(f.get("relation") or "") != relation:
            continue
        out.append(f)
    return out


def project_character_status(
    world: Dict[str, Any], *, at_index: int
) -> Dict[str, str]:
    """Latest status value per character at chapter index (dead/alive/…)."""
    latest: Dict[str, Tuple[int, str]] = {}
    for f in active_facts(world, at_index=at_index, relation="status"):
        subj = str(f.get("subject") or "").strip()
        if not subj:
            continue
        val = str(f.get("value") or "").strip().lower()
        if not val:
            continue
        vf = int(f.get("validFrom") or 0)
        prev = latest.get(subj)
        if prev is None or vf >= prev[0]:
            latest[subj] = (vf, val)
    return {k: v for k, v in ((n, t[1]) for n, t in latest.items())}


def looks_dead_value(value: str) -> bool:
    v = (value or "").strip().lower()
    if v in ("dead", "deceased", "gone", "absent", "已故", "死亡", "不在场"):
        return True
    return any(m in (value or "") for m in _DEAD_MARKERS)


def close_open_facts(
    facts: List[Dict[str, Any]],
    *,
    subject: str,
    relation: str,
    close_at: int,
) -> List[Dict[str, Any]]:
    """Close open intervals for a single-valued (subject, relation) before ``close_at``."""
    out: List[Dict[str, Any]] = []
    for f in facts:
        if (
            str(f.get("subject") or "") == subject
            and str(f.get("relation") or "") == relation
            and f.get("validTo") is None
            and int(f.get("validFrom") or 0) < close_at
        ):
            nf = dict(f)
            nf["validTo"] = close_at
            nf["updatedAt"] = _now()
            out.append(nf)
        else:
            out.append(f)
    return out


def upsert_facts(
    world: Dict[str, Any],
    new_facts: Sequence[Dict[str, Any]],
    *,
    replace_chapter_id: Optional[str] = None,
) -> Dict[str, Any]:
    """Merge facts; optionally drop prior facts sourced from the same chapter first."""
    facts = list(world.get("facts") or [])
    if replace_chapter_id:
        facts = [
            f
            for f in facts
            if str((f.get("source") or {}).get("chapterId") or "") != replace_chapter_id
        ]
    for nf in new_facts:
        if not isinstance(nf, dict):
            continue
        subj = str(nf.get("subject") or "").strip()
        rel = str(nf.get("relation") or "").strip()
        if not subj or not rel:
            continue
        vf = int(nf.get("validFrom") or 0)
        if rel in SINGLE_VALUED_RELATIONS:
            facts = close_open_facts(facts, subject=subj, relation=rel, close_at=vf)
        facts.append(nf)
    world = dict(world)
    world["facts"] = facts
    return world


def upsert_event_frame(
    world: Dict[str, Any], frame: Dict[str, Any]
) -> Dict[str, Any]:
    frames = [
        f
        for f in (world.get("eventFrames") or [])
        if str(f.get("chapterId") or "") != str(frame.get("chapterId") or "")
    ]
    frames.append(frame)
    # Cap frames by recency (keep last 80)
    if len(frames) > 80:
        frames = frames[-80:]
    world = dict(world)
    world["eventFrames"] = frames
    return world


# --------------------------------------------------------------------------- constraint block for prompts

_CONSTRAINT_BUDGET_DEFAULT = 2200
_OMIT_RESERVE = 64


def format_world_constraints(
    world: Dict[str, Any],
    *,
    chapters: Optional[Sequence[Any]] = None,
    focus_chapter_id: Optional[str] = None,
    foreshadows: Optional[Sequence[Dict[str, Any]]] = None,
    limit: int = _CONSTRAINT_BUDGET_DEFAULT,
) -> str:
    """Structured hard constraints for the writer — preferred over prose chunks.

    Soft retrieval (hybrid/pgvector) must never be mixed into this block.
    """
    order = chapter_index_map(chapters or [])
    focus_idx = order.get(str(focus_chapter_id or ""), max(order.values()) if order else 0)
    # Use "as of next chapter" so current-chapter facts are active
    at = focus_idx if focus_chapter_id else (max(order.values()) if order else 0)

    head = "## 世界状态约束（硬锚·不得推翻；软检索不得覆盖）"
    lines: List[str] = [head]

    statuses = project_character_status(world, at_index=at)
    dead = [n for n, v in statuses.items() if looks_dead_value(v)]
    alive_like = [n for n, v in statuses.items() if not looks_dead_value(v)]
    if dead or alive_like:
        lines.append("### 角色当前状态")
        for n in dead[:20]:
            lines.append(f"- {n}: 已故/不在场（status={statuses[n]}）")
        for n in alive_like[:12]:
            lines.append(f"- {n}: {statuses[n]}")

    # Open-ended non-status facts (location, attributes) — compact
    other: List[str] = []
    for f in active_facts(world, at_index=at):
        rel = str(f.get("relation") or "")
        if rel == "status":
            continue
        subj = str(f.get("subject") or "")
        val = str(f.get("value") or "")
        if not subj or not val:
            continue
        other.append(f"- {subj}.{rel} = {val}")
    if other:
        lines.append("### 有效事实")
        lines.extend(other[:24])

    fores = [x for x in (foreshadows or []) if str(x.get("status") or "open") != "paid"]
    if fores:
        lines.append("### 未回收伏笔（须留意）")

        def _age(fo: Dict[str, Any]) -> int:
            a = fo.get("ageChapters")
            return int(a) if isinstance(a, int) else -1

        for fo in sorted(fores, key=_age, reverse=True)[:10]:
            age = fo.get("ageChapters")
            age_bit = (
                f"，已埋 {age} 章"
                if isinstance(age, int) and age >= 3
                else ""
            )
            lines.append(
                f"- {fo.get('hook') or fo.get('id')}"
                + (f"（植于 {fo.get('plantedChapter')}）" if fo.get("plantedChapter") else "")
                + age_bit
            )

    frames = list(world.get("eventFrames") or [])[-6:]
    if frames:
        lines.append("### 近期事件帧")
        for fr in frames:
            parts = fr.get("participants") or []
            who = "、".join(str(p) for p in parts[:4])
            bit = f"（{who}）" if who else ""
            lines.append(f"- {fr.get('summary') or fr.get('chapterId')}{bit}")

    if len(lines) <= 1:
        return ""

    text = "\n".join(lines)
    if len(text) > limit:
        text = text[: limit - _OMIT_RESERVE].rstrip() + "\n…（世界状态约束已截断）"
    return text


def format_hard_anchors(
    ledger: Dict[str, Any],
    *,
    chapters: Optional[Sequence[Any]] = None,
    focus_chapter_id: Optional[str] = None,
    limit: int = 2800,
    graded: bool = False,
) -> str:
    """Preferred injection: WorldState constraints first, then legacy ledger soft summary.

    Soft chapter-fact prose is demoted when WorldState has content, so the model
    sees checkable constraints before narrative digests.
    """
    from app.core.pipeline.ledger import format_ledger_for_agent

    world = get_world_state(ledger)
    # Foreshadows stay in the legacy ledger block (keeps ### 未回收伏笔 section
    # order invariant for Lost-in-the-Middle). Constraints carry status / facts /
    # event frames only.
    constraints = format_world_constraints(
        world,
        chapters=chapters,
        focus_chapter_id=focus_chapter_id,
        foreshadows=None,
        limit=min(limit, 2200),
    )
    # Leave room for a slim legacy block when constraints are present
    remaining = max(400, limit - len(constraints) - 8) if constraints else limit
    # prefer_world_state=False avoids recursion back into this helper.
    legacy = format_ledger_for_agent(
        ledger,
        limit=remaining,
        chapters=list(chapters) if chapters is not None else None,
        focus_chapter_id=focus_chapter_id,
        graded=graded,
        prefer_world_state=False,
    )
    if constraints and legacy:
        return f"{constraints}\n\n{legacy}"
    return constraints or legacy
