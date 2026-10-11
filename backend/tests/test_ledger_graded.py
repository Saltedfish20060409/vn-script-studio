"""账本分级压缩：邻章详、远端一行。"""

from __future__ import annotations

from app.core.demo import create_demo_project
from app.core.pipeline.ledger import (
    auto_digest_ledger,
    format_ledger_for_agent,
    get_ledger,
)


def test_graded_ledger_marks_tiers():
    p = auto_digest_ledger(create_demo_project())
    ledger = get_ledger(p)
    plain = format_ledger_for_agent(ledger, chapters=p.chapters)
    graded = format_ledger_for_agent(
        ledger,
        chapters=p.chapters,
        focus_chapter_id=p.chapters[-1].id,
        graded=True,
    )
    assert "分级压缩" in graded or "锚点" in graded or "邻章" in graded
    assert "写作账本" in plain
    # 分级版不应比无限制版离谱地更长（有压缩意图）
    assert len(graded) <= len(plain) + 200
