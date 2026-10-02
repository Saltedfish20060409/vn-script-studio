"""P4.5：正文档引擎语法硬拒（shared fixture）。"""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from app.core.prose_engine_syntax import (
    PROSE_ENGINE_REJECT_MSG,
    line_has_engine_syntax,
    text_has_engine_syntax,
)

ROOT = Path(__file__).resolve().parents[2]
FIXTURE = ROOT / "shared" / "test-fixtures" / "engine_syntax_cases.json"


def _load_cases() -> dict:
    return json.loads(FIXTURE.read_text(encoding="utf-8"))


def _resolve_source(source: str) -> str:
    # e.g. docs/blindtest-runs/.../run.json#results.W08.content
    path_part, _, pointer = source.partition("#")
    data = json.loads((ROOT / path_part).read_text(encoding="utf-8"))
    cur: object = data
    for key in pointer.split("."):
        assert isinstance(cur, dict), source
        cur = cur[key]
    assert isinstance(cur, str), source
    return cur


def test_fixture_reject_cases():
    cases = _load_cases()
    for row in cases["reject"]:
        hit = text_has_engine_syntax(row["text"])
        assert hit is not None, row["id"]
        assert hit == row["hit"], (row["id"], hit, row["hit"])


def test_fixture_allow_cases_including_w08_w09():
    cases = _load_cases()
    for row in cases["allow"]:
        text = row.get("text")
        if not text and row.get("source"):
            text = _resolve_source(row["source"])
        assert text is not None, row["id"]
        assert text_has_engine_syntax(text) is None, row["id"]


def test_known_false_positives_still_hit():
    cases = _load_cases()
    for row in cases["known_false_positives"]:
        hit = text_has_engine_syntax(row["text"])
        assert hit == row["rule"], (row["id"], hit)


def test_reject_message_is_frozen():
    cases = _load_cases()
    assert cases["messages"]["append_replace"] == PROSE_ENGINE_REJECT_MSG


def test_line_scene_chinese_arg_not_hit():
    assert line_has_engine_syntax("scene 这个词很少有人当真。") is None
    assert line_has_engine_syntax("show 不要 tell，她只把伞递过去。") is None
