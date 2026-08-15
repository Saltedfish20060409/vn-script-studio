"""P2: chapterIndex refresh."""
from __future__ import annotations

from app.core.chapter_digest import refresh_chapter_index
from app.core.demo import create_demo_project


def test_refresh_chapter_index_fills_hashes():
    p = create_demo_project()
    out = refresh_chapter_index(p)
    assert out.chapterIndex
    assert len(out.chapterIndex) == len(out.chapters)
    first = out.chapterIndex[0]
    assert first.chapterId == out.chapters[0].id
    assert first.hash
    assert first.title
