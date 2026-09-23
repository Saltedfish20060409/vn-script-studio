"""头脑风暴作业化（async_mode）：多轮同步端点改成后台作业的样板。

为什么做这件事：`/brainstorm` 是「作家并发一轮 + 责编综合一轮」的**两轮串行**模型调用，
思考档下最坏 8 分钟量级。留在 HTTP 请求里，前端就只能把等待预算拉到 10 分钟级才不会误判超时；
做成作业后，发起请求只需覆盖"登记作业"的时间，进度与结果走既有作业通道
（与 pipeline/run、chapter-revise 的 async_mode 同一套）。

测试库不可达时整模块跳过（与既有 test_api_*.py 一致）。
"""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

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

FAKE_RESULT = {
    "mode": "parallel_then_synthesize",
    "question": "第二幕怎么收紧？",
    "lensIds": ["a", "b"],
    "perspectives": [
        {
            "id": "a",
            "name": "参谋甲",
            "content": "把冲突提前到第一场。",
            "model": "m",
            "ok": True,
            "error": None,
        }
    ],
    "synthesis": "先砍支线，再让对手先动手。",
    "model": "m",
    "authorCount": 2,
    "okCount": 1,
}


async def _setup(client, name: str):
    owner = await db_gate.register_headers(client, name)
    resp = await client.post(
        "/api/v1/projects", json={"title": f"头脑风暴-{name}"}, headers=owner
    )
    assert resp.status_code == 200, resp.text
    return owner, resp.json()["id"]


async def _poll_job(client, pid: str, job_id: str, headers, tries: int = 80) -> dict:
    """轮询作业直到终态。作业是后台任务，本轮 await 会让它有机会跑。"""
    last: dict = {}
    for _ in range(tries):
        resp = await client.get(f"/api/v1/projects/{pid}/jobs/{job_id}", headers=headers)
        assert resp.status_code == 200, resp.text
        last = resp.json()
        if last.get("status") in ("done", "error", "cancelled"):
            return last
        await asyncio.sleep(0.05)
    raise AssertionError(f"作业未在预期时间内结束：{last}")


def test_async_mode_returns_job_and_result_is_retrievable():
    """async_mode=true → 立刻拿到 jobId；结果通过作业查询接口取到，形状与同步一致。"""

    async def _run():
        await db_gate.create_all()
        await db_gate.truncate_all()
        async with db_gate.make_client(APP) as client:
            owner, pid = await _setup(client, "bs_async")
            with db_gate.background_jobs_use_test_db():
                with patch(
                    "app.api.v1.lenses.run_brainstorm",
                    new=AsyncMock(return_value=FAKE_RESULT),
                ):
                    resp = await client.post(
                        f"/api/v1/projects/{pid}/brainstorm",
                        json={"question": "第二幕怎么收紧？", "async_mode": True},
                        headers=owner,
                    )
                    assert resp.status_code == 200, resp.text
                    body = resp.json()
                    assert body["async"] is True
                    assert body["jobId"].startswith("job_")
                    job = await _poll_job(client, pid, body["jobId"], owner)
                assert job["status"] == "done", job
                assert job["kind"] == "brainstorm"
                assert job["result"]["synthesis"] == FAKE_RESULT["synthesis"]
                # 与同步分支同一个返回形状：markdown 也在
                assert FAKE_RESULT["synthesis"] in job["result"]["markdown"]
                assert job["result"]["perspectives"][0]["name"] == "参谋甲"

    asyncio.run(_run())


def test_async_mode_failure_is_reported_in_the_job():
    """作家不够之类的输入错误，不能在作业里静默掉——状态要变 error 并带上原因。"""

    async def _run():
        await db_gate.create_all()
        await db_gate.truncate_all()
        async with db_gate.make_client(APP) as client:
            owner, pid = await _setup(client, "bs_fail")
            boom = ValueError("强头脑风暴至少需要 2 位作家（请在 ⇄ 中多选）")
            with db_gate.background_jobs_use_test_db():
                with patch(
                    "app.api.v1.lenses.run_brainstorm", new=AsyncMock(side_effect=boom)
                ):
                    resp = await client.post(
                        f"/api/v1/projects/{pid}/brainstorm",
                        json={"question": "x", "async_mode": True},
                        headers=owner,
                    )
                    assert resp.status_code == 200, resp.text
                    job = await _poll_job(client, pid, resp.json()["jobId"], owner)
            assert job["status"] == "error", job
            assert "至少需要 2 位作家" in job["error"]

    asyncio.run(_run())


def test_sync_path_still_works():
    """不带 async_mode 时行为不变（老客户端 / 其它调用方仍可用）。"""

    async def _run():
        await db_gate.create_all()
        await db_gate.truncate_all()
        async with db_gate.make_client(APP) as client:
            owner, pid = await _setup(client, "bs_sync")
            with patch(
                "app.api.v1.lenses.run_brainstorm",
                new=AsyncMock(return_value=FAKE_RESULT),
            ):
                resp = await client.post(
                    f"/api/v1/projects/{pid}/brainstorm",
                    json={"question": "第二幕怎么收紧？"},
                    headers=owner,
                )
            assert resp.status_code == 200, resp.text
            data = resp.json()
            assert data["synthesis"] == FAKE_RESULT["synthesis"]
            assert "markdown" in data
            assert "async" not in data

    asyncio.run(_run())
