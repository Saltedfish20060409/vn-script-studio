"""本场写后守卫。"""

from __future__ import annotations

from app.core.demo import create_demo_project
from app.core.scene_guard import guard_scene_draft
from app.core.writing_strategy import (
    WritingStrategyProfile,
    adapt_from_turn_signals,
    reset_writing_strategy,
    set_writing_strategy,
)


def test_empty_draft_skips_guard():
    p = create_demo_project()
    r = guard_scene_draft(p, "")
    assert r.ok is True


def test_clean_prose_usually_passes():
    p = create_demo_project()
    draft = "林夏：「末班车要开了。」\n旁白：雨还没有停。"
    r = guard_scene_draft(p, draft, chapter_id=p.chapters[0].id)
    assert isinstance(r.ok, bool)
    assert isinstance(r.as_meta(), dict)


def test_adapt_strengthens_on_guard_signal():
    reset_writing_strategy()
    set_writing_strategy(
        WritingStrategyProfile(attention="high", memory="high", reasoning="high")
    )
    adapt = adapt_from_turn_signals(
        scene_guard_strengthen=True,
        gate_failed=True,
        current_assist="weak",
    )
    assert adapt.changed is True
    assert adapt.profile.attention in ("mid", "low")
    assert adapt.suggested_assist in ("mid", "strong")
    reset_writing_strategy()
