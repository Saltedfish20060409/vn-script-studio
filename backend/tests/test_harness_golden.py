"""Golden regression for full_audit + keyword beat checks."""
from __future__ import annotations

import json
from pathlib import Path

from app.core.harness.audit_full import full_audit_draft
from app.core.pipeline.orchestrator import stage_check

FIX = Path(__file__).resolve().parent / "fixtures" / "harness_golden.json"


def _load_cases():
    data = json.loads(FIX.read_text(encoding="utf-8"))
    return data["cases"]


def test_golden_audit_and_beats():
    cases = _load_cases()
    assert len(cases) >= 30
    for case in cases:
        draft = case["draft"]
        sheet = case.get("beatSheet")
        if sheet:
            result = stage_check(draft, beat_sheet=sheet)
        else:
            result = full_audit_draft(draft)
        codes = {i.get("code") for i in (result.get("issues") or []) if isinstance(i, dict)}
        if case.get("expectPass") is True:
            assert result.get("pass") is True, f"{case['id']} expected pass, got {codes}"
        if case.get("expectPass") is False:
            assert result.get("pass") is False, f"{case['id']} expected fail, got {codes}"
        for code in case.get("requireCodes") or []:
            assert code in codes, f"{case['id']} missing required code {code}; have {codes}"
        for code in case.get("forbidCodes") or []:
            assert code not in codes, f"{case['id']} unexpected code {code}"


def test_resolve_beat_issues_keyword_only_no_config():
    import asyncio

    from app.core.pipeline.beat_check import resolve_beat_issues

    sheet = {
        "beats": [
            {"name": "甲", "action": "打开铁盒"},
            {"name": "乙", "action": "读信件"},
        ]
    }
    issues = asyncio.run(
        resolve_beat_issues("绫: 「今天好晴。」", sheet, config=None, semantic=True)
    )
    assert any(i.code == "beats_coverage" for i in issues)
