"""P2: novel_memory deltas without TBD placeholders."""
from __future__ import annotations

from app.core.demo import create_demo_project
from app.core.novel_memory import (
    build_all_archive_drafts,
    build_continuity_text,
    format_memory_for_agent,
    number_chapters,
)


def test_continuity_text_has_no_tbd():
    p = create_demo_project()
    group = number_chapters(p)
    text = build_continuity_text(p, group)
    assert "TBD" not in text
    assert "Character deltas" in text
    assert "出场" in text or "无自动检出" in text


def test_continuity_includes_world_state_hard_anchors():
    from app.core.pipeline.ledger import set_ledger
    from app.core.world_state import make_fact

    p = create_demo_project()
    ledger = dict(p.writingLedger or {})
    ledger["worldState"] = {
        "schemaVersion": 1,
        "facts": [
            make_fact(
                subject="林夏",
                relation="status",
                value="dead",
                chapter_id=(p.chapters or [None])[0].id if p.chapters else "ch0",
                chapter_index=0,
                quote="身亡",
            )
        ],
    }
    p = set_ledger(p, ledger)
    group = number_chapters(p)
    text = build_continuity_text(p, group)
    assert "WorldState Hard Anchors" in text
    assert "林夏" in text
    assert "已故" in text


def test_archive_draft_deltas_populated():
    p = create_demo_project()
    drafts = build_all_archive_drafts(p, span=10, include_incomplete=True)
    assert drafts
    d = drafts[0]
    assert "character" in d.deltas
    assert isinstance(d.deltas["character"], list)
    assert "TBD" not in d.continuity_text


def test_format_memory_keeps_deltas_and_drops_snapshot():
    """超预算时留下硬锚点与增量，丢掉设定快照，且不从中段对切。"""
    continuity = "\n".join(
        [
            "## WorldState Hard Anchors（本段结束时）",
            "林夏已故专名锚点ZZZ",
            "",
            "## Range Spine",
            "脊" * 2000,
            "",
            "## Character And Plot Memory To Preserve",
            "### Character deltas",
            "- 角色增量专名QQQ",
            "",
            "## Current Rolling Context Snapshot",
            "快照废料" * 2000,
        ]
    )
    out = format_memory_for_agent(continuity, max_chars=700)
    assert "林夏已故专名锚点ZZZ" in out
    assert "角色增量专名QQQ" in out
    assert "记忆切片中间省略" not in out
    assert "快照废料" not in out
    assert "因篇幅未展开" in out
