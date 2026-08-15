"""Unit tests for analysis fact bus (no LLM / no DB)."""
from __future__ import annotations

from app.core.demo import create_demo_project
from app.core.fact_extract import (
    accept_character_link,
    build_scan_candidates,
    compute_fingerprints,
    diff_fingerprints,
    existing_dedupe_keys,
    filter_new_candidates,
    link_dedupe_key,
    reconcile_stale,
    weak_sync_relationships,
)
from app.core.project import normalize_project
from app.domain.types import FactEvidence


def test_fingerprints_change_on_script_edit():
    p = create_demo_project()
    meta = compute_fingerprints(p)
    p2 = p.model_copy(deep=True)
    ch = p2.chapters[0]
    blocks = list(ch.blocks) + [
        {
            "type": "dialogue",
            "id": "x1",
            "characterId": "linxia",
            "text": "新加一句对白用于指纹变更。",
        }
    ]
    p2.chapters = [
        c.model_copy(update={"blocks": blocks}) if c.id == ch.id else c for c in p2.chapters
    ]
    delta = diff_fingerprints(p2, meta)
    assert ch.id in delta.changed_chapter_ids
    assert not delta.is_first_scan


def test_scan_produces_candidates_and_dedupes_accepted():
    p = create_demo_project()
    cands, delta, _meta = build_scan_candidates(p, full=True)
    assert delta.is_first_scan or cands
    keys = existing_dedupe_keys(p)
    fresh = filter_new_candidates(p, cands)
    for c in fresh:
        assert c.dedupe_key not in keys
    # demo already has linxia-zhouyu link — that exact key may still appear with different label
    assert any(c.kind == "timeline_event" for c in cands)


def test_accept_weak_sync_relationships():
    p = normalize_project(
        {
            "id": "t1",
            "title": "t",
            "characters": [
                {
                    "id": "a",
                    "defineName": "a",
                    "displayName": "甲",
                    "color": "#111",
                    "relationships": "",
                },
                {
                    "id": "b",
                    "defineName": "b",
                    "displayName": "乙",
                    "color": "#222",
                    "relationships": "",
                },
            ],
            "chapters": [
                {
                    "id": "ch1",
                    "title": "一",
                    "blocks": [{"type": "label", "id": "start", "name": "start"}],
                }
            ],
        }
    )
    p2 = accept_character_link(
        p,
        from_id="a",
        to_id="b",
        label="旧友",
        evidence=[{"source": "agent"}],
        sync_cards=True,
    )
    assert len(p2.characterLinks or []) == 1
    a = next(c for c in p2.characters if c.id == "a")
    b = next(c for c in p2.characters if c.id == "b")
    assert "乙" in (a.relationships or "")
    assert "甲" in (b.relationships or "")
    # idempotent weak sync
    p3 = weak_sync_relationships(p2, "a", "b", "旧友")
    assert (p3.characters[0].relationships or "").count("旧友") == 1


def test_reconcile_marks_stale_when_quote_missing():
    p = create_demo_project()
    ghost_quote = "这段对白绝对不存在于任何章节XYZ999"
    links = list(p.characterLinks or [])
    links[0] = links[0].model_copy(
        update={
            "evidence": [
                FactEvidence(
                    source="script",
                    chapterId="ch1",
                    quote=ghost_quote,
                )
            ]
        }
    )
    p = p.model_copy(update={"characterLinks": links})
    out = reconcile_stale(p)
    assert out.characterLinks
    assert out.characterLinks[0].stale is True
    assert out.characterLinks[0].staleReason


def test_reconcile_timeline_missing_chapter():
    p = create_demo_project()
    events = list(p.timeline or [])
    events[0] = events[0].model_copy(update={"chapterRef": "missing-ch"})
    p = p.model_copy(update={"timeline": events})
    out = reconcile_stale(p)
    assert out.timeline[0].stale is True


def test_link_dedupe_key_symmetric():
    assert link_dedupe_key("a", "b", "友") == link_dedupe_key("b", "a", "友")


def test_filter_respects_pending_keys():
    p = create_demo_project()
    cands, _, _ = build_scan_candidates(p, full=True)
    if not cands:
        return
    key = cands[0].dedupe_key
    filtered = filter_new_candidates(p, cands, {key})
    assert all(c.dedupe_key != key for c in filtered)
