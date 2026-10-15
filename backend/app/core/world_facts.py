"""Incremental atomic-fact extraction into WorldState (local heuristics, no LLM).

Runs after chapter digest. Deterministic so it can sit on the save path and in CI.
LLM enrichment can later append facts with lower confidence; A-layer checks rely
on status / death / location relations produced here.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence

from app.core.agent_context import chapter_plain
from app.core.chapter_digest import make_chapter_digest
from app.core.world_state import (
    get_world_state,
    make_event_frame,
    make_fact,
    project_character_status,
    set_world_state_on_ledger,
    upsert_event_frame,
    upsert_facts,
)
from app.domain.types import VnProject

_DEAD_RE = re.compile(r"死|身亡|已故|阵亡|遇害|牺牲|去世|毙命|亡故|永眠")
_LOC_GONE_RE = re.compile(r"已毁|废弃|不存在|倒塌|焚毁|封死|禁止进入")


def _chapter_index(project: VnProject, chapter_id: str) -> int:
    for i, ch in enumerate(project.chapters or []):
        if str(getattr(ch, "id", "") or "") == chapter_id:
            return i
    return 0


def extract_facts_from_chapter(
    project: VnProject,
    chapter_id: str,
    *,
    ledger_states: Optional[Sequence[Dict[str, Any]]] = None,
) -> List[Dict[str, Any]]:
    """Heuristic atomic facts for one chapter (idempotent when re-digested)."""
    ch = next((c for c in (project.chapters or []) if c.id == chapter_id), None)
    if ch is None:
        return []
    idx = _chapter_index(project, chapter_id)
    dig = make_chapter_digest(ch, project.characters)
    plain = chapter_plain(ch, project.characters) or ""
    facts: List[Dict[str, Any]] = []

    # Speakers → present / status=alive (unless body already says dead)
    speakers = list(dig.speakers or [])
    dead_from_states: Dict[str, str] = {}
    for s in ledger_states or []:
        if not isinstance(s, dict):
            continue
        if str(s.get("chapterId") or "") != chapter_id:
            continue
        name = str(s.get("characterName") or "").strip()
        if not name:
            continue
        blob = " ".join(
            str(s.get(k) or "") for k in ("body", "emotion", "relations")
        )
        if _DEAD_RE.search(blob):
            dead_from_states[name] = blob[:80]

    for name in speakers[:12]:
        if name in dead_from_states:
            continue
        facts.append(
            make_fact(
                subject=name,
                relation="status",
                value="alive",
                chapter_id=chapter_id,
                chapter_index=idx,
                quote=f"{name} 出场",
                confidence=0.7,
                category="characterization",
            )
        )

    for name, quote in dead_from_states.items():
        facts.append(
            make_fact(
                subject=name,
                relation="status",
                value="dead",
                chapter_id=chapter_id,
                chapter_index=idx,
                quote=quote,
                confidence=0.92,
                category="characterization",
            )
        )

    # Plain-text death mentions next to known character names (cheap signal)
    for c in project.characters or []:
        name = str(getattr(c, "displayName", None) or getattr(c, "defineName", None) or "")
        if len(name) < 2 or name not in plain:
            continue
        # Look for "X死了" / "X身亡" within a short window
        for m in re.finditer(re.escape(name) + r".{0,12}(?:" + _DEAD_RE.pattern + r")", plain):
            facts.append(
                make_fact(
                    subject=name,
                    relation="status",
                    value="dead",
                    chapter_id=chapter_id,
                    chapter_index=idx,
                    quote=m.group(0)[:80],
                    confidence=0.8,
                    category="characterization",
                )
            )
            break

    # Location gone flags from setting cards → world rule facts
    for loc in project.locations or []:
        name = str(getattr(loc, "name", "") or "").strip()
        if len(name) < 2:
            continue
        blob = " ".join(
            [
                str(getattr(loc, "description", "") or ""),
                " ".join(str(t) for t in (getattr(loc, "tags", None) or [])),
            ]
        )
        if not _LOC_GONE_RE.search(blob):
            continue
        facts.append(
            make_fact(
                subject=name,
                relation="status",
                value="gone",
                chapter_id=chapter_id,
                chapter_index=idx,
                quote=blob[:80],
                confidence=0.9,
                category="world_building",
            )
        )

    return facts


def extract_event_frame(
    project: VnProject, chapter_id: str
) -> Optional[Dict[str, Any]]:
    ch = next((c for c in (project.chapters or []) if c.id == chapter_id), None)
    if ch is None:
        return None
    dig = make_chapter_digest(ch, project.characters)
    summary = dig.beatSummary or f"章节「{ch.title}」"
    participants = list(dig.speakers or [])[:8]
    posts: List[str] = []
    if dig.closeHook:
        posts.append(f"closeHook:{dig.closeHook[:60]}")
    return make_event_frame(
        chapter_id=chapter_id,
        summary=summary,
        participants=participants,
        postconditions=posts,
    )


def sync_world_state_after_digest(
    project: VnProject,
    ledger: Dict[str, Any],
    chapter_id: str,
) -> Dict[str, Any]:
    """Update ledger['worldState'] from the chapter just digested.

    Idempotent per chapter: replaces facts previously sourced from this chapter.
    """
    world = get_world_state(ledger)
    # Prefer states already written into this digest pass
    states = [
        s
        for s in (ledger.get("characterStates") or [])
        if str(s.get("chapterId") or "") == chapter_id
    ]
    new_facts = extract_facts_from_chapter(
        project, chapter_id, ledger_states=states
    )
    world = upsert_facts(world, new_facts, replace_chapter_id=chapter_id)
    frame = extract_event_frame(project, chapter_id)
    if frame is not None:
        world = upsert_event_frame(world, frame)
    return set_world_state_on_ledger(ledger, world)


def dead_characters_at(
    ledger_or_project: Any, *, chapter_index: int
) -> List[str]:
    world = get_world_state(ledger_or_project)
    statuses = project_character_status(world, at_index=chapter_index)
    from app.core.world_state import looks_dead_value

    return [n for n, v in statuses.items() if looks_dead_value(v)]
