"""VN/轻小说特异约束：分支记忆、伏笔图、总装、垂直评测。"""

from __future__ import annotations

from app.core.branch_memory import (
    filter_ledger_for_route,
    format_branch_memory_block,
    resolve_branch_memory_scope,
)
from app.core.demo import create_demo_project
from app.core.eval_vn_sota import run_vn_sota_suite
from app.core.foreshadow_graph import build_foreshadow_graph, format_foreshadow_payoff_block
from app.core.pipeline.ledger import AUTO_FORESHADOW_NOTE, get_ledger, set_ledger
from app.core.vn_scene_constraints import format_vn_scene_constraints_block
from app.core.vn_write_bundle import assemble_vn_write_bundle
from app.core.voice_write_prior import format_voice_write_prior_block


def test_linear_branch_scope_on_demo():
    p = create_demo_project()
    focus = p.chapters[-1].id
    scope = resolve_branch_memory_scope(p, chapter_id=focus)
    assert scope.mode in {"linear", "graph"}
    assert focus in scope.reachable_chapter_ids
    # 焦点章之前都应可达
    for c in p.chapters:
        assert c.id in scope.reachable_chapter_ids
        if c.id == focus:
            break


def test_other_route_foreshadow_isolated():
    p = create_demo_project()
    early = p.chapters[0].id
    late = p.chapters[-1].id
    ledger = get_ledger(p)
    ledger["foreshadows"] = [
        {
            "id": "f-early",
            "hook": "本线钩子雨声",
            "plantedChapter": early,
            "status": "open",
            "note": AUTO_FORESHADOW_NOTE,
        },
        {
            "id": "f-late",
            "hook": "他线钩子不该出现",
            "plantedChapter": late,
            "status": "open",
            "note": "他线",
        },
    ]
    p = set_ledger(p, ledger)
    # 焦点取首章：后章视为不可达（linear 前缀）
    scope = resolve_branch_memory_scope(p, chapter_id=early)
    filtered = filter_ledger_for_route(get_ledger(p), scope)
    hooks = [f.get("hook") for f in filtered.get("foreshadows") or []]
    assert "本线钩子雨声" in hooks
    others = filtered.get("_otherRouteForeshadows") or []
    if late not in scope.reachable_chapter_ids:
        assert any("他线" in str(f.get("hook")) for f in others)
        block = format_branch_memory_block(scope, filtered)
        assert "他线伏笔" in block


def test_foreshadow_graph_and_payoff_block():
    p = create_demo_project()
    ledger = get_ledger(p)
    ledger["foreshadows"] = [
        {
            "id": "f1",
            "hook": "钟楼上的灯",
            "plantedChapter": p.chapters[0].id,
            "status": "open",
            "note": AUTO_FORESHADOW_NOTE,
        }
    ]
    p = set_ledger(p, ledger)
    g = build_foreshadow_graph(p)
    assert g.open_count >= 1
    block = format_foreshadow_payoff_block(g, focus_chapter_id=p.chapters[1].id)
    assert "伏笔支付图" in block


def test_vn_bundle_assembles():
    p = create_demo_project()
    b = assemble_vn_write_bundle(p, chapter_id=p.chapters[0].id)
    assert "分支条件记忆" in b.lore_craft or "伏笔支付图" in b.lore_craft
    assert "可演场景硬约束" in b.framing_extra
    assert b.meta.get("branch")
    assert b.meta.get("intensity") == "full"


def test_vn_bundle_weak_assist_is_light():
    from app.core.writing_strategy import profile_from_assist

    p = create_demo_project()
    b = assemble_vn_write_bundle(
        p,
        chapter_id=p.chapters[0].id,
        strategy=profile_from_assist("weak"),
        writing_assist="weak",
        playtest_hints_block="## 试玩/结构改稿提示\n不应出现",
    )
    assert b.meta.get("intensity") == "light"
    assert "伏笔支付图" not in (b.lore_craft or "")
    assert "试玩/结构改稿提示" not in (b.framing_extra or "")
    assert "可演场景硬约束" in (b.framing_extra or "")


def test_scene_constraints_always_present():
    p = create_demo_project()
    text = format_vn_scene_constraints_block(p, chapter_id=p.chapters[0].id)
    assert "假选择" in text or "剧情代价" in text


def test_voice_prior_formatter_empty_ok():
    assert format_voice_write_prior_block([]) == ""


def test_vn_sota_suite_runs_on_demo():
    p = create_demo_project()
    suite = run_vn_sota_suite(p, chapter_id=p.chapters[0].id)
    assert suite["suite"] == "vn_ln_vertical_sota_v1"
    ids = {m["id"] for m in suite["metrics"]}
    assert "route_isolation" in ids
    assert "foreshadow_payoff_graph" in ids
    assert "playtest_hook_density" in ids
    assert suite["overall"] is None or isinstance(suite["overall"], float)
    assert "非通用 Arena" in (suite.get("disclaimer") or "")
    assert suite.get("weighted", {}).get("applied")


def test_vn_sota_overall_deterministic():
    from app.core.eval_vn_sota import build_overall_table

    p = create_demo_project()
    a = run_vn_sota_suite(p, chapter_id=p.chapters[0].id, seed=20260409)
    b = run_vn_sota_suite(p, chapter_id=p.chapters[0].id, seed=20260409)
    assert a["overall"] == b["overall"]
    table = build_overall_table(a)
    assert table["overall"] == a["overall"]
    assert any(r["id"] == "route_isolation" for r in table["rows"])


def test_vn_sota_ab_appendix_not_in_overall():
    from app.core.eval_vn_sota import attach_ab_appendix, compute_weighted_overall

    p = create_demo_project()
    base = run_vn_sota_suite(p, chapter_id=p.chapters[0].id)
    before = base["overall"]
    with_ab = attach_ab_appendix(
        base, ab_payload={"summary": {"tool": 0.9, "bare": 0.5}, "seed": 1}
    )
    assert with_ab["overall"] == before
    assert "abFiveDim" in (with_ab.get("appendix") or {})
    # 附录键不进权重表
    w = compute_weighted_overall(with_ab["metrics"])
    assert all(a["id"] != "abFiveDim" for a in w["applied"])
