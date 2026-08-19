"""Deterministic NL → RPY parse (no LLM)."""

import asyncio

from app.core.prose_rpy import generate_rpy_from_prose, parse_prose_to_blocks
from app.domain.types import Character, VnProject


def test_parse_colon_dialogue():
    people = [Character(id="lx", defineName="lx", displayName="林夏")]
    blocks = parse_prose_to_blocks("林夏：末班车已经开走了。\n雨还在下。", people)
    types = [b["type"] for b in blocks]
    assert "label" in types
    assert any(t in types for t in ("dialogue", "narration", "raw"))


def test_generate_without_llm():
    vn = VnProject.model_validate(
        {
            "id": "p",
            "title": "t",
            "updatedAt": "2026-01-01T00:00:00+00:00",
            "characters": [{"id": "lx", "defineName": "lx", "displayName": "林夏"}],
            "chapters": [{"id": "ch1", "title": "一", "blocks": []}],
        }
    )
    rpy, blocks = asyncio.run(
        generate_rpy_from_prose(vn, "林夏：你好。\n雨还在下。", None, use_llm=False)
    )
    assert blocks
    blob = rpy + "".join(str(b.get("text") or b.get("code") or "") for b in blocks)
    assert "你好" in blob
