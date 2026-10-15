"""ConsistencyHarness — independent of the writer model.

Layers (plan):
- A: deterministic (WorldState status vs draft presence; gone locations)
- B: proposed-fact delta vs active WorldState intervals (FactTrack-style)
- C: optional LLM judge (not invoked here; callers may pass proposed semantic
  issues separately). This module stays local / CI-safe.

Issues always carry ``code`` + evidence quote + chapterIds for audit registry.
"""

from __future__ import annotations

import re
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Sequence

from app.core.pipeline.ledger import get_ledger
from app.core.world_state import (
    SINGLE_VALUED_RELATIONS,
    active_facts,
    chapter_index_map,
    get_world_state,
    looks_dead_value,
    project_character_status,
)
from app.domain.types import VnProject

# ConStory-inspired coarse categories (for messaging / eval bucketing)
_CATEGORY_FOR_CODE = {
    "ws_dead_character": "characterization",
    "ws_status_conflict": "factual",
    "ws_gone_location": "world_building",
    "ws_fact_interval_clash": "timeline",
}


@dataclass
class WorldConflict:
    code: str
    severity: str  # error | warn
    message: str
    subject: str = ""
    quote: str = ""
    chapterIds: List[str] = field(default_factory=list)
    category: str = "factual"
    #: legal_extension = new info that does not violate; violation = hard conflict
    kind: str = "violation"

    def as_dict(self) -> Dict[str, Any]:
        return {
            "code": self.code,
            "severity": self.severity,
            "message": self.message,
            "subject": self.subject,
            "quote": self.quote,
            "chapterIds": list(self.chapterIds),
            "category": self.category,
            "kind": self.kind,
        }


@dataclass
class ConsistencyHarnessReport:
    conflicts: List[WorldConflict] = field(default_factory=list)
    proposedFacts: List[Dict[str, Any]] = field(default_factory=list)
    blocking: bool = False

    def as_meta(self) -> Dict[str, Any]:
        return {
            "blocking": self.blocking,
            "conflictCount": len(self.conflicts),
            "conflicts": [c.as_dict() for c in self.conflicts[:20]],
            "proposedFactCount": len(self.proposedFacts),
        }


def _facts_conflict(a: Dict[str, Any], b: Dict[str, Any]) -> bool:
    """Two facts about the same subject/relation conflict if values disagree
    and intervals overlap (FactTrack interval collision idea)."""
    if str(a.get("subject") or "") != str(b.get("subject") or ""):
        return False
    if str(a.get("relation") or "") != str(b.get("relation") or ""):
        return False
    rel = str(a.get("relation") or "")
    if rel not in SINGLE_VALUED_RELATIONS:
        return False
    va = str(a.get("value") or "").strip().lower()
    vb = str(b.get("value") or "").strip().lower()
    if not va or not vb or va == vb:
        return False
    # dead vs alive always conflict
    if looks_dead_value(va) != looks_dead_value(vb) and (
        looks_dead_value(va) or looks_dead_value(vb)
    ):
        pass  # conflict
    elif va == vb:
        return False
    # Interval overlap: [aFrom, aTo) ∩ [bFrom, bTo)
    a0, b0 = int(a.get("validFrom") or 0), int(b.get("validFrom") or 0)
    a1 = a.get("validTo")
    b1 = b.get("validTo")
    a_end = int(a1) if a1 is not None else 10**9
    b_end = int(b1) if b1 is not None else 10**9
    return a0 < b_end and b0 < a_end


def propose_facts_from_draft(
    project: VnProject,
    draft: str,
    *,
    chapter_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    """Cheap proposed facts from draft text vs known character names.

    Does not call an LLM. Detects presence of names marked dead in WorldState
    and treats draft presence of a known speaker as status=alive proposal.
    """
    from app.core.world_state import make_fact

    text = draft or ""
    if not text.strip():
        return []
    order = chapter_index_map(project.chapters or [])
    idx = order.get(str(chapter_id or ""), max(order.values()) if order else 0)
    cid = str(chapter_id or "") or "draft"
    proposed: List[Dict[str, Any]] = []
    names: List[str] = []
    for c in project.characters or []:
        n = str(getattr(c, "displayName", None) or getattr(c, "defineName", None) or "")
        if len(n) >= 2:
            names.append(n)
    # Also include subjects already in world state
    world = get_world_state(get_ledger(project))
    for f in world.get("facts") or []:
        n = str(f.get("subject") or "")
        if len(n) >= 2 and n not in names:
            names.append(n)

    for name in names:
        if name not in text:
            continue
        # Presence in draft proposes "alive" unless the line itself asserts death
        window = ""
        for m in re.finditer(re.escape(name) + r".{0,20}", text):
            window = m.group(0)
            break
        value = "dead" if looks_dead_value(window) else "alive"
        proposed.append(
            make_fact(
                subject=name,
                relation="status",
                value=value,
                chapter_id=cid,
                chapter_index=idx,
                quote=window[:80] or name,
                confidence=0.75,
                category="characterization",
            )
        )
    return proposed


def check_proposed_against_world(
    world: Dict[str, Any],
    proposed: Sequence[Dict[str, Any]],
    *,
    at_index: int,
) -> List[WorldConflict]:
    conflicts: List[WorldConflict] = []
    statuses = project_character_status(world, at_index=at_index)

    for pf in proposed:
        subj = str(pf.get("subject") or "")
        rel = str(pf.get("relation") or "")
        val = str(pf.get("value") or "")
        quote = str((pf.get("source") or {}).get("quote") or "")
        cid = str((pf.get("source") or {}).get("chapterId") or "")

        if rel == "status" and val == "alive" and looks_dead_value(statuses.get(subj, "")):
            conflicts.append(
                WorldConflict(
                    code="ws_dead_character",
                    severity="error",
                    message=(
                        f"世界状态记「{subj}」已故/不在场，本稿仍将其当作在场。"
                    ),
                    subject=subj,
                    quote=quote or subj,
                    chapterIds=[cid] if cid else [],
                    category=_CATEGORY_FOR_CODE["ws_dead_character"],
                )
            )
            continue

        # Interval clash with any active single-valued fact
        for ef in active_facts(world, at_index=at_index, subject=subj, relation=rel):
            if _facts_conflict(ef, pf):
                conflicts.append(
                    WorldConflict(
                        code="ws_fact_interval_clash",
                        severity="error",
                        message=(
                            f"事实冲突：{subj}.{rel} 已有「{ef.get('value')}」"
                            f"（章序 {ef.get('validFrom')}–{ef.get('validTo')}），"
                            f"本稿提议「{val}」。"
                        ),
                        subject=subj,
                        quote=quote or val,
                        chapterIds=[
                            x
                            for x in [
                                cid,
                                str((ef.get("source") or {}).get("chapterId") or ""),
                            ]
                            if x
                        ],
                        category=_CATEGORY_FOR_CODE["ws_fact_interval_clash"],
                    )
                )
                break

        # Gone location mentioned as if present
        if rel == "status" and looks_dead_value(statuses.get(subj, "")) is False:
            pass
        if rel == "status" and str(statuses.get(subj) or "").lower() == "gone":
            if val not in ("gone", "abandoned", "destroyed"):
                conflicts.append(
                    WorldConflict(
                        code="ws_gone_location",
                        severity="warn",
                        message=f"地点「{subj}」在世界状态中已标废弃/已毁，本稿仍当作可用。",
                        subject=subj,
                        quote=quote or subj,
                        chapterIds=[cid] if cid else [],
                        category=_CATEGORY_FOR_CODE["ws_gone_location"],
                    )
                )

    return conflicts


def check_draft_presence_against_status(
    world: Dict[str, Any],
    draft: str,
    *,
    at_index: int,
    chapter_id: Optional[str] = None,
) -> List[WorldConflict]:
    """A-layer: names with status=dead appearing in draft."""
    text = draft or ""
    if not text.strip():
        return []
    conflicts: List[WorldConflict] = []
    statuses = project_character_status(world, at_index=at_index)
    for name, status in statuses.items():
        if not looks_dead_value(status):
            continue
        if name and name in text:
            # Find a short evidence line
            quote = name
            for ln in text.splitlines():
                if name in ln:
                    quote = ln.strip()[:160]
                    break
            conflicts.append(
                WorldConflict(
                    code="ws_dead_character",
                    severity="error",
                    message=(
                        f"世界状态记「{name}」为 {status}，本稿仍出现该名。"
                    ),
                    subject=name,
                    quote=quote,
                    chapterIds=[chapter_id] if chapter_id else [],
                    category=_CATEGORY_FOR_CODE["ws_dead_character"],
                )
            )
    # Gone locations
    for f in active_facts(world, at_index=at_index, relation="status"):
        if str(f.get("value") or "").lower() != "gone":
            continue
        name = str(f.get("subject") or "")
        if len(name) >= 2 and name in text:
            conflicts.append(
                WorldConflict(
                    code="ws_gone_location",
                    severity="warn",
                    message=f"地点「{name}」已标废弃/已毁，本稿仍出现。",
                    subject=name,
                    quote=name,
                    chapterIds=[chapter_id] if chapter_id else [],
                    category=_CATEGORY_FOR_CODE["ws_gone_location"],
                )
            )
    return conflicts


def run_consistency_harness(
    project: VnProject,
    *,
    draft: str = "",
    chapter_id: Optional[str] = None,
    proposed_facts: Optional[Sequence[Dict[str, Any]]] = None,
) -> ConsistencyHarnessReport:
    """Run A+B layers. Empty draft → no draft conflicts (still returns structure)."""
    ledger = get_ledger(project)
    world = get_world_state(ledger)
    order = chapter_index_map(project.chapters or [])
    at = order.get(
        str(chapter_id or ""),
        max(order.values()) if order else 0,
    )

    proposed = list(proposed_facts) if proposed_facts is not None else []
    if draft and not proposed:
        proposed = propose_facts_from_draft(project, draft, chapter_id=chapter_id)

    conflicts: List[WorldConflict] = []
    if draft:
        conflicts.extend(
            check_draft_presence_against_status(
                world, draft, at_index=at, chapter_id=chapter_id
            )
        )
    conflicts.extend(
        check_proposed_against_world(world, proposed, at_index=at)
    )

    # Dedup by (code, subject)
    seen: set[tuple[str, str]] = set()
    uniq: List[WorldConflict] = []
    for c in conflicts:
        key = (c.code, c.subject)
        if key in seen:
            continue
        seen.add(key)
        uniq.append(c)

    blocking = any(c.severity == "error" for c in uniq)
    return ConsistencyHarnessReport(
        conflicts=uniq,
        proposedFacts=list(proposed)[:40],
        blocking=blocking,
    )


def detect_world_state_findings(project: VnProject) -> List[Dict[str, Any]]:
    """Adapter for ``eval_longrange.detect_deterministic`` — scan chapter plains.

    Emits findings shaped like continuity findings (code / chapterId / message).
    """
    ledger = get_ledger(project)
    world = get_world_state(ledger)
    if not (world.get("facts") or []):
        # Bootstrap from chapter digests so eval works before a save cycle
        from app.core.world_facts import sync_world_state_after_digest

        for ch in project.chapters or []:
            ledger = sync_world_state_after_digest(project, ledger, ch.id)
        world = get_world_state(ledger)

    order = chapter_index_map(project.chapters or [])
    out: List[Dict[str, Any]] = []
    from app.core.agent_context import chapter_plain

    for ch in project.chapters or []:
        cid = str(ch.id)
        idx = order.get(cid, 0)
        plain = chapter_plain(ch, project.characters) or ""
        for c in check_draft_presence_against_status(
            world, plain, at_index=idx, chapter_id=cid
        ):
            out.append(
                {
                    "code": c.code,
                    "kind": c.code,
                    "category": "character"
                    if c.code == "ws_dead_character"
                    else "location",
                    "chapterId": cid,
                    "chapterIds": [cid],
                    "message": c.message,
                }
            )
    return out
