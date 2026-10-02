"""P5 condense 钩子优先：framing + W05 fixture 检查器。"""

from __future__ import annotations

import json
from pathlib import Path

from app.core.capability_router import CONDENSE_HOOK_PRIORITY, write_op_framing
from app.core.pipeline.condense_hook_contract import (
    assert_condense_keeps_hooks,
    missing_retained_phrases,
)

FIXTURE = (
    Path(__file__).resolve().parents[2]
    / "shared"
    / "test-fixtures"
    / "condense_hook_w05.json"
)


def _load_w05():
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def test_condense_framing_includes_hook_priority():
    frame = write_op_framing("condense")
    assert CONDENSE_HOOK_PRIORITY in frame
    assert "钩子" in frame


def test_w05_fixture_must_retain_present_in_sample():
    data = _load_w05()
    prose = data["sample_prose"]
    for phrase in data["must_retain"]:
        assert phrase in prose


def test_w05_checker_passes_when_hook_kept():
    data = _load_w05()
    before = data["sample_prose"]
    # 模拟合法缩写：丢掉铺陈，保留钩子
    after = (
        "她袖口湿透。雨里有人叫了她的旧名字。她没有回头。"
    )
    assert missing_retained_phrases(before, after, data["must_retain"]) == []
    assert_condense_keeps_hooks(before, after, data["must_retain"])


def test_w05_checker_fails_when_hook_stripped():
    data = _load_w05()
    before = data["sample_prose"]
    # P2.5 观察项：缩写把钩子压掉
    after = "路灯照着积水。她把伞挪了挪，没有回头。"
    lost = missing_retained_phrases(before, after, data["must_retain"])
    assert lost == data["must_retain"]
