"""Analysis fact bus: fingerprints, heuristic extract, reconcile, accept helpers.

Phase 1 is rule/heuristic first (tests run without LLM). Optional LLM enrichment
can be layered later. Phase 2 reserves source=upload and voiceReports persistence.
"""
from __future__ import annotations

import hashlib
import json
import re
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Set, Tuple

from app.domain.types import (
    AnalysisMeta,
    Character,
    CharacterLink,
    FactEvidence,
    TimelineEvent,
    VnProject,
)

from .agent_context import _blocks_to_plain
from .project import uid

# Phase 2: file upload extraction joins the same inbox via source="upload".
# Heuristic labels too weak to pollute character.relationships cards
WEAK_LINK_LABELS = frozenset({"同场", "设定共现", "粘贴共现"})


def should_weak_sync_label(label: str) -> bool:
    return (label or "").strip() not in WEAK_LINK_LABELS


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _sha(text: str) -> str:
    return hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]


def chapter_fingerprint(project: VnProject, chapter_id: str) -> str:
    ch = next((c for c in project.chapters if c.id == chapter_id), None)
    if not ch:
        return ""
    plain = _blocks_to_plain(ch.blocks, project.characters)
    syn = ch.synopsis or ""
    return _sha(f"{ch.title}\n{syn}\n{plain}")


def bible_fingerprint(project: VnProject) -> str:
    b = project.bible
    if not b:
        return _sha(project.lore or "")
    return _sha(
        "\n".join(
            [
                b.world or "",
                b.background or "",
                b.outline or "",
                b.themes or "",
                b.notes or "",
            ]
        )
    )


def character_fingerprint(c: Character) -> str:
    return _sha(
        "\n".join(
            [
                c.displayName or "",
                c.voice or "",
                c.bio or "",
                c.relationships or "",
            ]
        )
    )


def compute_fingerprints(project: VnProject) -> AnalysisMeta:
    return AnalysisMeta(
        chapterFingerprints={
            ch.id: chapter_fingerprint(project, ch.id) for ch in project.chapters
        },
        bibleFingerprint=bible_fingerprint(project),
        characterFingerprints={
            c.id: character_fingerprint(c) for c in project.characters
        },
    )


@dataclass
class FingerprintDelta:
    changed_chapter_ids: List[str] = field(default_factory=list)
    bible_changed: bool = False
    changed_character_ids: List[str] = field(default_factory=list)
    is_first_scan: bool = False


def diff_fingerprints(project: VnProject, meta: Optional[AnalysisMeta]) -> FingerprintDelta:
    current = compute_fingerprints(project)
    if meta is None or (
        not meta.chapterFingerprints
        and not meta.bibleFingerprint
        and not meta.characterFingerprints
    ):
        return FingerprintDelta(
            changed_chapter_ids=[ch.id for ch in project.chapters],
            bible_changed=True,
            changed_character_ids=[c.id for c in project.characters],
            is_first_scan=True,
        )
    prev_ch = meta.chapterFingerprints or {}
    changed_ch = [
        ch.id
        for ch in project.chapters
        if prev_ch.get(ch.id) != (current.chapterFingerprints or {}).get(ch.id)
    ]
    # deleted chapters ignored; new chapters appear as changed
    for cid, fp in (current.chapterFingerprints or {}).items():
        if cid not in prev_ch and cid not in changed_ch:
            changed_ch.append(cid)
    prev_chars = meta.characterFingerprints or {}
    changed_chars = [
        c.id
        for c in project.characters
        if prev_chars.get(c.id) != (current.characterFingerprints or {}).get(c.id)
    ]
    return FingerprintDelta(
        changed_chapter_ids=changed_ch,
        bible_changed=(meta.bibleFingerprint or "") != (current.bibleFingerprint or ""),
        changed_character_ids=changed_chars,
        is_first_scan=False,
    )


def link_dedupe_key(from_id: str, to_id: str, label: str) -> str:
    a, b = sorted([from_id.strip().lower(), to_id.strip().lower()])
    lab = re.sub(r"\s+", "", (label or "").strip().lower())
    return f"clink:{a}|{b}|{lab}"


def timeline_dedupe_key(title: str, chapter_ref: Optional[str] = None) -> str:
    t = re.sub(r"\s+", "", (title or "").strip().lower())
    return f"tl:{(chapter_ref or '').lower()}|{t}"


@dataclass
class FactCandidate:
    kind: str  # character_link | timeline_event
    payload: Dict[str, Any]
    evidence: List[Dict[str, Any]]
    dedupe_key: str
    # Optional LLM semantic-layer confidence (0..1); None for pure heuristic.
    confidence: Optional[float] = None


def _char_index(project: VnProject) -> Dict[str, Character]:
    idx: Dict[str, Character] = {}
    for c in project.characters:
        idx[c.id.lower()] = c
        idx[c.defineName.lower()] = c
        idx[c.displayName.lower()] = c
    return idx


def _find_char(idx: Dict[str, Character], name: str) -> Optional[Character]:
    return idx.get((name or "").strip().lower())


def extract_from_character_cards(
    project: VnProject, character_ids: Optional[Sequence[str]] = None
) -> List[FactCandidate]:
    """Seed link candidates from free-text relationships on cards."""
    allow = set(character_ids) if character_ids is not None else None
    idx = _char_index(project)
    out: List[FactCandidate] = []
    names = sorted(
        [c.displayName for c in project.characters if c.displayName],
        key=len,
        reverse=True,
    )
    for c in project.characters:
        if allow is not None and c.id not in allow:
            continue
        text = (c.relationships or "").strip()
        if not text:
            continue
        fp = character_fingerprint(c)
        for other_name in names:
            if other_name == c.displayName:
                continue
            if other_name not in text:
                continue
            other = _find_char(idx, other_name)
            if not other or other.id == c.id:
                continue
            # crude label: snippet around the name
            i = text.find(other_name)
            start = max(0, i - 8)
            end = min(len(text), i + len(other_name) + 12)
            label = re.sub(r"[；;。\n]+", "", text[start:end]).strip() or "相关"
            if len(label) > 24:
                label = label[:24]
            key = link_dedupe_key(c.id, other.id, label)
            out.append(
                FactCandidate(
                    kind="character_link",
                    payload={
                        "fromId": c.id,
                        "toId": other.id,
                        "label": label,
                    },
                    evidence=[
                        {
                            "source": "card",
                            "field": "relationships",
                            "quote": text[:160],
                            "fingerprint": fp,
                        }
                    ],
                    dedupe_key=key,
                )
            )
    return out


def extract_from_bible(project: VnProject) -> List[FactCandidate]:
    b = project.bible
    if not b:
        return []
    text = "\n".join(
        filter(
            None,
            [b.background or "", b.outline or "", b.world or ""],
        )
    )
    if not text.strip():
        return []
    fp = bible_fingerprint(project)
    idx = _char_index(project)
    out: List[FactCandidate] = []
    chars = [c for c in project.characters if c.displayName]
    for i, a in enumerate(chars):
        for bch in chars[i + 1 :]:
            if a.displayName in text and bch.displayName in text:
                # co-mention in bible → weak relation candidate
                key = link_dedupe_key(a.id, bch.id, "设定共现")
                out.append(
                    FactCandidate(
                        kind="character_link",
                        payload={
                            "fromId": a.id,
                            "toId": bch.id,
                            "label": "设定共现",
                        },
                        evidence=[
                            {
                                "source": "bible",
                                "quote": text[:200],
                                "fingerprint": fp,
                            }
                        ],
                        dedupe_key=key,
                    )
                )
    # outline lines as timeline seeds
    outline = (b.outline or "").strip()
    if outline:
        lines = [ln.strip() for ln in re.split(r"[\n；;]", outline) if ln.strip()]
        for n, ln in enumerate(lines[:12], start=1):
            title = re.sub(r"^\d+[\.\)、]\s*", "", ln)[:40]
            key = timeline_dedupe_key(title, None)
            out.append(
                FactCandidate(
                    kind="timeline_event",
                    payload={
                        "title": title,
                        "when": f"大纲 · {n}",
                        "summary": ln[:200],
                        "chapterRef": None,
                        "order": n,
                    },
                    evidence=[
                        {
                            "source": "bible",
                            "field": "outline",
                            "quote": ln[:160],
                            "fingerprint": fp,
                        }
                    ],
                    dedupe_key=key,
                )
            )
    return out


def extract_from_chapters(
    project: VnProject, chapter_ids: Sequence[str]
) -> List[FactCandidate]:
    out: List[FactCandidate] = []
    id_set = set(chapter_ids)
    chapter_index = {ch.id: i for i, ch in enumerate(project.chapters)}
    for ch in project.chapters:
        if ch.id not in id_set:
            continue
        plain = _blocks_to_plain(ch.blocks, project.characters)
        syn = (ch.synopsis or "").strip()
        blob = f"{syn}\n{plain}".strip()
        if not blob:
            continue
        fp = chapter_fingerprint(project, ch.id)
        present = [
            c
            for c in project.characters
            if c.displayName and c.displayName in blob
        ]
        for i, a in enumerate(present):
            for bch in present[i + 1 :]:
                key = link_dedupe_key(a.id, bch.id, "同场")
                # find a short quote containing both if possible
                quote = ""
                for line in blob.splitlines():
                    if a.displayName in line and bch.displayName in line:
                        quote = line.strip()[:160]
                        break
                if not quote:
                    quote = blob[:120]
                out.append(
                    FactCandidate(
                        kind="character_link",
                        payload={
                            "fromId": a.id,
                            "toId": bch.id,
                            "label": "同场",
                        },
                        evidence=[
                            {
                                "source": "script",
                                "chapterId": ch.id,
                                "quote": quote,
                                "fingerprint": fp,
                            }
                        ],
                        dedupe_key=key,
                    )
                )
        # chapter as timeline node
        title = ch.title or ch.id
        key = timeline_dedupe_key(title, ch.id)
        out.append(
            FactCandidate(
                kind="timeline_event",
                payload={
                    "title": title,
                    "when": syn[:40] if syn else "章节节点",
                    "summary": syn or plain[:160],
                    "chapterRef": ch.id,
                    "order": float(chapter_index.get(ch.id, 0) + 1),
                },
                evidence=[
                    {
                        "source": "script",
                        "chapterId": ch.id,
                        "quote": (syn or plain)[:160],
                        "fingerprint": fp,
                    }
                ],
                dedupe_key=key,
            )
        )
    return out


def extract_from_paste(project: VnProject, paste_text: str) -> List[FactCandidate]:
    text = (paste_text or "").strip()
    if not text:
        return []
    fp = _sha(text)
    out: List[FactCandidate] = []
    chars = [c for c in project.characters if c.displayName]
    for i, a in enumerate(chars):
        for bch in chars[i + 1 :]:
            if a.displayName in text and bch.displayName in text:
                key = link_dedupe_key(a.id, bch.id, "粘贴共现")
                out.append(
                    FactCandidate(
                        kind="character_link",
                        payload={
                            "fromId": a.id,
                            "toId": bch.id,
                            "label": "粘贴共现",
                        },
                        evidence=[
                            {
                                "source": "paste",
                                "quote": text[:200],
                                "fingerprint": fp,
                            }
                        ],
                        dedupe_key=key,
                    )
                )
    return out


def merge_candidates(cands: Sequence[FactCandidate]) -> List[FactCandidate]:
    by_key: Dict[str, FactCandidate] = {}
    for c in cands:
        prev = by_key.get(c.dedupe_key)
        if not prev:
            by_key[c.dedupe_key] = c
            continue
        # merge evidence
        seen = {
            json.dumps(e, ensure_ascii=False, sort_keys=True) for e in prev.evidence
        }
        for e in c.evidence:
            s = json.dumps(e, ensure_ascii=False, sort_keys=True)
            if s not in seen:
                prev.evidence.append(e)
                seen.add(s)
    return list(by_key.values())


def existing_dedupe_keys(project: VnProject) -> Set[str]:
    keys: Set[str] = set()
    for l in project.characterLinks or []:
        keys.add(link_dedupe_key(l.fromId, l.toId, l.label))
    for t in project.timeline or []:
        keys.add(timeline_dedupe_key(t.title, t.chapterRef))
    return keys


def filter_new_candidates(
    project: VnProject,
    cands: Sequence[FactCandidate],
    pending_keys: Optional[Set[str]] = None,
) -> List[FactCandidate]:
    taken = existing_dedupe_keys(project) | (pending_keys or set())
    return [c for c in cands if c.dedupe_key not in taken]


def build_scan_candidates(
    project: VnProject,
    *,
    force_chapter_ids: Optional[Sequence[str]] = None,
    paste_text: Optional[str] = None,
    full: bool = False,
) -> Tuple[List[FactCandidate], FingerprintDelta, AnalysisMeta]:
    meta = project.analysisMeta
    delta = diff_fingerprints(project, meta)
    if full or delta.is_first_scan:
        ch_ids = [ch.id for ch in project.chapters]
        char_ids = None
        do_bible = True
    else:
        ch_ids = list(force_chapter_ids) if force_chapter_ids else list(delta.changed_chapter_ids)
        char_ids = list(delta.changed_character_ids) if delta.changed_character_ids else []
        do_bible = delta.bible_changed
        if force_chapter_ids:
            # still include card/bible if forced scan of a chapter only? keep delta for cards
            pass

    cands: List[FactCandidate] = []
    if do_bible or full or delta.is_first_scan:
        cands.extend(extract_from_bible(project))
    if char_ids is None or char_ids or full or delta.is_first_scan:
        cands.extend(extract_from_character_cards(project, char_ids))
    if ch_ids:
        cands.extend(extract_from_chapters(project, ch_ids))
    if paste_text:
        cands.extend(extract_from_paste(project, paste_text))

    merged = merge_candidates(cands)
    fresh = compute_fingerprints(project)
    fresh.lastScanAt = _now_iso()
    if meta and meta.lastReconcileAt:
        fresh.lastReconcileAt = meta.lastReconcileAt
    return merged, delta, fresh


def _chapter_plain(project: VnProject, chapter_id: str) -> str:
    ch = next((c for c in project.chapters if c.id == chapter_id), None)
    if not ch:
        return ""
    return _blocks_to_plain(ch.blocks, project.characters)


def reconcile_stale(project: VnProject) -> VnProject:
    """Mark accepted facts stale when script quotes vanish; never auto-delete."""
    next_p = project.model_copy(deep=True)
    links: List[CharacterLink] = []
    for link in next_p.characterLinks or []:
        stale = False
        reason = None
        evs = link.evidence or []
        script_evs = [e for e in evs if e.source == "script" and e.quote]
        if script_evs and all(
            (e.chapterId and e.quote not in _chapter_plain(next_p, e.chapterId))
            or (not e.chapterId and e.quote not in "".join(
                _chapter_plain(next_p, ch.id) for ch in next_p.chapters
            ))
            for e in script_evs
        ):
            # only stale if EVERY script quote is gone
            if script_evs:
                stale = True
                reason = "剧本出处句已找不到"
        card_evs = [e for e in evs if e.source == "card"]
        if card_evs:
            # if both endpoints cleared relationships mentioning the other
            a = next((c for c in next_p.characters if c.id == link.fromId), None)
            b = next((c for c in next_p.characters if c.id == link.toId), None)
            if a and b:
                a_rel = a.relationships or ""
                b_rel = b.relationships or ""
                if not a_rel.strip() and not b_rel.strip() and not script_evs:
                    stale = True
                    reason = reason or "角色卡关系字段已清空"
        links.append(
            link.model_copy(
                update={
                    "stale": stale or None,
                    "staleReason": reason if stale else None,
                }
            )
        )
    events: List[TimelineEvent] = []
    for ev in next_p.timeline or []:
        stale = False
        reason = None
        script_evs = [
            e for e in (ev.evidence or []) if e.source == "script" and e.quote
        ]
        if script_evs:
            missing = True
            for e in script_evs:
                cid = e.chapterId or ev.chapterRef
                if cid and e.quote and e.quote in _chapter_plain(next_p, cid):
                    missing = False
                    break
                if not cid and e.quote:
                    if any(
                        e.quote in _chapter_plain(next_p, ch.id)
                        for ch in next_p.chapters
                    ):
                        missing = False
                        break
            if missing:
                stale = True
                reason = "剧本出处句已找不到"
        if ev.chapterRef and not any(ch.id == ev.chapterRef for ch in next_p.chapters):
            stale = True
            reason = "关联章节已删除"
        events.append(
            ev.model_copy(
                update={
                    "stale": stale or None,
                    "staleReason": reason if stale else None,
                }
            )
        )
    meta = compute_fingerprints(next_p)
    prev = next_p.analysisMeta
    meta.lastScanAt = prev.lastScanAt if prev else None
    meta.lastReconcileAt = _now_iso()
    return next_p.model_copy(
        update={
            "characterLinks": links,
            "timeline": events,
            "analysisMeta": meta,
        }
    )


def weak_sync_relationships(
    project: VnProject, from_id: str, to_id: str, label: str
) -> VnProject:
    """Append a short summary sentence to both character cards (deduped)."""
    next_p = project.model_copy(deep=True)
    a = next((c for c in next_p.characters if c.id == from_id), None)
    b = next((c for c in next_p.characters if c.id == to_id), None)
    if not a or not b:
        return next_p
    clause_ab = f"与{b.displayName}：{label}"
    clause_ba = f"与{a.displayName}：{label}"

    def _append(rel: str, clause: str) -> str:
        rel = (rel or "").strip()
        if clause in rel:
            return rel
        return f"{rel}；{clause}".strip("；") if rel else clause

    chars = []
    for c in next_p.characters:
        if c.id == a.id:
            chars.append(c.model_copy(update={"relationships": _append(c.relationships or "", clause_ab)}))
        elif c.id == b.id:
            chars.append(c.model_copy(update={"relationships": _append(c.relationships or "", clause_ba)}))
        else:
            chars.append(c)
    return next_p.model_copy(update={"characters": chars})


def accept_character_link(
    project: VnProject,
    *,
    from_id: str,
    to_id: str,
    label: str,
    evidence: Optional[List[Dict[str, Any]]] = None,
    link_id: Optional[str] = None,
    sync_cards: bool = True,
) -> VnProject:
    if from_id == to_id:
        return project
    key = link_dedupe_key(from_id, to_id, label)
    if key in existing_dedupe_keys(project):
        return project
    ev_models = [FactEvidence.model_validate(e) for e in (evidence or [])]
    link = CharacterLink(
        id=link_id or uid("clink"),
        fromId=from_id,
        toId=to_id,
        label=label or "关系",
        evidence=ev_models or None,
        acceptedAt=_now_iso(),
    )
    next_p = project.model_copy(
        deep=True,
        update={
            "characterLinks": [*(project.characterLinks or []), link],
        },
    )
    if sync_cards and should_weak_sync_label(label or "关系"):
        next_p = weak_sync_relationships(next_p, from_id, to_id, label or "关系")
    return next_p


def accept_timeline_event(
    project: VnProject,
    *,
    title: str,
    when: Optional[str] = None,
    summary: Optional[str] = None,
    chapter_ref: Optional[str] = None,
    order: Optional[float] = None,
    evidence: Optional[List[Dict[str, Any]]] = None,
    event_id: Optional[str] = None,
) -> VnProject:
    key = timeline_dedupe_key(title, chapter_ref)
    if key in existing_dedupe_keys(project):
        return project
    ev_models = [FactEvidence.model_validate(e) for e in (evidence or [])]
    ord_v = order if order is not None else float(len(project.timeline or []) + 1)
    ev = TimelineEvent(
        id=event_id or uid("tl"),
        title=title,
        when=when,
        summary=summary,
        chapterRef=chapter_ref,
        order=ord_v,
        evidence=ev_models or None,
        acceptedAt=_now_iso(),
    )
    return project.model_copy(
        deep=True,
        update={"timeline": [*(project.timeline or []), ev]},
    )


def clear_stale_flags(
    project: VnProject,
    *,
    link_ids: Optional[Sequence[str]] = None,
    timeline_ids: Optional[Sequence[str]] = None,
    all_stale: bool = False,
) -> VnProject:
    """User acknowledges stale facts — clear flags without deleting."""
    next_p = project.model_copy(deep=True)
    link_set = set(link_ids or [])
    tl_set = set(timeline_ids or [])
    links = []
    for l in next_p.characterLinks or []:
        if all_stale or l.id in link_set:
            links.append(
                l.model_copy(update={"stale": None, "staleReason": None})
            )
        else:
            links.append(l)
    events = []
    for t in next_p.timeline or []:
        if all_stale or t.id in tl_set:
            events.append(
                t.model_copy(update={"stale": None, "staleReason": None})
            )
        else:
            events.append(t)
    return next_p.model_copy(update={"characterLinks": links, "timeline": events})


def candidate_to_dict(c: FactCandidate) -> Dict[str, Any]:
    out = {
        "kind": c.kind,
        "payload": c.payload,
        "evidence": c.evidence,
        "dedupeKey": c.dedupe_key,
    }
    if c.confidence is not None:
        out["confidence"] = c.confidence
    return out
