"""策略抬档 JSONL 落盘。"""

from __future__ import annotations

from pathlib import Path

from app.core.strategy_adapt_log import (
    append_strategy_adapt_event,
    read_recent_events,
)


def test_append_and_read(tmp_path: Path):
    path = append_strategy_adapt_event(
        project_id="demo-proj",
        chapter_id="ch1",
        write_op="continue",
        adapt={
            "changed": True,
            "suggestedAssist": "strong",
            "attention": "low",
            "memory": "low",
            "reasoning": "mid",
            "reasons": ["本场守卫/写后闸未通过"],
        },
        log_dir=tmp_path,
    )
    assert path
    assert Path(path).is_file()
    rows = read_recent_events("demo-proj", limit=5, log_dir=tmp_path)
    assert len(rows) == 1
    assert rows[0]["changed"] is True
    assert rows[0]["suggestedAssist"] == "strong"


def test_empty_adapt_skipped(tmp_path: Path):
    assert (
        append_strategy_adapt_event(
            project_id="x", adapt={}, log_dir=tmp_path
        )
        is None
    )
