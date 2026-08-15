"""Agent loop tools — project-scoped only."""

from __future__ import annotations

from app.core.agent_loop import _normalize_tool_calls, _parse_loop_json
from app.core.agent_tools import run_agent_tool, tool_catalog_for_prompt
from app.domain.types import VnProject


def _demo() -> VnProject:
    return VnProject.model_validate(
        {
            "id": "p1",
            "title": "雨夜",
            "updatedAt": "2026-01-01T00:00:00Z",
            "characters": [
                {
                    "id": "c1",
                    "defineName": "linxia",
                    "displayName": "霖夏",
                    "voice": "克制",
                    "bio": "雨夜车站的人",
                }
            ],
            "chapters": [
                {
                    "id": "ch1",
                    "title": "车站",
                    "blocks": [
                        {"type": "narration", "text": "雨很大。"},
                        {
                            "type": "dialogue",
                            "characterId": "c1",
                            "text": "伞借你。",
                        },
                    ],
                }
            ],
            "bible": {"world": "近未来雨城", "outline": "车站邂逅"},
            "locations": [{"id": "l1", "name": "车站", "description": "夜雨"}],
        }
    )


def test_tool_catalog_mentions_no_shell():
    cat = tool_catalog_for_prompt()
    assert "get_chapter" in cat
    assert "shell" not in cat.lower() or "禁止" in cat


def test_get_chapter_and_search():
    p = _demo()
    ok, text = run_agent_tool("get_chapter", {}, project=p, chapter_id="ch1")
    assert ok
    assert "伞借你" in text or "雨" in text
    ok2, hits = run_agent_tool(
        "search_script", {"query": "伞"}, project=p, chapter_id="ch1"
    )
    assert ok2
    assert "伞" in hits


def test_get_character_and_bible():
    p = _demo()
    ok, text = run_agent_tool("get_character", {"ref": "霖夏"}, project=p)
    assert ok and "霖夏" in text
    ok2, bible = run_agent_tool("get_bible", {}, project=p)
    assert ok2 and "雨城" in bible
    ok3, sb = run_agent_tool("search_bible", {"query": "车站"}, project=p)
    assert ok3 and "车站" in sb


def test_lint_draft_runs():
    p = _demo()
    ok, out = run_agent_tool(
        "lint_draft",
        {"text": '旁白 "你好。"\n霖夏 "嗯。"'},
        project=p,
    )
    assert ok
    assert "体检" in out or "问题" in out or "通过" in out


def test_parse_loop_json_tool_calls():
    raw = '{"message":"先查","tool_calls":[{"id":"t1","name":"get_chapter","arguments":{}}],"done":false}'
    parsed = _parse_loop_json(raw)
    calls = _normalize_tool_calls(parsed.get("tool_calls"))
    assert len(calls) == 1
    assert calls[0]["name"] == "get_chapter"


def test_legacy_actions_only_means_done_path():
    raw = '{"message":"这是意见","actions":[]}'
    parsed = _parse_loop_json(raw)
    calls = _normalize_tool_calls(parsed.get("tool_calls"))
    assert calls == []
