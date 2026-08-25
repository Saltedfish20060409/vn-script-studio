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


@pytest.fixture(scope="module", autouse=True)
def _ensure_run_state_column():
    """已存在的测试库不会走 create_all 增列——幂等补列（与 0024 迁移一致）。"""
    from sqlalchemy import text

    async def _run():
        async with db_gate.engine.begin() as conn:
            await conn.execute(
                text(
                    "ALTER TABLE agent_sessions "
                    "ADD COLUMN IF NOT EXISTS run_state JSONB"
                )
            )

    asyncio.run(_run())
    yield


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

            async def fake_run_agent(
                config, request, *, on_event=None, on_checkpoint=None, resume=None
            ):
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

            async def fake_stream_agent(
                config, request, *, on_event=None, on_checkpoint=None, resume=None
            ):
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

            async def failing_agent(
                config, request, *, on_event=None, on_checkpoint=None, resume=None
            ):
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


def test_agent_stream_resume_continues_from_checkpoint():
    """执行状态持久化：中途失败 → run_state=error → resume 从检查点续跑。"""

    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "stream_resume_user")
            pid = await _create_demo_project(client, headers)

            async def failing_agent(
                config, request, *, on_event=None, on_checkpoint=None, resume=None
            ):
                assert on_event is not None
                await on_event({"type": "task", "text": "先读章节"})
                # 模拟执行快照（检查点落库的依据）
                if on_checkpoint is not None:
                    await on_checkpoint(
                        {
                            "status": "running",
                            "step": 1,
                            "steps": 3,
                            "task": "chat",
                            "temperature": 0.7,
                            "craftMode": "off",
                            "messages": [{"role": "user", "content": "审查第一章"}],
                            "project": request.project.model_dump(mode="json"),
                            "actions": [],
                            "trace": [{"type": "tool_result", "name": "get_chapter", "ok": True}],
                            "final_message": "",
                            "last_tool_text": "",
                        }
                    )
                raise RuntimeError("上游超时（模拟）")

            # 第一次运行：中途失败 → 检查点 status=error
            with patch(PATCH_TARGET, new=failing_agent):
                r = await client.post(
                    f"/api/v1/projects/{pid}/agent/stream",
                    json={"messages": MESSAGE, "apply_actions": True},
                    headers=headers,
                )
            assert r.status_code == 200, r.text
            assert "error" in r.text

            # 会话暴露 run_state 摘要（status=error）
            convs = (await client.get(f"/api/v1/projects/{pid}/agent/conversations", headers=headers)).json()
            assert len(convs) == 1
            conv_id = convs[0]["id"]
            detail = (
                await client.get(
                    f"/api/v1/projects/{pid}/agent/conversations/{conv_id}",
                    headers=headers,
                )
            ).json()
            assert detail["run_state"] is not None
            assert detail["run_state"]["status"] == "error"
            assert detail["run_state"]["step"] == 1

            async def resuming_agent(
                config, request, *, on_event=None, on_checkpoint=None, resume=None
            ):
                assert resume is not None, "resume 模式必须携带检查点"
                assert resume.get("step") == 1
                assert resume.get("project")  # 快照项目可恢复
                await on_event({"type": "task", "text": "从断点继续"})
                await on_event(
                    {"type": "thought", "text": "已拿到检查点，继续给意见"}
                )
                await on_event({"type": "done", "result": {"message": "续跑完成"}})
                return AgentResponse(
                    message="续跑完成。",
                    actions=[UPDATE_VOICE_ACTION],
                    model="test-model",
                )

            # 第二次：resume=true 从检查点续跑 → 正常完成并落库
            with patch(PATCH_TARGET, new=resuming_agent):
                r = await client.post(
                    f"/api/v1/projects/{pid}/agent/stream",
                    json={
                        "messages": [],
                        "conversation_id": conv_id,
                        "apply_actions": True,
                        "resume": True,
                    },
                    headers=headers,
                )
            assert r.status_code == 200, r.text
            events = [
                json.loads(line[len("data: "):])
                for line in r.text.splitlines()
                if line.startswith("data: ")
            ]
            types = [e["type"] for e in events]
            assert types[-1] == "final", f"expected final, got {types}"
            assert events[-1]["result"]["applied"] is True
            assert events[-1]["result"]["message"] == "续跑完成。"

            # 续跑完成后 run_state=done，不再提示"继续"
            detail2 = (
                await client.get(
                    f"/api/v1/projects/{pid}/agent/conversations/{conv_id}",
                    headers=headers,
                )
            ).json()
            assert detail2["run_state"]["status"] == "done"

    _run(_scenario())


def test_agent_stream_resume_without_checkpoint_rejected():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "stream_resume_none")
            pid = await _create_demo_project(client, headers)

            async def ok_agent(
                config, request, *, on_event=None, on_checkpoint=None, resume=None
            ):
                await on_event({"type": "task", "text": "正常完成"})
                await on_event({"type": "done", "result": {"message": "完成"}})
                return AgentResponse(
                    message="完成。",
                    actions=[],
                    model="test-model",
                )

            # 正常运行完成 → run_state=done（无中断检查点）
            with patch(PATCH_TARGET, new=ok_agent):
                r = await client.post(
                    f"/api/v1/projects/{pid}/agent/stream",
                    json={"messages": MESSAGE, "apply_actions": True},
                    headers=headers,
                )
            assert r.status_code == 200, r.text
            convs = (
                await client.get(f"/api/v1/projects/{pid}/agent/conversations", headers=headers)
            ).json()
            conv_id = convs[0]["id"]
            # 已结束时 resume 必须 400
            r2 = await client.post(
                f"/api/v1/projects/{pid}/agent/stream",
                json={
                    "messages": [],
                    "conversation_id": conv_id,
                    "apply_actions": True,
                    "resume": True,
                },
                headers=headers,
            )
            assert r2.status_code == 400, r2.text
            assert "没有可继续" in r2.json()["detail"]

    _run(_scenario())
