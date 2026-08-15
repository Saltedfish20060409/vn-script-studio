"""P2: voiceReports persist + stale."""
from __future__ import annotations

from app.core.chapter_digest import chapter_content_hash
from app.core.demo import create_demo_project
from app.core.voice_reports import mark_voice_reports_stale, persist_voice_report


def test_persist_and_stale_on_edit():
    p = create_demo_project()
    cid = p.chapters[0].id
    p = persist_voice_report(
        p,
        chapter_id=cid,
        summary="稳",
        issues=[],
        model="test",
    )
    assert p.voiceReports
    assert p.voiceReports[-1]["stale"] is False
    fp = p.voiceReports[-1]["fingerprint"]
    assert fp == chapter_content_hash(p.chapters[0])

    # Mutate chapter → mark stale
    blocks = list(p.chapters[0].blocks) + [
        {"type": "narration", "text": "新旁白触发指纹变化"}  # type: ignore[list-item]
    ]
    ch = p.chapters[0].model_copy(update={"blocks": blocks})
    chapters = [ch] + list(p.chapters[1:])
    edited = p.model_copy(update={"chapters": chapters})
    stale_p = mark_voice_reports_stale(edited)
    assert stale_p.voiceReports[-1]["stale"] is True
