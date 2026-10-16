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
from app.domain.types import Character, Location, SceneChapter, VnProject


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


def test_extract_relation_holds_time_and_location():
    from app.core.world_facts import extract_facts_from_chapter

    chars = [
        Character(id="c1", defineName="linxia", displayName="林夏", color="#a"),
        Character(id="c2", defineName="aken", displayName="阿肯", color="#b"),
    ]
    ch = SceneChapter(
        id="ch0",
        title="关系",
        prose=(
            "旁白: 林夏是阿肯的朋友。\n"
            "旁白: 今天清晨，林夏拿着钥匙来到车站。\n"
            "林夏: 「我不会游泳。」\n"
        ),
        blocks=[],
    )
    p = VnProject(
        id="p-ex",
        title="抽取",
        characters=chars,
        chapters=[ch],
        locations=[Location(id="l1", name="车站")],
        updatedAt="2026-10-15T00:00:00Z",
    )
    facts = extract_facts_from_chapter(p, "ch0")
    rels = {(f["subject"], f["relation"], f["value"]) for f in facts}
    assert ("林夏", "relation", "朋友:阿肯") in rels
    assert any(f["relation"] == "holds" and f["subject"] == "林夏" for f in facts)
    assert any(
        f["relation"] == "location" and f["value"] == "车站" for f in facts
    )
    assert any(f["relation"] == "time_anchor" for f in facts)
    assert any(
        f["relation"] == "cannot" and f["value"] == "游泳" for f in facts
    )


def test_normalize_llm_world_facts_caps_confidence():
    from app.core.world_facts import normalize_llm_world_facts

    rows = normalize_llm_world_facts(
        [{"subject": "林夏", "relation": "holds", "value": "刀", "confidence": 0.99}],
        chapter_id="ch0",
        chapter_index=0,
    )
    assert len(rows) == 1
    assert rows[0]["confidence"] <= 0.55


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


def test_accept_legal_extension_clears_dead_block():
    """作者接受合法转折后，同一篇草稿不应再被 WorldState A 层挡住。"""
    from app.core.world_state import accept_legal_extension

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

    draft = "林夏站在窗边，笑了笑。"
    before = run_consistency_harness(p, draft=draft, chapter_id="ch1")
    assert before.blocking

    ledger = accept_legal_extension(
        get_ledger(p),
        subject="林夏",
        code="ws_dead_character",
        chapter_id="ch1",
        chapter_index=1,
        note="假死归来",
    )
    p = set_ledger(p, ledger)
    after = run_consistency_harness(p, draft=draft, chapter_id="ch1")
    assert after.blocking is False
    assert not any(c.code == "ws_dead_character" for c in after.conflicts)

    gate = gate_continue_draft(draft, project=p, chapter_id="ch1")
    # May still fail on other lint; WorldState dead must be gone
    assert not any(i.get("code") == "ws_dead_character" for i in gate.issues)
    meta = gate.as_meta()
    assert "acceptCandidates" in meta


def test_write_gate_meta_lists_accept_candidates():
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

    gate = gate_continue_draft(
        "林夏站在窗边，笑了笑。", project=p, chapter_id="ch1"
    )
    assert gate.passed is False
    cand = gate.as_meta().get("acceptCandidates") or []
    assert any(c.get("subject") == "林夏" for c in cand)


def test_write_gate_accept_candidates_prefer_subject_field():
    """Interval-clash messages put values in「」; subject must come from field."""
    from app.core.write_gate import WriteGateResult

    gate = WriteGateResult(
        passed=False,
        issues=[
            {
                "severity": "error",
                "code": "ws_dead_character",
                "message": "世界状态记「林夏」为 dead，本稿仍出现该名。",
                "subject": "林夏",
            }
        ],
    )
    cand = gate.as_meta().get("acceptCandidates") or []
    assert cand and cand[0]["subject"] == "林夏"


def test_gone_location_warn_still_lists_accept_candidate():
    p = _project_with_death()
    ledger = digest_chapter_into_ledger(p, "ch0")
    world = get_world_state(ledger)
    world = upsert_facts(
        world,
        [
            make_fact(
                subject="废弃仓库",
                relation="status",
                value="gone",
                chapter_id="ch0",
                chapter_index=0,
                quote="已毁",
            )
        ],
    )
    ledger["worldState"] = world
    p = set_ledger(p, ledger)
    gate = gate_continue_draft(
        "他们走进废弃仓库。", project=p, chapter_id="ch0"
    )
    # warn only — gate may still pass on other lint, but accept must list location
    cand = gate.as_meta().get("acceptCandidates") or []
    assert any(
        c.get("code") == "ws_gone_location" and c.get("subject") == "废弃仓库"
        for c in cand
    )


def test_semantic_c_layer_parse_requires_quote_in_draft():
    from app.core.harness.world_semantic import parse_semantic_issues

    draft = "林夏忽然说出了只有死者才知道的暗号。"
    hits = parse_semantic_issues(
        {
            "issues": [
                {
                    "code": "ws_knowledge",
                    "severity": "high",
                    "subject": "林夏",
                    "quote": "只有死者才知道的暗号",
                    "message": "林夏不应知道死者暗号",
                },
                {
                    "code": "ws_motive",
                    "quote": "编造的不在稿里",
                    "message": "应被丢弃",
                },
            ]
        },
        draft=draft,
        chapter_id="ch1",
    )
    assert len(hits) == 1
    assert hits[0].code == "ws_knowledge"
    assert hits[0].severity == "warn"  # high → warn in v1


def test_merge_c_into_write_gate_warns_only():
    from app.core.harness.world_consistency import WorldConflict
    from app.core.harness.world_semantic import merge_c_into_write_gate
    from app.core.write_gate import WriteGateResult

    gate = WriteGateResult(passed=True)
    merge_c_into_write_gate(
        gate,
        [
            WorldConflict(
                code="ws_motive",
                severity="warn",
                message="动机矛盾",
                subject="林夏",
                quote="我改主意了",
            )
        ],
    )
    assert gate.passed is True
    assert any(i.get("code") == "ws_motive" for i in gate.issues)
    assert gate.warnings


def test_digest_defers_alive_when_already_dead():
    """已故硬锚存在时，同章再抽 alive 不得覆盖，应进 deferredFacts。"""
    p = _project_with_death()
    ledger = digest_chapter_into_ledger(p, "ch0")
    world = get_world_state(ledger)
    world = upsert_facts(
        world,
        [
            make_fact(
                subject="林夏",
                relation="status",
                value="dead",
                chapter_id="prior",
                chapter_index=0,
                quote="身亡",
            )
        ],
    )
    ledger["worldState"] = world
    # ch1 prose has 林夏 as speaker-like presence via narration, not death-only.
    # Force an alive proposal by digesting a chapter that only shows presence.
    ch_alive = SceneChapter(
        id="chAlive",
        title="归来",
        prose='林夏: 「我回来了。」',
        blocks=[{"type": "dialogue", "characterId": "c1", "text": "我回来了。"}],
    )
    p2 = p.model_copy(update={"chapters": list(p.chapters or []) + [ch_alive]})
    p2 = set_ledger(p2, ledger)
    ledger2 = digest_chapter_into_ledger(p2, "chAlive")
    ws = get_world_state(ledger2)
    statuses = project_character_status(ws, at_index=99)
    assert statuses.get("林夏") == "dead"
    deferred = ws.get("deferredFacts") or []
    assert any(
        str(d.get("subject")) == "林夏" and str(d.get("value")) == "alive"
        for d in deferred
    )


def test_mark_needs_reinterpret_does_not_rewrite_value():
    from app.core.world_state import format_world_constraints, mark_facts_needs_reinterpret

    p = _project_with_death()
    ledger = get_ledger(p)
    ledger["worldState"] = {
        "schemaVersion": 1,
        "facts": [
            make_fact(
                subject="林夏",
                relation="status",
                value="dead",
                chapter_id="ch0",
                chapter_index=0,
                quote="身亡",
            )
        ],
    }
    out = mark_facts_needs_reinterpret(
        ledger, subjects=["林夏"], reason="角色卡已改"
    )
    fact = get_world_state(out)["facts"][0]
    assert fact["value"] == "dead"
    assert fact["validTo"] is None
    assert fact.get("needsReinterpret") is True
    text = format_world_constraints(get_world_state(out), chapters=p.chapters)
    assert "待重解释" in text
    assert "已故/不在场" not in text


def test_accept_interval_clash_requires_relation_and_value():
    from app.core.world_state import accept_legal_extension

    p = _project_with_death()
    ledger = get_ledger(p)
    ledger["worldState"] = {
        "facts": [
            make_fact(
                subject="林夏",
                relation="holds",
                value="钥匙",
                chapter_id="ch0",
                chapter_index=0,
            )
        ]
    }
    try:
        accept_legal_extension(
            ledger,
            subject="林夏",
            code="ws_fact_interval_clash",
            chapter_index=1,
        )
        raise AssertionError("expected ValueError")
    except ValueError:
        pass
    out = accept_legal_extension(
        ledger,
        subject="林夏",
        code="ws_fact_interval_clash",
        chapter_id="ch1",
        chapter_index=1,
        relation="holds",
        new_value="信",
    )
    statuses = [
        f
        for f in get_world_state(out)["facts"]
        if f.get("relation") == "holds" and f.get("validTo") is None
    ]
    assert statuses and statuses[-1]["value"] == "信"
    assert statuses[-1]["source"].get("authorConfirmed") is True


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
