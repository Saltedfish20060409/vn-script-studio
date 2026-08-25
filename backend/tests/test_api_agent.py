"""API tests: POST /projects/{id}/agent and POST /projects/{id}/agent/stream.

LLM is fully mocked via unittest.mock.patch on `app.api.v1.projects.run_agent`;
everything else (action apply → DB, undo stack, conversation rows, SSE framing)
is real.
"""

from __future__ import annotations

import asyncio
import json
from unittest.mock import patch

import db_gate
import pytest

from app.domain.types import AgentResponse

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(
        not db_gate.DB_AVAILABLE,
        reason="PostgreSQL test DB unreachable (set DATABASE_URL_TEST)",
    ),
]

APP = db_gate.make_app()

PATCH_TARGET = "app.api.v1.projects.run_agent"

MESSAGE = [{"role": "user", "content": "帮我把霖夏的台词改得冷静一些"}]

UPDATE_VOICE_ACTION = {
    "op": "update_character",
    "ref": "linxia",
    "patch": {"voice": "冷静克制，短句"},
}

BAD_ACTION = {"op": "add_character", "displayName": ""}  # always skipped → warning


def _run(coro):
    return asyncio.run(coro)


async def _create_demo_project(client, headers, title="Agent 测试项目") -> str:
    r = await client.post(
        "/api/v1/projects", json={"title": title, "from_demo": True}, headers=headers
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_agent_run_applies_actions_and_persists():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "agent_user")
            pid = await _create_demo_project(client, headers)

            async def fake_run_agent(config, request, *, on_event=None):
                return AgentResponse(
                    message="已按人设调整霖夏的台词风格。",
                    actions=[UPDATE_VOICE_ACTION, BAD_ACTION],
                    model="test-model",
                )

            with patch(PATCH_TARGET, new=fake_run_agent):
                r = await client.post(
                    f"/api/v1/projects/{pid}/agent",
                    json={"messages": MESSAGE, "apply_actions": True},
                    headers=headers,
                )
            assert r.status_code == 200, r.text
            body = r.json()

            # apply_actions wrote the project row
            assert body["applied"] is True
            assert body["message"].startswith("已按人设")
            assert body["model"] == "test-model"
            # the invalid action surfaced as a warning
            assert any("add_character 缺少" in w for w in body["warnings"])
            # a conversation row was created
            conv_id = body["conversation_id"]
            assert conv_id

            chars = {c["id"]: c for c in body["project"]["characters"]}
            assert chars["linxia"]["voice"] == "冷静克制，短句"

            # DB: project JSONB is actually updated
            r = await client.get(f"/api/v1/projects/{pid}", headers=headers)
            assert r.status_code == 200
            chars = {c["id"]: c for c in r.json()["characters"]}
            assert chars["linxia"]["voice"] == "冷静克制，短句"

            # DB: conversation persisted with undo_stack entry
            r = await client.get(
                f"/api/v1/projects/{pid}/agent/conversations", headers=headers
            )
            assert r.status_code == 200
            convs = r.json()
            assert len(convs) == 1
            assert convs[0]["id"] == conv_id

            r = await client.get(
                f"/api/v1/projects/{pid}/agent/conversations/{conv_id}",
                headers=headers,
            )
            assert r.status_code == 200
            conv = r.json()
            assert conv["title"] == "帮我把霖夏的台词改得冷静一些"
            assert len(conv["undo_stack"]) == 1
            assert conv["undo_stack"][0]["title"] == "Agent 测试项目"

    _run(_scenario())


def test_agent_run_without_actions_is_readonly():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "agent_ro")
            pid = await _create_demo_project(client, headers)

            async def fake_run_agent(config, request, *, on_event=None):
                return AgentResponse(
                    message="只是建议，未改动工程。",
                    actions=[],
                    model="test-model",
                )

            with patch(PATCH_TARGET, new=fake_run_agent):
                r = await client.post(
                    f"/api/v1/projects/{pid}/agent",
                    json={"messages": MESSAGE, "apply_actions": False},
                    headers=headers,
                )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["applied"] is False
            assert body["project"]["title"] == "Agent 测试项目"

            # conversation still created for chat continuity
            r = await client.get(
                f"/api/v1/projects/{pid}/agent/conversations", headers=headers
            )
            assert len(r.json()) == 1

    _run(_scenario())


def test_agent_stream_sse_events_and_final():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "stream_user")
            pid = await _create_demo_project(client, headers)

            async def fake_stream_agent(config, request, *, on_event=None):
                assert on_event is not None  # endpoint passes the queue sink
                await on_event({"type": "task", "text": "分析当前章节"})
                await on_event({"type": "thought", "text": "霖夏应保持克制"})
                await on_event({"type": "done", "result": {"message": "流式完成"}})
                return AgentResponse(
                    message="流式完成。",
                    actions=[UPDATE_VOICE_ACTION],
                    model="test-model",
                )

            with patch(PATCH_TARGET, new=fake_stream_agent):
                r = await client.post(
                    f"/api/v1/projects/{pid}/agent/stream",
                    json={"messages": MESSAGE, "apply_actions": True},
                    headers=headers,
                )

            assert r.status_code == 200, r.text
            assert "text/event-stream" in r.headers.get("content-type", "")

            events = []
            for line in r.text.splitlines():
                if line.startswith("data: "):
                    events.append(json.loads(line[len("data: "):]))

            types = [e["type"] for e in events]
            assert "task" in types
            assert "thought" in types
            assert "done" in types
            assert types[-1] == "final"

            final = events[-1]
            result = final["result"]
            assert result["applied"] is True
            assert result["message"] == "流式完成。"
            # final event carries the persisted project (voice patched)
            chars = {c["id"]: c for c in result["project"]["characters"]}
            assert chars["linxia"]["voice"] == "冷静克制，短句"

            # DB: conversation exists with an undo entry from the stream run
            r = await client.get(
                f"/api/v1/projects/{pid}/agent/conversations", headers=headers
            )
            convs = r.json()
            assert len(convs) == 1
            conv_id = convs[0]["id"]
            r = await client.get(
                f"/api/v1/projects/{pid}/agent/conversations/{conv_id}",
                headers=headers,
            )
            assert len(r.json()["undo_stack"]) == 1

    _run(_scenario())


def test_agent_stream_mid_loop_failure_surfaces_error_not_hang():
    """回归：runner 中途抛错（如上游 404/超时）时，流必须发 error 事件并结束，
    而不是 keepalive 死循环让前端永远卡在"正在检索设定"。
    """

    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "stream_fail_user")
            pid = await _create_demo_project(client, headers)

            async def failing_agent(config, request, *, on_event=None):
                await on_event({"type": "task", "text": "分析当前章节"})
                raise RuntimeError("DeepSeek API 404: not found (mock)")

            with patch(PATCH_TARGET, new=failing_agent):
                r = await client.post(
                    f"/api/v1/projects/{pid}/agent/stream",
                    json={"messages": MESSAGE, "apply_actions": True},
                    headers=headers,
                )

            assert r.status_code == 200, r.text
            events = []
            for line in r.text.splitlines():
                if line.startswith("data: "):
                    events.append(json.loads(line[len("data: "):]))
            types = [e["type"] for e in events]
            assert "task" in types
            assert "error" in types, f"expected error event, got {types}"
            assert "404" in events[-1]["message"]
            assert types[-1] == "error"  # 流以 error 收尾，不 keepalive 悬挂

    _run(_scenario())
