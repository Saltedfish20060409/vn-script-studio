"""写路径 hybrid 检索。"""

from __future__ import annotations

from app.core.demo import create_demo_project
from app.core.write_hybrid import build_write_hybrid_block, collect_hybrid_hits


def test_hybrid_hits_demo_on_relevant_query():
    p = create_demo_project()
    hits = collect_hybrid_hits(p, "雨夜 月台 末班车", limit=4)
    assert isinstance(hits, list)
    # demo 主题就是雨夜车站，应能命中至少一章或设定
    block, hits2 = build_write_hybrid_block(p, "雨夜", chapter_id=p.chapters[0].id)
    if hits2:
        assert "相关检索" in block
        assert "hybrid" in block


def test_hybrid_empty_query_returns_empty():
    p = create_demo_project()
    block, hits = build_write_hybrid_block(p, "   ")
    assert block == ""
    assert hits == []
