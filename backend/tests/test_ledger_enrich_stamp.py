"""A1：LLM enrich 入库后 stamp sourceHash，auto_digest 不得抹掉 enrich。"""

from __future__ import annotations

from app.core.chapter_digest import chapter_content_hash
from app.core.demo import create_demo_project
from app.core.pipeline.ledger import (
    auto_digest_ledger,
    digest_chapter_into_ledger,
    get_ledger,
    set_ledger,
)


def test_llm_enrich_survives_auto_digest():
    p = create_demo_project()
    ch = p.chapters[0]
    enrich_facts = ["LLM专属事实：主角的剑已断", "关系：与配角已决裂"]
    ledger = digest_chapter_into_ledger(p, ch.id, llm_facts=enrich_facts)
    p = set_ledger(p, ledger)

    row = next(f for f in get_ledger(p)["chapterFacts"] if f["chapterId"] == ch.id)
    assert row.get("sourceHash") == chapter_content_hash(ch)
    assert "LLM专属事实：主角的剑已断" in row["facts"]

    # 正文未变 → auto_digest 应跳过该章，保留 enrich
    again = auto_digest_ledger(p)
    row2 = next(
        f for f in get_ledger(again)["chapterFacts"] if f["chapterId"] == ch.id
    )
    assert "LLM专属事实：主角的剑已断" in row2["facts"]
    assert row2["sourceHash"] == chapter_content_hash(ch)
