"""Unit tests: deterministic snapshot diff (snapshot_diff)."""

from __future__ import annotations

from app.core.demo import create_demo_project
from app.core.snapshot_diff import compare_snapshots
from app.core.snapshots import snapshot_payload_dict


def _payload(**mutations):
    p = create_demo_project()
    return snapshot_payload_dict(p), p, mutations


def test_same_payload_no_changes():
    p = create_demo_project()
    payload = snapshot_payload_dict(p)
    diff = compare_snapshots(payload, payload)
    assert diff["changedChapters"] == 0
    assert "一致" in diff["summary"]
    assert all(c["status"] == "same" for c in diff["chapters"])
    assert all(c["status"] == "same" for c in diff["characters"])


def test_edited_chapter_reports_word_delta():
    p = create_demo_project()
    payload_a = snapshot_payload_dict(p)
    p2 = p.model_copy(deep=True)
    # extend the first chapter with more narration
    ch = p2.chapters[0]
    ch.blocks = ch.blocks + [{"type": "narration", "text": "又补了一段很长的描写。"}]
    payload_b = snapshot_payload_dict(p2)
    diff = compare_snapshots(payload_a, payload_b)
    assert diff["changedChapters"] == 1
    ch_diff = next(c for c in diff["chapters"] if c["chapterId"] == ch.id)
    assert ch_diff["status"] == "changed"
    assert ch_diff["wordsTo"] > ch_diff["wordsFrom"]
    assert "1 章有变化" in diff["summary"]


def test_added_and_removed_chapters():
    p = create_demo_project()
    payload_a = snapshot_payload_dict(p)
    p2 = p.model_copy(deep=True)
    p2.chapters = p2.chapters[:2]  # drop the rest
    payload_b = snapshot_payload_dict(p2)
    diff = compare_snapshots(payload_a, payload_b)
    removed = [c for c in diff["chapters"] if c["status"] == "removed"]
    assert removed, "dropped chapters must be reported as removed"
    assert all(c["wordsTo"] == 0 and c["linesTo"] == 0 for c in removed)


def test_character_added_and_removed():
    p = create_demo_project()
    payload_a = snapshot_payload_dict(p)
    p2 = p.model_copy(deep=True)
    p2.characters = p2.characters[:-1]  # drop last character
    payload_b = snapshot_payload_dict(p2)
    diff = compare_snapshots(payload_a, payload_b)
    removed = [c for c in diff["characters"] if c["status"] == "removed"]
    assert len(removed) == 1
    assert "移除角色 1 名" in diff["summary"]


def test_timeline_and_location_counts():
    from app.domain.types import TimelineEvent

    p = create_demo_project()
    payload_a = snapshot_payload_dict(p)
    p2 = p.model_copy(deep=True)
    p2.timeline = (p2.timeline or []) + [
        TimelineEvent(
            id="t-new",
            title="新增事件",
            when="某日",
            summary="新增",
            order=99,
        )
    ]
    p2.locations = (p2.locations or [])[:1]  # drop rest
    payload_b = snapshot_payload_dict(p2)
    diff = compare_snapshots(payload_a, payload_b)
    assert diff["timeline"]["added"] == 1
    assert diff["locations"]["removed"] >= 1
    assert "时间线变化 1 条" in diff["summary"]
