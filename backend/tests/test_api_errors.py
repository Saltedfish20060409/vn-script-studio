"""API tests: error reporting sink (rate-limited) + list endpoint."""

from __future__ import annotations

import asyncio

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


def _run(coro):
    return asyncio.run(coro)


def test_report_error_stores_and_lists():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "err_owner")

            # anonymous (no auth) report
            r = await client.post(
                "/api/v1/errors",
                json={
                    "message": "编辑器渲染失败",
                    "stack": "at Render (App.tsx:12)",
                    "url": "http://test/project/p1",
                    "component": "ScriptEditor",
                },
            )
            assert r.status_code == 200, r.text
            assert r.json()["ok"] is True

            # authenticated report gets attributed to the user
            r = await client.post(
                "/api/v1/errors",
                json={"message": "带登录态的报错", "level": "warn"},
                headers=headers,
            )
            assert r.status_code == 200, r.text

            # invalid: empty message → 422
            r = await client.post("/api/v1/errors", json={"message": ""})
            assert r.status_code == 422

            # list requires auth
            r = await client.get("/api/v1/errors")
            assert r.status_code in (401, 403)

            r = await client.get("/api/v1/errors", headers=headers)
            assert r.status_code == 200, r.text
            reports = r.json()["reports"]
            assert len(reports) == 2
            messages = {x["message"] for x in reports}
            assert "编辑器渲染失败" in messages
            assert "带登录态的报错" in messages

    _run(_scenario())


def test_report_error_rate_limited():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            ok = 0
            for i in range(25):
                r = await client.post(
                    "/api/v1/errors", json={"message": f"批量报错 {i}"}
                )
                if r.status_code == 200:
                    ok += 1
                elif r.status_code == 429:
                    break
            assert ok <= 20, "rate limiter should cap error reports per IP"

    _run(_scenario())
