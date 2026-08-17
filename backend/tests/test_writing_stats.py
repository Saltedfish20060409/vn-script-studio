"""Unit tests: writing stats (pure logic, no DB)."""

from __future__ import annotations

from app.domain.types import VnProject
from app.services.writing_stats import (
    chapter_metrics,
    count_blocks_words,
    count_words,
)


def test_count_words_cjk_and_latin():
    assert count_words("雨夜，末班车从站台缓缓开出。") == 12
    assert count_words("hello world 2024") == 3
    assert count_words("") == 0


def test_count_blocks_words_counts_prose_and_dialogue():
    blocks = [
        {"type": "narration", "text": "雨夜，末班车从站台缓缓开出。"},
        {"type": "dialogue", "characterId": "lx", "text": "我们走吧"},
        {"type": "scene", "image": "bg station"},  # not counted
        {"type": "label", "name": "start"},  # not counted
    ]
    assert count_blocks_words(blocks) == 12 + 4


def test_chapter_metrics_summary():
    vn = VnProject.model_validate(
        {
            "id": "proj-x",
            "title": "t",
            "updatedAt": "2026-01-01T00:00:00+00:00",
            "chapters": [
                {
                    "id": "ch1",
                    "title": "第一章",
                    "blocks": [
                        {"type": "narration", "text": "雨夜，末班车从站台缓缓开出。"},
                        {"type": "dialogue", "characterId": "lx", "text": "我们走吧"},
                    ],
                }
            ],
        }
    )
    m = chapter_metrics(vn)
    assert len(m) == 1
    row = m[0]
    assert row["index"] == 1
    assert row["words"] == 16
    assert row["lines"] == 2
    assert row["dialogueWords"] == 4
    assert row["dialogueRatio"] == round(4 / 16, 3)
    assert row["speakers"] == ["lx"]


def test_chapter_metrics_dialogue_ratio_zero_for_no_prose():
    vn = VnProject.model_validate(
        {
            "id": "p",
            "title": "t",
            "updatedAt": "2026-01-01T00:00:00+00:00",
            "chapters": [{"id": "c", "title": "T", "blocks": [{"type": "label", "name": "s"}]}],
        }
    )
    m = chapter_metrics(vn)
    assert m[0]["words"] == 0
    assert m[0]["dialogueRatio"] == 0
