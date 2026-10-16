"""Incremental atomic-fact extraction into WorldState (local heuristics, no LLM).

Runs after chapter digest. Deterministic so it can sit on the save path and in CI.
Optional LLM triples may be merged later at low confidence; they must still pass
the consistency harness before being treated as hard truth.
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Sequence, Tuple

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

#: Kinship / social relation: 「A是B的朋友」
_RELATION_RE = re.compile(
    r"(?P<a>[\u4e00-\u9fff·]{2,8})"
    r"(?:是|乃|当作)"
    r"(?P<b>[\u4e00-\u9fff·]{2,8})"
    r"的"
    r"(?P<rel>朋友|好友|恋人|情人|未婚夫|未婚妻|丈夫|妻子|哥哥|弟弟|姐姐|妹妹|"
    r"父亲|母亲|师父|徒弟|同事|上司|下属|敌人|对手|青梅竹马|同学)"
)

#: Possession / holding near a known name (windowed)
_HOLD_VERBS = r"(?:拿着|握着|带着|怀揣|收起|藏着|佩戴|拔出|掏出)"
_HOLD_OBJ = r"([\u4e00-\u9fffA-Za-z0-9]{1,12}(?:钥匙|信|刀|剑|枪|戒指|项链|徽章|手机|照片|纸条|盒子|药|书)?)"

#: Time anchors (chapter-level)
_TIME_ANCHOR_RE = re.compile(
    r"(昨天|今日|今天|明天|翌日|当晚|清晨|黎明|正午|傍晚|深夜|三天前|一周前|"
    r"上个月|那年冬天|那年夏天|第三天|次日|当晚午夜)"
)

#: Ability / incapability
_ABILITY_DENY_RE = re.compile(
    r"(?P<name>[\u4e00-\u9fff·]{2,8})"
    r".{0,6}"
    r"(?:不会|不能|无法|没学会)"
    r"(?P<skill>[\u4e00-\u9fff]{1,8})"
)
_ABILITY_CAN_RE = re.compile(
    r"(?P<name>[\u4e00-\u9fff·]{2,8})"
    r".{0,6}"
    r"(?:会|能|擅长)"
    r"(?P<skill>[\u4e00-\u9fff]{1,8})"
)


def _chapter_index(project: VnProject, chapter_id: str) -> int:
    for i, ch in enumerate(project.chapters or []):
        if str(getattr(ch, "id", "") or "") == chapter_id:
            return i
    return 0


def _char_names(project: VnProject) -> List[str]:
    names: List[str] = []
    for c in project.characters or []:
        for cand in (
            getattr(c, "displayName", None),
            getattr(c, "defineName", None),
            *((getattr(c, "aliases", None) or [])),
        ):
            n = str(cand or "").strip()
            if len(n) >= 2 and n not in names:
                names.append(n)
    return names


def _loc_names(project: VnProject) -> List[str]:
    out: List[str] = []
    for loc in project.locations or []:
        n = str(getattr(loc, "name", "") or "").strip()
        if len(n) >= 2 and n not in out:
            out.append(n)
    return out


def _extract_relations(
    plain: str,
    names: Sequence[str],
    *,
    chapter_id: str,
    idx: int,
) -> List[Dict[str, Any]]:
    facts: List[Dict[str, Any]] = []
    name_set = set(names)
    for m in _RELATION_RE.finditer(plain):
        a, b, rel = m.group("a"), m.group("b"), m.group("rel")
        if a not in name_set and b not in name_set:
            # Still keep if both look like person names (CJK 2–8)
            if len(a) < 2 or len(b) < 2:
                continue
        facts.append(
            make_fact(
                subject=a,
                relation="relation",
                value=f"{rel}:{b}",
                chapter_id=chapter_id,
                chapter_index=idx,
                quote=m.group(0)[:80],
                confidence=0.75,
                category="characterization",
            )
        )
    return facts


def _extract_holds(
    plain: str,
    names: Sequence[str],
    *,
    chapter_id: str,
    idx: int,
) -> List[Dict[str, Any]]:
    facts: List[Dict[str, Any]] = []
    for name in names:
        # 「林夏拿着钥匙」/ 「拿着钥匙的林夏」
        pat1 = re.compile(
            re.escape(name) + r".{0,8}" + _HOLD_VERBS + _HOLD_OBJ
        )
        pat2 = re.compile(
            _HOLD_VERBS + _HOLD_OBJ + r".{0,6}" + re.escape(name)
        )
        for pat in (pat1, pat2):
            for m in pat.finditer(plain):
                obj = (m.group(1) or "").strip()
                if len(obj) < 1:
                    continue
                facts.append(
                    make_fact(
                        subject=name,
                        relation="holds",
                        value=obj,
                        chapter_id=chapter_id,
                        chapter_index=idx,
                        quote=m.group(0)[:80],
                        confidence=0.72,
                        category="factual",
                    )
                )
                break
    return facts


def _extract_at_location(
    plain: str,
    names: Sequence[str],
    locs: Sequence[str],
    *,
    chapter_id: str,
    idx: int,
) -> List[Dict[str, Any]]:
    facts: List[Dict[str, Any]] = []
    for name in names:
        if name not in plain:
            continue
        for loc in locs:
            if loc not in plain:
                continue
            # Same sentence-ish window: name ... 在/来到 loc or reverse
            window = re.compile(
                re.escape(name)
                + r".{0,24}(?:在|来到|回到|前往|走进|离开了?)"
                + re.escape(loc)
            )
            window2 = re.compile(
                re.escape(loc)
                + r".{0,16}"
                + re.escape(name)
            )
            m = window.search(plain) or window2.search(plain)
            if not m:
                continue
            facts.append(
                make_fact(
                    subject=name,
                    relation="location",
                    value=loc,
                    chapter_id=chapter_id,
                    chapter_index=idx,
                    quote=m.group(0)[:80],
                    confidence=0.7,
                    category="world_building",
                )
            )
            break
    return facts


def _extract_time_anchors(
    plain: str,
    *,
    chapter_id: str,
    idx: int,
) -> List[Dict[str, Any]]:
    facts: List[Dict[str, Any]] = []
    seen: set[str] = set()
    for m in _TIME_ANCHOR_RE.finditer(plain):
        label = m.group(1)
        if label in seen:
            continue
        seen.add(label)
        facts.append(
            make_fact(
                subject=f"chapter:{chapter_id}",
                relation="time_anchor",
                value=label,
                chapter_id=chapter_id,
                chapter_index=idx,
                quote=m.group(0)[:40],
                confidence=0.65,
                category="timeline",
            )
        )
        if len(facts) >= 4:
            break
    return facts


def _extract_abilities(
    plain: str,
    names: Sequence[str],
    *,
    chapter_id: str,
    idx: int,
) -> List[Dict[str, Any]]:
    facts: List[Dict[str, Any]] = []
    name_set = set(names)
    for m in _ABILITY_DENY_RE.finditer(plain):
        name, skill = m.group("name"), m.group("skill")
        if name not in name_set:
            continue
        if skill in ("说话", "看见", "听见", "知道", "明白"):
            continue
        facts.append(
            make_fact(
                subject=name,
                relation="cannot",
                value=skill,
                chapter_id=chapter_id,
                chapter_index=idx,
                quote=m.group(0)[:80],
                confidence=0.68,
                category="characterization",
            )
        )
    for m in _ABILITY_CAN_RE.finditer(plain):
        name, skill = m.group("name"), m.group("skill")
        if name not in name_set:
            continue
        if skill in ("说话", "看见", "听见", "知道", "明白", "感到"):
            continue
        facts.append(
            make_fact(
                subject=name,
                relation="can",
                value=skill,
                chapter_id=chapter_id,
                chapter_index=idx,
                quote=m.group(0)[:80],
                confidence=0.6,
                category="characterization",
            )
        )
    return facts


def _facts_from_character_cards(
    project: VnProject,
    speakers: Sequence[str],
    *,
    chapter_id: str,
    idx: int,
) -> List[Dict[str, Any]]:
    """When a character appears, seed soft facts from their relationships field."""
    facts: List[Dict[str, Any]] = []
    spoken = set(speakers)
    for c in project.characters or []:
        name = str(getattr(c, "displayName", None) or getattr(c, "defineName", None) or "")
        if name not in spoken:
            continue
        rel = str(getattr(c, "relationships", None) or "").strip()
        if len(rel) < 4:
            continue
        facts.append(
            make_fact(
                subject=name,
                relation="card_relations",
                value=rel[:120],
                chapter_id=chapter_id,
                chapter_index=idx,
                quote=rel[:80],
                confidence=0.55,
                category="characterization",
            )
        )
    return facts


def _facts_from_ledger_state_relations(
    ledger_states: Sequence[Dict[str, Any]],
    *,
    chapter_id: str,
    idx: int,
) -> List[Dict[str, Any]]:
    facts: List[Dict[str, Any]] = []
    for s in ledger_states:
        if str(s.get("chapterId") or "") != chapter_id:
            continue
        name = str(s.get("characterName") or "").strip()
        rel = str(s.get("relations") or "").strip()
        if not name or len(rel) < 2 or rel in ("—", "-", "无"):
            continue
        facts.append(
            make_fact(
                subject=name,
                relation="state_relations",
                value=rel[:120],
                chapter_id=chapter_id,
                chapter_index=idx,
                quote=rel[:80],
                confidence=0.6,
                category="characterization",
            )
        )
    return facts


def normalize_llm_world_facts(
    rows: Sequence[Any],
    *,
    chapter_id: str,
    chapter_index: int,
) -> List[Dict[str, Any]]:
    """Convert optional LLM triples into WorldState facts (capped confidence).

    Expected row shape: {subject, relation, value, quote?}
    Never exceeds confidence 0.55 — harness / author confirm remains the truth gate.
    """
    out: List[Dict[str, Any]] = []
    for raw in rows or []:
        if not isinstance(raw, dict):
            continue
        subj = str(raw.get("subject") or "").strip()
        rel = str(raw.get("relation") or "").strip()
        val = str(raw.get("value") or "").strip()
        if not subj or not rel or not val:
            continue
        # Guard against free-form dump relations
        if len(rel) > 32 or len(val) > 120:
            continue
        out.append(
            make_fact(
                subject=subj,
                relation=rel,
                value=val,
                chapter_id=chapter_id,
                chapter_index=chapter_index,
                quote=str(raw.get("quote") or "")[:80],
                confidence=min(0.55, float(raw.get("confidence") or 0.55)),
                category=str(raw.get("category") or "factual"),
            )
        )
        if len(out) >= 16:
            break
    return out


def extract_facts_from_chapter(
    project: VnProject,
    chapter_id: str,
    *,
    ledger_states: Optional[Sequence[Dict[str, Any]]] = None,
    llm_world_facts: Optional[Sequence[Any]] = None,
) -> List[Dict[str, Any]]:
    """Heuristic atomic facts for one chapter (idempotent when re-digested)."""
    ch = next((c for c in (project.chapters or []) if c.id == chapter_id), None)
    if ch is None:
        return []
    idx = _chapter_index(project, chapter_id)
    dig = make_chapter_digest(ch, project.characters)
    plain = chapter_plain(ch, project.characters) or ""
    facts: List[Dict[str, Any]] = []
    names = _char_names(project)
    locs = _loc_names(project)

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
    for name in names:
        if name not in plain:
            continue
        for m in re.finditer(
            re.escape(name) + r".{0,12}(?:" + _DEAD_RE.pattern + r")", plain
        ):
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

    # Expanded heuristics (relation / holds / location / time / ability)
    facts.extend(_extract_relations(plain, names, chapter_id=chapter_id, idx=idx))
    facts.extend(_extract_holds(plain, names, chapter_id=chapter_id, idx=idx))
    facts.extend(
        _extract_at_location(plain, names, locs, chapter_id=chapter_id, idx=idx)
    )
    facts.extend(_extract_time_anchors(plain, chapter_id=chapter_id, idx=idx))
    facts.extend(_extract_abilities(plain, names, chapter_id=chapter_id, idx=idx))
    facts.extend(
        _facts_from_character_cards(
            project, speakers, chapter_id=chapter_id, idx=idx
        )
    )
    facts.extend(
        _facts_from_ledger_state_relations(
            list(ledger_states or []), chapter_id=chapter_id, idx=idx
        )
    )

    # Optional LLM triples — always capped confidence
    if llm_world_facts:
        facts.extend(
            normalize_llm_world_facts(
                llm_world_facts, chapter_id=chapter_id, chapter_index=idx
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
    plain = chapter_plain(ch, project.characters) or ""
    pre: List[str] = []
    for m in _TIME_ANCHOR_RE.finditer(plain):
        pre.append(f"time:{m.group(1)}")
        if len(pre) >= 3:
            break
    return make_event_frame(
        chapter_id=chapter_id,
        summary=summary,
        participants=participants,
        preconditions=pre,
        postconditions=posts,
    )


_DEFERRED_FACTS_CAP = 40


def _fact_is_author_confirmed(fact: Dict[str, Any]) -> bool:
    src = fact.get("source") if isinstance(fact.get("source"), dict) else {}
    return bool(src.get("authorConfirmed"))


def _partition_facts_for_commit(
    world: Dict[str, Any],
    proposed: Sequence[Dict[str, Any]],
    *,
    at_index: int,
) -> Tuple[List[Dict[str, Any]], List[Dict[str, Any]]]:
    """Split proposed facts into (commit, deferred) via A/B harness.

    Author-confirmed facts always commit. Error-level conflicts against the
    *remaining* world (same-chapter facts already stripped) go to deferred.
    """
    from app.core.harness.world_consistency import check_proposed_against_world

    commit: List[Dict[str, Any]] = []
    deferred: List[Dict[str, Any]] = []
    for pf in proposed:
        if not isinstance(pf, dict):
            continue
        if _fact_is_author_confirmed(pf):
            commit.append(pf)
            continue
        conflicts = check_proposed_against_world(world, [pf], at_index=at_index)
        if any(c.severity == "error" for c in conflicts):
            row = dict(pf)
            row["deferredReason"] = (conflicts[0].message if conflicts else "harness")[
                :160
            ]
            row["deferredCodes"] = [c.code for c in conflicts if c.severity == "error"][
                :4
            ]
            deferred.append(row)
        else:
            commit.append(pf)
    return commit, deferred


def sync_world_state_after_digest(
    project: VnProject,
    ledger: Dict[str, Any],
    chapter_id: str,
    *,
    llm_world_facts: Optional[Sequence[Any]] = None,
) -> Dict[str, Any]:
    """Update ledger['worldState'] from the chapter just digested.

    Idempotent per chapter: replaces facts previously sourced from this chapter.
    Only proposals that pass the consistency harness (or are author-confirmed)
    are committed; conflicting proposals land in ``deferredFacts``.
    """
    from app.core.world_state import chapter_index_map

    world = get_world_state(ledger)
    # Prefer states already written into this digest pass
    states = [
        s
        for s in (ledger.get("characterStates") or [])
        if str(s.get("chapterId") or "") == chapter_id
    ]
    new_facts = extract_facts_from_chapter(
        project,
        chapter_id,
        ledger_states=states,
        llm_world_facts=llm_world_facts,
    )
    # Check against world *without* this chapter's prior facts (replace semantics).
    base_facts = [
        f
        for f in (world.get("facts") or [])
        if str((f.get("source") or {}).get("chapterId") or "") != chapter_id
    ]
    base_world = dict(world)
    base_world["facts"] = base_facts
    order = chapter_index_map(project.chapters or [])
    at_index = order.get(str(chapter_id), max(order.values()) if order else 0)
    # Compare against the full world (including this chapter's prior facts) so a
    # re-digest cannot silently revive a dead status that was already committed.
    # Then replace this chapter's own facts and commit only the non-conflicting ones.
    commit, deferred_new = _partition_facts_for_commit(
        world, new_facts, at_index=at_index
    )
    stripped = dict(world)
    stripped["facts"] = base_facts
    world = upsert_facts(stripped, commit, replace_chapter_id=None)
    # Refresh deferred: drop prior rows from this chapter, append new, cap.
    prior_deferred = [
        d
        for d in (world.get("deferredFacts") or [])
        if str((d.get("source") or {}).get("chapterId") or "") != chapter_id
    ]
    for d in deferred_new:
        prior_deferred.append(d)
    world = dict(world)
    world["deferredFacts"] = prior_deferred[-_DEFERRED_FACTS_CAP:]
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
