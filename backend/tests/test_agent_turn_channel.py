"""Writing Turn（POST /agent/turn）P1 守卫：透传 writer + meta/soft/hard 超时协议。"""

from __future__ import annotations

import asyncio
import json

import db_gate
import pytest

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(
        not db_gate.DB_AVAILABLE,
        reason="PostgreSQL test DB unreachable (set DATABASE_URL_TEST)",
    ),
]

APP = db_gate.make_app()

DRAFT = "（她看着你，不说话。）\n"


def _run(coro):
    return asyncio.run(coro)


async def _create_project(client, headers, title="Turn通道测试"):
    resp = await client.post(
        "/api/v1/projects", json={"title": title, "from_demo": True}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def _sse_events(text: str) -> list[dict]:
    return [
        json.loads(line[len("data: ") :])
        for line in text.splitlines()
        if line.startswith("data: ")
    ]


def test_agent_turn_write_passthrough_emits_meta_and_done(monkeypatch):
    from app.core.pipeline import orchestrator as orch

    async def fake_stage_write(cfg, project, **kwargs):
        on_token = kwargs.get("on_token")
        if on_token is not None:
            on_token(DRAFT)
        return {"stage": "write", "content": DRAFT, "model": "test-model"}

    monkeypatch.setattr(orch, "stage_write", fake_stage_write)

    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "turn_chan")
            pid = await _create_project(client, headers)
            before = (await client.get(f"/api/v1/projects/{pid}", headers=headers)).json()
            chapter_id = before["chapters"][0]["id"]

            resp = await client.post(
                f"/api/v1/projects/{pid}/agent/turn",
                json={
                    "capability": "write",
                    "write_op": "continue",
                    "instruction": "续写下一拍",
                    "chapter_id": chapter_id,
                },
                headers=headers,
            )
            assert resp.status_code == 200, resp.text
            events = _sse_events(resp.text)
            kinds = [e["type"] for e in events]
            assert kinds[0] == "meta", events
            assert events[0].get("passthrough") is False
            assert events[0].get("enrichContext") is True
            assert events[0].get("compatLayer") is True
            assert events[0]["softTimeoutS"] == 180.0
            assert events[0]["hardCancelS"] == 210.0
            assert "token" in kinds
            assert kinds[-1] == "done"
            assert events[-1]["wrote"] is False
            assert events[-1]["content"] == DRAFT.strip()

            after = (await client.get(f"/api/v1/projects/{pid}", headers=headers)).json()
            assert after["chapters"][0]["prose"] == before["chapters"][0].get("prose")

    _run(_scenario())


def test_agent_turn_rejects_unknown_write_op(monkeypatch):
    """P5 已开放 polish 等；未知 write_op 仍应 400。"""

    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "turn_bad_op")
            pid = await _create_project(client, headers)
            resp = await client.post(
                f"/api/v1/projects/{pid}/agent/turn",
                json={
                    "capability": "write",
                    "write_op": "teleport",
                    "instruction": "非法 op",
                },
                headers=headers,
            )
            assert resp.status_code in (400, 422), resp.text

    _run(_scenario())


def test_agent_turn_ingest_delegates_not_501():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "turn_ingest")
            pid = await _create_project(client, headers)
            resp = await client.post(
                f"/api/v1/projects/{pid}/agent/turn",
                json={"capability": "ingest", "instruction": "写入设定"},
                headers=headers,
            )
            assert resp.status_code == 200, resp.text
            events = _sse_events(resp.text)
            assert events[0]["type"] == "meta"
            assert events[0].get("delegated") is True
            assert events[0].get("capability") == "ingest"
            assert events[-1]["type"] == "done"
            assert events[-1].get("delegated") is True

    _run(_scenario())


def test_agent_turn_chat_delegates_not_501(monkeypatch):
    from app.core import agent as agent_mod

    async def fake_run_agent(cfg, req, on_event=None, on_checkpoint=None, resume=None):
        if on_event:
            await on_event({"type": "thought", "text": "想想"})
            await on_event(
                {
                    "type": "done",
                    "reply": "雪菜的人设还可以再立一点反差。",
                    "actions": [],
                }
            )
        return {
            "reply": "雪菜的人设还可以再立一点反差。",
            "actions": [],
            "messages": list(getattr(req, "messages", []) or []),
            "usage": {},
            "model": "test",
        }

    monkeypatch.setattr(agent_mod, "run_agent", fake_run_agent)

    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "turn_chat")
            pid = await _create_project(client, headers)
            resp = await client.post(
                f"/api/v1/projects/{pid}/agent/turn",
                json={
                    "capability": "chat",
                    "instruction": "你觉得雪菜这个角色怎么样",
                },
                headers=headers,
            )
            assert resp.status_code == 200, resp.text
            assert resp.status_code != 501
            events = _sse_events(resp.text)
            assert events, resp.text
            assert events[0]["type"] == "meta"
            assert events[0].get("capability") == "chat"
            assert events[0].get("delegated") is True
            joined = resp.text
            assert "尚未在 Writing Turn 实现" not in joined
            assert "经典责编工具环" not in joined

    _run(_scenario())


def test_source_has_no_channel_tax_501_copy():
    """ADR §6：禁止再出现「请用写作能力 / 开经典工具环」的 501 心智税文案。"""
    from pathlib import Path

    src = Path(__file__).resolve().parents[1] / "app" / "api" / "v1" / "projects.py"
    text = src.read_text(encoding="utf-8")
    assert "尚未在 Writing Turn 实现" not in text
    assert "请使用写作能力" not in text


def test_agent_turn_hard_timeout_cancels(monkeypatch):
    from app.core import agent_turn
    from app.core.pipeline import orchestrator as orch

    monkeypatch.setattr(agent_turn, "WRITE_SOFT_TIMEOUT_S", 0.05)
    monkeypatch.setattr(agent_turn, "WRITE_HARD_CANCEL_S", 0.12)

    async def slow_stage_write(cfg, project, **kwargs):
        await asyncio.sleep(2.0)
        return {"stage": "write", "content": "should-not-finish", "model": "x"}

    monkeypatch.setattr(orch, "stage_write", slow_stage_write)

    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "turn_hard")
            pid = await _create_project(client, headers)
            resp = await client.post(
                f"/api/v1/projects/{pid}/agent/turn",
                json={"capability": "write", "instruction": "慢写"},
                headers=headers,
            )
            assert resp.status_code == 200, resp.text
            events = _sse_events(resp.text)
            kinds = [e["type"] for e in events]
            assert "meta" in kinds
            assert "soft_timeout" in kinds or "error" in kinds
            err = next(e for e in events if e.get("type") == "error")
            assert err.get("code") == "hard_timeout"
            assert "done" not in kinds

    _run(_scenario())
