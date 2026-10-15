"""WorldState schema + ConsistencyHarness — A-layer regression."""

from __future__ import annotations

from app.core.harness.world_consistency import (
    check_proposed_against_world,
    run_consistency_harness,
)
from app.core.pipeline.ledger import (
    digest_chapter_into_ledger,
    format_ledger_for_agent,
    get_ledger,
    set_ledger,
)
from app.core.world_state import (
    get_world_state,
    make_fact,
    project_character_status,
    upsert_facts,
)
from app.core.write_gate import gate_continue_draft
from app.core.write_hybrid import format_hybrid_block
from app.domain.types import Character, SceneChapter, VnProject


def _project_with_death() -> VnProject:
    """Ch0: 林夏出场；Ch1: 正文含身亡；draft later mentions 林夏."""
    chars = [
        Character(
            id="c1",
            defineName="linxia",
            displayName="林夏",
            color="#aabbcc",
        )
    ]
    ch0 = SceneChapter(
        id="ch0",
        title="初遇",
        prose='林夏: 「你好。」\n旁白: 雨还在下。',
        blocks=[
            {"type": "dialogue", "characterId": "c1", "text": "你好。"},
        ],
    )
    ch1 = SceneChapter(
        id="ch1",
        title="诀别",
        prose="旁白: 林夏身亡的消息传来。\n旁白: 葬礼上没有人说话。",
        blocks=[
            {"type": "narration", "text": "林夏身亡的消息传来。"},
        ],
    )
    return VnProject(
        id="p-ws",
        title="WS测试",
        characters=chars,
        chapters=[ch0, ch1],
        updatedAt="2026-10-15T00:00:00Z",
    )


def test_digest_builds_world_state_facts():
    p = _project_with_death()
    ledger = digest_chapter_into_ledger(p, "ch0")
    p = set_ledger(p, ledger)
    ledger = digest_chapter_into_ledger(p, "ch1")
    p = set_ledger(p, ledger)
    world = get_world_state(get_ledger(p))
    assert world.get("facts"), "digest 后应有原子事实"
    # ch1 prose contains 身亡 → status=dead for 林夏
    statuses = project_character_status(world, at_index=1)
    assert "林夏" in statuses
    from app.core.world_state import looks_dead_value

    assert looks_dead_value(statuses["林夏"]), statuses


def test_harness_blocks_dead_character_in_draft():
    p = _project_with_death()
    ledger = digest_chapter_into_ledger(p, "ch0")
    p = set_ledger(p, ledger)
    # Force a dead fact at ch1
    world = get_world_state(get_ledger(p))
    world = upsert_facts(
        world,
        [
            make_fact(
                subject="林夏",
                relation="status",
                value="dead",
                chapter_id="ch1",
                chapter_index=1,
                quote="林夏身亡",
                confidence=0.95,
            )
        ],
    )
    ledger = get_ledger(p)
    ledger["worldState"] = world
    p = set_ledger(p, ledger)

    report = run_consistency_harness(
        p, draft="林夏: 「我还活着。」", chapter_id="ch1"
    )
    assert report.blocking
    codes = {c.code for c in report.conflicts}
    assert "ws_dead_character" in codes


def test_interval_clash_detected():
    alive = make_fact(
        subject="林夏",
        relation="status",
        value="alive",
        chapter_id="ch0",
        chapter_index=0,
        quote="出场",
    )
    # Close alive and assert dead from ch1
    dead = make_fact(
        subject="林夏",
        relation="status",
        value="dead",
        chapter_id="ch1",
        chapter_index=1,
        quote="身亡",
    )
    world = {"facts": [alive], "eventFrames": [], "schemaVersion": 1, "version": 1}
    from app.core.world_state import upsert_facts

    world = upsert_facts(world, [dead])
    # Propose alive again overlapping the dead interval
    proposed = [
        make_fact(
            subject="林夏",
            relation="status",
            value="alive",
            chapter_id="ch2",
            chapter_index=2,
            quote="又出场",
        )
    ]
    conflicts = check_proposed_against_world(world, proposed, at_index=2)
    assert any(c.code in ("ws_dead_character", "ws_fact_interval_clash") for c in conflicts)


def test_format_ledger_prefers_world_constraints():
    p = _project_with_death()
    ledger = digest_chapter_into_ledger(p, "ch0")
    p = set_ledger(p, ledger)
    world = get_world_state(get_ledger(p))
    world = upsert_facts(
        world,
        [
            make_fact(
                subject="林夏",
                relation="status",
                value="dead",
                chapter_id="ch1",
                chapter_index=1,
                quote="身亡",
            )
        ],
    )
    ledger = get_ledger(p)
    ledger["worldState"] = world
    block = format_ledger_for_agent(ledger, chapters=p.chapters)
    assert "世界状态约束" in block
    assert "林夏" in block


def test_hybrid_block_is_marked_soft():
    text = format_hybrid_block(
        [{"label": "章「一」", "snippet": "雨夜", "score": 0.9}]
    )
    assert "soft" in text.lower()
    assert "不是" in text or "硬事实" in text


def test_write_gate_blocks_on_world_state_dead():
    p = _project_with_death()
    ledger = digest_chapter_into_ledger(p, "ch0")
    p = set_ledger(p, ledger)
    world = get_world_state(get_ledger(p))
    world = upsert_facts(
        world,
        [
            make_fact(
                subject="林夏",
                relation="status",
                value="dead",
                chapter_id="ch1",
                chapter_index=1,
                quote="身亡",
            )
        ],
    )
    ledger = get_ledger(p)
    ledger["worldState"] = world
    p = set_ledger(p, ledger)

    result = gate_continue_draft(
        "林夏站在窗边，笑了笑。",
        project=p,
        chapter_id="ch1",
    )
    assert result.passed is False
    assert any(i.get("code") == "ws_dead_character" for i in result.issues)


def test_get_ledger_preserves_world_state():
    p = _project_with_death()
    ledger = get_ledger(p)
    ledger["worldState"] = {
        "schemaVersion": 1,
        "facts": [
            make_fact(
                subject="林夏",
                relation="status",
                value="alive",
                chapter_id="ch0",
                chapter_index=0,
            )
        ],
        "eventFrames": [],
        "version": 1,
    }
    p = set_ledger(p, ledger)
    again = get_ledger(p)
    assert again["worldState"].get("facts")
    assert again["worldState"]["facts"][0]["subject"] == "林夏"


def test_eval_detect_deterministic_includes_ws_dead():
    """eval_longrange adapter must surface WorldState A-layer hits."""
    from app.core.eval_longrange import detect_deterministic

    p = _project_with_death()
    ledger = digest_chapter_into_ledger(p, "ch0")
    p = set_ledger(p, ledger)
    world = get_world_state(get_ledger(p))
    world = upsert_facts(
        world,
        [
            make_fact(
                subject="林夏",
                relation="status",
                value="dead",
                chapter_id="ch0",
                chapter_index=0,
                quote="身亡",
            )
        ],
    )
    # ch1 still mentions 林夏 → should flag
    ledger = get_ledger(p)
    ledger["worldState"] = world
    p = set_ledger(p, ledger)
    # Ensure ch1 plain still has the name
    hits = detect_deterministic(p)
    codes = {h.get("code") for h in hits}
    assert "ws_dead_character" in codes
