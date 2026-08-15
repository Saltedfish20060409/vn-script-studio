"""Agent loop SSE event emission (streaming hook)."""
from __future__ import annotations

import asyncio

from app.core.ai import DeepSeekConfig
from app.core.agent_loop import run_agent_loop
from app.domain.types import AgentRequest, VnProject


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
                        {"type": "dialogue", "characterId": "c1", "text": "伞借你。"},
                    ],
                }
            ],
            "bible": {"world": "近未来雨城", "outline": "车站邂逅"},
            "locations": [{"id": "l1", "name": "车站", "description": "夜雨"}],
        }
    )


def test_agent_loop_emits_stream_events(monkeypatch):
    from app.core import agent_loop as al

    events: list[dict] = []

    async def sink(evt: dict) -> None:
        events.append(evt)

    async def fake_chat_json(provider, *, temperature, messages):
        return '{"message":"先看设定与当前章。","actions":[],"tool_calls":[],"done":true}'

    monkeypatch.setattr(al, "_chat_json", fake_chat_json)
    cfg = DeepSeekConfig(apiKey="test-key", baseUrl="http://x", model="m")
    req = AgentRequest(
        project=_demo(),
        messages=[{"role": "user", "content": "续写"}],  # type: ignore[arg-type]
        task="continue",
    )

    async def _run():
        return await run_agent_loop(cfg, req, on_event=sink)

    res = asyncio.run(_run())

    types = [e["type"] for e in events]
    assert "task" in types
    assert "thought" in types
    assert types[-1] == "done"
    done = events[-1]
    assert done.get("result", {}).get("message")
    assert res.message
    assert "先看设定" in res.message


def test_agent_loop_events_include_actions(monkeypatch):
    from app.core import agent_loop as al

    events: list[dict] = []

    async def sink(evt: dict) -> None:
        events.append(evt)

    async def fake_chat_json(provider, *, temperature, messages):
        return (
            '{"message":"写入剧本。","actions":[{"op":"append_script",'
            '"chapterRef":"ch1","text":"霖夏 \\"……又来一场雨。\\""}],'
            '"tool_calls":[],"done":true}'
        )

    monkeypatch.setattr(al, "_chat_json", fake_chat_json)
    cfg = DeepSeekConfig(apiKey="test-key", baseUrl="http://x", model="m")
    req = AgentRequest(
        project=_demo(),
        messages=[{"role": "user", "content": "续写"}],  # type: ignore[arg-type]
        task="continue",
    )

    async def _run():
        return await run_agent_loop(cfg, req, on_event=sink)

    res = asyncio.run(_run())

    types = [e["type"] for e in events]
    assert "actions" in types
    actions_evt = next(e for e in events if e["type"] == "actions")
    assert actions_evt.get("actions")
    assert res.actions
    assert res.actions[0]["op"] == "append_script"
