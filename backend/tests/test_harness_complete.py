"""Harness completeness — beats, full audit, apply draft, ledger emotion."""
from __future__ import annotations

from app.core.harness.audit_full import full_audit_draft
from app.core.pipeline.apply_draft import (
    apply_draft_to_chapter,
    extract_script_body,
    plain_text_to_raw_blocks,
)
from app.core.pipeline.beat_check import lint_beat_sheet
from app.core.pipeline.ledger import digest_chapter_into_ledger, get_ledger
from app.core.pipeline.orchestrator import stage_check
from app.domain.types import Character, SceneChapter, StoryBible, VnProject


def _mini_project(*, script: str = "") -> VnProject:
    blocks = plain_text_to_raw_blocks(script) if script else []
    return VnProject(
        id="p1",
        title="t",
        logline="",
        updatedAt="2026-01-01T00:00:00Z",
        bible=StoryBible(),
        characters=[
            Character(
                id="c1",
                defineName="aya",
                displayName="绫",
                relationships="与主角同学",
            )
        ],
        chapters=[
            SceneChapter(
                id="ch1",
                title="第一章",
                blocks=blocks,
            )
        ],
        locations=[],
        locationLinks=[],
    )


def test_full_audit_includes_style_flag():
    out = full_audit_draft('绫: "你好。"\n')
    assert "issues" in out
    assert out.get("styleSkill") is True
    assert "pass" in out


def test_beat_coverage_error_when_none_match():
    sheet = {
        "goal": "车站告白",
        "beats": [
            {"name": "相遇", "action": "雨夜车站重逢"},
            {"name": "误会", "action": "伞被风吹走"},
            {"name": "告白", "action": "说出喜欢"},
        ],
        "triggers": ["红伞"],
    }
    draft = '绫: "今天天气不错。"\n旁白: 阳光很好。\n'
    issues = lint_beat_sheet(draft, sheet)
    codes = {i.code for i in issues}
    assert "beats_coverage" in codes
    assert any(i.code == "beat_missing" for i in issues)


def test_beat_coverage_pass_when_keywords_present():
    sheet = {
        "goal": "车站重逢",
        "beats": [
            {"name": "车站", "action": "雨夜在车站相遇"},
            {"name": "伞", "action": "红伞被风吹走"},
        ],
        "triggers": ["红伞"],
    }
    draft = (
        "旁白: 雨夜的车站灯火摇曳。\n"
        '绫: "你的红伞！"\n'
        "旁白: 伞被风吹走，两人追着跑。\n"
    )
    issues = lint_beat_sheet(draft, sheet)
    assert not any(i.code == "beats_coverage" for i in issues)


def test_stage_check_merges_beats():
    sheet = {
        "goal": "测试",
        "beats": [
            {"name": "甲事件", "action": "打开古旧铁盒"},
            {"name": "乙事件", "action": "发现泛黄信件"},
        ],
    }
    chk = stage_check('绫: "随便说一句。"\n', beat_sheet=sheet)
    assert chk.get("beatChecked") is True
    assert chk["errorCount"] >= 1
    assert any(i.get("code") == "beats_coverage" for i in chk["issues"])


def test_extract_script_body_prefers_fence():
    raw = "仍须注意：去说明书腔。\n\n```renpy\n绫: \"改好了。\"\n```\n"
    assert '绫: "改好了。"' in extract_script_body(raw)


def test_apply_draft_replaces_chapter_blocks():
    vn = _mini_project(script='旧: "旧稿"')
    vn2 = apply_draft_to_chapter(vn, "ch1", '绫: "新稿写入。"\n旁白: ok')
    ch = next(c for c in vn2.chapters if c.id == "ch1")
    texts = []
    for b in ch.blocks:
        if b.get("type") == "dialogue":
            texts.append(b.get("text") or "")
        elif b.get("type") == "narration":
            texts.append(b.get("text") or "")
        elif b.get("type") == "raw":
            texts.append(b.get("code") or "")
    joined = "\n".join(texts)
    assert "新稿写入" in joined
    assert "旧稿" not in joined


def test_ledger_emotion_not_placeholder():
    vn = _mini_project(
        script='绫: "为什么会这样？！"\n旁白: 雨还在下。\n'
    )
    ledger = digest_chapter_into_ledger(vn, "ch1")
    states = [s for s in ledger["characterStates"] if s.get("characterName") == "绫"]
    assert states
    assert states[0]["emotion"] != "（待流水线充实）"
    assert states[0]["emotion"] in {"激动", "疑惑", "平静", "低落", "愉悦", "担忧"}


def test_get_ledger_roundtrip_empty():
    vn = _mini_project()
    assert get_ledger(vn)["chapterFacts"] == []
