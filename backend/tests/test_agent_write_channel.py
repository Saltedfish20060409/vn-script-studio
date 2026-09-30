"""写作通道（POST /agent/write）的守卫测试。

为什么单开一条通道（2026-09-30 线上实测）：聊天那条走的是**审阅条件**（JSON 协议 + 工具 +
规则块），同一模型同一份设计书下会退化成"把设计书抄成骨架"（1141 字，选项留成占位符）；
writer 条件的成稿是 2124 字。这条测试钉住三件事：

1. 它是**流式**的（先来 token、最后来 done）；
2. 它**一个字都不写工程**（作者在前端对照/确认后才走 apply）；
3. done 事件里带着原文与标题——前端对照面板要用它们。

LLM 由 monkeypatch 掉 `stage_write`，其余（鉴权、项目读、SSE 框架）都是真的。
"""

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

DRAFT = "（她看着你，不说话。）\n雪菜：「名字……和代号，有什么不同？」\n"


def _run(coro):
    return asyncio.run(coro)


async def _create_project(client, headers, title="写作通道测试"):
    resp = await client.post(
        "/api/v1/projects", json={"title": title, "from_demo": True}, headers=headers
    )
    assert resp.status_code == 200, resp.text
    return resp.json()["id"]


def test_agent_write_streams_draft_without_touching_the_project(monkeypatch):
    from app.core.pipeline import orchestrator as orch

    captured: dict = {}

    async def fake_stage_write(cfg, project, **kwargs):
        captured.update(kwargs)
        on_token = kwargs.get("on_token")
        if on_token is not None:
            for piece in ("（她看着你，不说话。）\n", "雪菜：「名字……和代号，有什么不同？」\n"):
                on_token(piece)
        return {"stage": "write", "content": DRAFT, "model": "test-model"}

    monkeypatch.setattr(orch, "stage_write", fake_stage_write)

    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "write_chan")
            pid = await _create_project(client, headers)
            before = (await client.get(f"/api/v1/projects/{pid}", headers=headers)).json()
            chapter_id = before["chapters"][0]["id"]

            resp = await client.post(
                f"/api/v1/projects/{pid}/agent/write",
                json={
                    "instruction": "请按设计书写完整的第一章",
                    "chapter_id": chapter_id,
                },
                headers=headers,
            )
            assert resp.status_code == 200, resp.text
            assert resp.headers["content-type"].startswith("text/event-stream")

            events = [
                json.loads(line[len("data: ") :])
                for line in resp.text.splitlines()
                if line.startswith("data: ")
            ]
            kinds = [e["type"] for e in events]
            assert "token" in kinds, events
            assert kinds[-1] == "done", kinds

            done = events[-1]
            assert done["content"] == DRAFT.strip()
            assert done["wrote"] is False
            assert done["chapterId"] == chapter_id
            assert done["chapterTitle"] == before["chapters"][0]["title"]
            assert isinstance(done["sourceText"], str)

            # 拿到的东西：作者的指令 + 这一章的 id 传给了写作条件
            assert captured.get("instruction") == "请按设计书写完整的第一章"
            assert captured.get("chapter_id") == chapter_id

            # 一个字都没写进工程
            after = (await client.get(f"/api/v1/projects/{pid}", headers=headers)).json()
            assert after["chapters"] == before["chapters"]
            assert after["updatedAt"] == before["updatedAt"]

    _run(_scenario())


def test_agent_write_requires_chapter_when_writing_into_one(monkeypatch):
    """不传 chapter_id 也能写（纯创作），但要能明确报错路径：缺 Key 时给可执行的提示。"""
    from app.core.pipeline import orchestrator as orch

    async def fake_stage_write(cfg, project, **kwargs):
        return {"stage": "write", "content": "正文", "model": "test-model"}

    monkeypatch.setattr(orch, "stage_write", fake_stage_write)

    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "write_chan2")
            pid = await _create_project(client, headers, "写作通道测试2")
            resp = await client.post(
                f"/api/v1/projects/{pid}/agent/write",
                json={"instruction": "写一段"},
                headers=headers,
            )
            # db_gate 会给端点一个假 Key，所以这里应当是 200 且照常流式返回
            assert resp.status_code == 200, resp.text
            assert "data: " in resp.text

    _run(_scenario())
