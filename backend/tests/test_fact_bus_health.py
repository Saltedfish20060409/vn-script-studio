"""Health-check coverage for fact-bus edge cases."""
from __future__ import annotations

from app.core.demo import create_demo_project
from app.core.fact_extract import (
    WEAK_LINK_LABELS,
    accept_character_link,
    clear_stale_flags,
    should_weak_sync_label,
)
from app.core.project import normalize_project
from app.domain.types import FactEvidence


def test_weak_labels_skip_card_sync():
    assert "同场" in WEAK_LINK_LABELS
    assert not should_weak_sync_label("同场")
    assert should_weak_sync_label("旧友")

    p = normalize_project(
        {
            "id": "t-weak",
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
        p, from_id="a", to_id="b", label="同场", evidence=[{"source": "script"}]
    )
    assert len(p2.characterLinks or []) == 1
    assert not (p2.characters[0].relationships or "").strip()


def test_clear_stale_flags():
    p = create_demo_project()
    links = list(p.characterLinks or [])
    links[0] = links[0].model_copy(
        update={
            "stale": True,
            "staleReason": "测试",
            "evidence": [
                FactEvidence(source="script", chapterId="ch1", quote="nope-xyz")
            ],
        }
    )
    p = p.model_copy(update={"characterLinks": links})
    cleared = clear_stale_flags(p, link_ids=[links[0].id])
    assert cleared.characterLinks[0].stale is None
    assert cleared.characterLinks[0].staleReason is None
