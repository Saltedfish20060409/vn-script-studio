"""API tests: project save path bumps row_version (optimistic-lock foundation).

put/patch now hold a FOR UPDATE row lock inside the save transaction, and
every write bumps projects.row_version — the foundation for future client
conditional saves (rowVersion / If-Match).
"""

from __future__ import annotations

import asyncio

import db_gate
import pytest
from sqlalchemy import text

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(
        not db_gate.DB_AVAILABLE,
        reason="PostgreSQL test DB unreachable (set DATABASE_URL_TEST)",
    ),
]

APP = db_gate.make_app()


def _ensure_column() -> None:
    """已存在的测试库不会走 create_all 增列——幂等补列（与 0023 迁移一致）。"""

    async def _run():
        async with db_gate.engine.begin() as conn:
            await conn.execute(
                text(
                    "ALTER TABLE projects "
                    "ADD COLUMN IF NOT EXISTS row_version INTEGER NOT NULL DEFAULT 1"
                )
            )

    asyncio.run(_run())


def _run(coro):
    return asyncio.run(coro)


def test_row_version_bumps_on_every_save():
    _ensure_column()

    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "rowver_user")
            r = await client.post(
                "/api/v1/projects", json={"title": "版本项目"}, headers=headers
            )
            assert r.status_code == 200, r.text
            pid = r.json()["id"]

            proj = (
                await client.get(f"/api/v1/projects/{pid}", headers=headers)
            ).json()
            for i in range(2):
                proj["title"] = f"版本项目 v{i + 2}"
                r = await client.put(
                    f"/api/v1/projects/{pid}", json={"data": proj}, headers=headers
                )
                assert r.status_code == 200, r.text
                proj = r.json()

        async with db_gate.SessionLocal() as session:
            got = (
                await session.execute(
                    text("SELECT row_version FROM projects WHERE id = :pid"),
                    {"pid": pid},
                )
            ).scalar_one()
        # 建项目=1，两次保存各 +1
        assert got == 3, f"expected row_version 3, got {got}"

    _run(_scenario())


def test_patch_also_bumps_row_version():
    _ensure_column()

    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "rowver_patch")
            r = await client.post(
                "/api/v1/projects", json={"title": "补丁项目"}, headers=headers
            )
            assert r.status_code == 200, r.text
            pid = r.json()["id"]
            r = await client.patch(
                f"/api/v1/projects/{pid}",
                json={"title": "补丁后的标题"},
                headers=headers,
            )
            assert r.status_code == 200, r.text

        async with db_gate.SessionLocal() as session:
            title, ver = (
                await session.execute(
                    text("SELECT title, row_version FROM projects WHERE id = :pid"),
                    {"pid": pid},
                )
            ).one()
        assert title == "补丁后的标题"
        assert ver == 2, f"expected row_version 2 after patch, got {ver}"

    _run(_scenario())
