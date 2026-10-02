"""P7 settings_ingest plan_to_actions 守卫。"""

from __future__ import annotations

from app.core.settings_ingest import plan_to_actions
from app.domain.types import VnProject


def _project(**extra):
    base = {
        "id": "p1",
        "title": "t",
        "updatedAt": "2026-10-02T00:00:00Z",
        "characters": [],
        "chapters": [],
    }
    base.update(extra)
    return VnProject.model_validate(base)


def test_plan_to_actions_includes_location_link_and_writing_genre():
    project = _project(
        locations=[
            {"id": "l1", "name": "钟楼"},
            {"id": "l2", "name": "车站"},
        ]
    )
    plan = {
        "meta": {"writingGenre": "novel", "title": "新标题"},
        "bible": {"world": "有雨的城"},
        "locationLinks": [
            {"fromName": "钟楼", "toName": "车站", "relation": "雨巷相连"}
        ],
    }
    actions = plan_to_actions(project, plan)
    ops = [a.get("op") for a in actions]
    assert "update_bible" in ops
    assert "update_meta" in ops
    meta = next(a for a in actions if a.get("op") == "update_meta")
    assert meta.get("writingGenre") == "novel"
    assert "add_location_link" in ops


def test_plan_to_actions_skips_empty():
    project = _project()
    assert plan_to_actions(project, {}) == []
