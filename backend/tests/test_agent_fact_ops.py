"""Agent fact-bus ops (propose / add / scan_request)."""
from __future__ import annotations

from app.core.agent import apply_agent_actions
from app.core.demo import create_demo_project


def test_propose_character_link_goes_to_inbox_side_effect():
    p = create_demo_project()
    res = apply_agent_actions(
        p,
        [
            {
                "op": "propose_character_link",
                "fromRef": "林夏",
                "toRef": "周屿",
                "label": "试探中的同盟",
                "quote": "伞下",
            }
        ],
    )
    assert res.inbox_proposals
    assert res.inbox_proposals[0]["kind"] == "character_link"
    assert res.inbox_proposals[0]["payload"]["label"] == "试探中的同盟"
    # project graph unchanged by propose
    assert len(res.project.characterLinks or []) == len(p.characterLinks or [])


def test_add_timeline_event_writes_project():
    p = create_demo_project()
    before = len(p.timeline or [])
    res = apply_agent_actions(
        p,
        [
            {
                "op": "add_timeline_event",
                "title": "Agent 写入节点",
                "when": "第二晚",
                "chapterRef": "ch1",
            }
        ],
    )
    assert len(res.project.timeline or []) == before + 1
    assert any(t.title == "Agent 写入节点" for t in (res.project.timeline or []))


def test_scan_facts_sets_request():
    p = create_demo_project()
    res = apply_agent_actions(
        p, [{"op": "scan_facts", "includePaste": True, "chapterRef": "ch1"}]
    )
    assert res.scan_request is not None
    assert res.scan_request.get("includePaste") is True
