"""GET /settings 下发 P4.5 flag；PUT 带只读字段静默忽略。"""

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


def test_settings_get_includes_enforce_flag():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "p45_flag_get")
            r = await client.get("/api/v1/settings", headers=headers)
            assert r.status_code == 200, r.text
            body = r.json()
            assert "enforce_prose_engine_syntax_reject" in body
            assert isinstance(body["enforce_prose_engine_syntax_reject"], bool)

    _run(_scenario())


def test_settings_put_ignores_enforce_flag():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "p45_flag_put")
            before = (await client.get("/api/v1/settings", headers=headers)).json()
            server_val = before["enforce_prose_engine_syntax_reject"]
            r = await client.put(
                "/api/v1/settings",
                headers=headers,
                json={
                    "theme": before.get("theme") or "day",
                    "enforce_prose_engine_syntax_reject": not server_val,
                },
            )
            assert r.status_code == 200, r.text
            after = r.json()
            # 只读：PUT 不能改服务端 env 值
            assert after["enforce_prose_engine_syntax_reject"] is server_val

    _run(_scenario())
