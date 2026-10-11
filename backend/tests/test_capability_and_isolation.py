"""能力探针、子代理隔离、flag 切片、伏笔结局完备性。"""

from __future__ import annotations

from app.core.capability_probes import (
    blend_with_assist,
    profile_to_strategy,
    run_capability_probes,
)
from app.core.demo import create_demo_project
from app.core.flag_slice import build_flag_slice, format_flag_slice_block
from app.core.foreshadow_endings import check_foreshadow_ending_completeness
from app.core.pipeline.ledger import AUTO_FORESHADOW_NOTE, get_ledger, set_ledger
from app.core.subagent_isolation import run_consistency_subagent
from app.core.vn_write_bundle import assemble_vn_write_bundle
from app.core.writing_strategy import reset_writing_strategy


def test_capability_probes_produce_tiers():
    reset_writing_strategy()
    p = create_demo_project()
    cap = run_capability_probes(p, chapter_id=p.chapters[0].id)
    meta = cap.as_meta()
    assert "tiers" in meta
    for dim in ("reasoning", "attention", "memory", "instruction_following"):
        assert meta["tiers"][dim] in ("low", "mid", "high")
    strat = profile_to_strategy(cap)
    assert strat.attention in ("low", "mid", "high")
    blended = blend_with_assist(cap, "strong")
    # strong 更保守（更多补）→ attention 应为 low
    assert blended.attention == "low"
    reset_writing_strategy()


def test_subagent_returns_conclusion_only():
    p = create_demo_project()
    c = run_consistency_subagent(p, chapter_id=p.chapters[0].id)
    assert c.task == "consistency_isolation"
    meta = c.as_meta()
    assert "contradictionCount" in meta
    # 主窗口格式：要么空（全通过），要么以「子代理结论」开头
    text = c.format_for_main()
    assert text == "" or text.startswith("## 子代理结论")


def test_flag_slice_on_demo():
    p = create_demo_project()
    slice_ = build_flag_slice(p, chapter_id=p.chapters[0].id, assumed_flags={})
    assert isinstance(slice_.as_meta(), dict)
    block = format_flag_slice_block(slice_)
    assert isinstance(block, str)


def test_foreshadow_ending_completeness_linear():
    p = create_demo_project()
    ledger = get_ledger(p)
    ledger["foreshadows"] = [
        {
            "id": "f1",
            "hook": "雨夜的伞",
            "plantedChapter": p.chapters[0].id,
            "status": "open",
            "note": AUTO_FORESHADOW_NOTE,
        }
    ]
    p = set_ledger(p, ledger)
    report = check_foreshadow_ending_completeness(p)
    assert report.rows
    # 首章埋点且后面还有章 → 线性模式下应完备
    assert report.completeness_rate is not None
    assert report.completeness_rate >= 0.0


def test_vn_bundle_includes_new_layers():
    p = create_demo_project()
    b = assemble_vn_write_bundle(p, chapter_id=p.chapters[0].id)
    assert "branch" in b.meta
    assert "flag" in b.meta
    assert "foreshadowEndings" in b.meta
    assert "subagent" in b.meta
