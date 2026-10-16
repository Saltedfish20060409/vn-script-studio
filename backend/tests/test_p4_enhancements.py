"""P4：语义重排 / 全局记忆 graded / 小分类器 / 子代理契约。"""

from __future__ import annotations

import os

from app.core.demo import create_demo_project
from app.core.global_memory import build_global_memory, format_global_memory_for_agent
from app.core.pipeline.ledger import get_ledger, set_ledger
from app.core.semantic_search import lexical_overlap_score, rerank_texts
from app.core.subagent_isolation import llm_subagent_enabled, run_consistency_subagent
from app.core.vn_classifiers import (
    classify_dead_character_in_text,
    classify_foreshadow_pressure,
    run_local_classifiers,
)
from app.core.write_hybrid import collect_hybrid_hits


def test_lexical_rerank_boosts_overlap():
    hits = [
        ("远", "完全无关的厨房菜谱", 0.9),
        ("近", "雨夜月台末班车停靠", 0.5),
    ]
    out = rerank_texts("雨夜 月台", hits, alpha=0.6)
    assert out[0][0] == "近"
    assert lexical_overlap_score("雨夜", "雨夜车站") > 0.0


def test_hybrid_still_works_with_rerank():
    p = create_demo_project()
    hits = collect_hybrid_hits(p, "雨夜 月台", limit=4)
    assert isinstance(hits, list)


def test_global_memory_graded_shorter_or_equal():
    p = create_demo_project()
    mem = build_global_memory(p)
    full = format_global_memory_for_agent(mem, graded=False)
    graded = format_global_memory_for_agent(mem, graded=True)
    assert graded
    # graded 预算更紧；内容不应显著更长
    assert len(graded) <= len(full) + 40


def test_graded_volume_keeps_state_change():
    from app.core.world_state import make_fact

    p = create_demo_project()
    first = (p.chapters or [None])[0]
    assert first is not None
    ledger = dict(p.writingLedger or {})
    ledger["worldState"] = {
        "schemaVersion": 1,
        "facts": [
            make_fact(
                subject="林夏",
                relation="status",
                value="alive",
                chapter_id=first.id,
                chapter_index=0,
                valid_to=0,
                fact_id="alive",
            ),
            make_fact(
                subject="林夏",
                relation="status",
                value="dead",
                chapter_id=first.id,
                chapter_index=0,
                quote="身亡",
                fact_id="dead",
            ),
        ],
    }
    p = set_ledger(p, ledger)
    graded = format_global_memory_for_agent(
        build_global_memory(p), graded=True, max_chars=8000
    )
    assert "林夏.status：原为 alive，现为 dead" in graded


def test_dead_character_classifier():
    p = create_demo_project()
    name = (
        (p.characters[0].displayName if p.characters else "林夏") or "林夏"
    )
    ledger = get_ledger(p)
    ledger["characterStates"] = [
        {
            "characterId": p.characters[0].id if p.characters else "c1",
            "characterName": name,
            "body": "已死亡",
            "emotion": "—",
        }
    ]
    p = set_ledger(p, ledger)
    hits = classify_dead_character_in_text(p, f"{name}忽然出现在门口。")
    assert any(h["code"] == "dead_character_present" for h in hits)


def test_foreshadow_pressure_classifier(monkeypatch):
    p = create_demo_project()
    monkeypatch.setattr(
        "app.core.pipeline.ledger._foreshadow_rows",
        lambda ledger, chapters: [
            {
                "id": "f-old",
                "hook": "古老的钟声",
                "status": "open",
                "ageChapters": 8,
            }
        ],
    )
    hits = classify_foreshadow_pressure(p)
    assert any("高压伏笔" in h["message"] for h in hits)


def test_local_classifiers_bundle():
    p = create_demo_project()
    out = run_local_classifiers(p, chapter_id=p.chapters[0].id)
    assert "ok" in out
    assert isinstance(out["errors"], list)


def test_subagent_default_local_no_llm():
    os.environ.pop("VNSS_LLM_SUBAGENT", None)
    assert llm_subagent_enabled() is False
    p = create_demo_project()
    c = run_consistency_subagent(p, chapter_id=p.chapters[0].id, use_llm=False)
    assert c.meta.get("mode") in {"local", "timeout", "error"}
    assert "llm" not in (c.meta.get("mode") or "")


def test_strategy_adapt_log_off(monkeypatch, tmp_path):
    from app.core.strategy_adapt_log import append_strategy_adapt_event

    monkeypatch.setenv("VNSS_STRATEGY_ADAPT_LOG", "off")
    assert (
        append_strategy_adapt_event(
            project_id="p",
            adapt={"changed": True, "suggestedAssist": "strong"},
            log_dir=tmp_path,
        )
        is None
    )
