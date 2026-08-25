"""API tests: admin gating (403 for normal users) + ban/unban login flow."""

from __future__ import annotations

import asyncio

import db_gate
import pytest
from sqlalchemy import select, text

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


async def _ensure_is_admin_column() -> None:
    """幂等补齐 users.is_admin（与 0022 迁移一致）：兼容旧结构的测试库。

    conftest 的 create_all 只会建缺失的表、不会给已有表加列，所以这里显式
    补一次，避免旧测试库上整个模块因缺列而挂。
    """
    async with db_gate.SessionLocal() as session:
        await session.execute(
            text(
                "ALTER TABLE users "
                "ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT false"
            )
        )
        await session.commit()


async def _make_admin(client, username: str) -> dict:
    """注册一个用户、直接在库中置 is_admin=True，重新登录拿 token。

    必须先有一个 admin 存在，否则 ensure_admin_access 的「首个登录者升
    admin」bootstrap 会把普通用户也变成管理员，403 断言就测不到了。
    """
    from app.models import User

    await db_gate.register_headers(client, username)
    async with db_gate.SessionLocal() as session:
        result = await session.execute(select(User).where(User.username == username))
        user = result.scalar_one()
        user.is_admin = True
        await session.commit()
    r = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": "secret123"},
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_non_admin_cannot_access_overview():
    """普通用户访问 /admin/overview 得 403；管理员得 200 且返回 dict。"""

    async def _scenario():
        async with db_gate.make_client(APP) as client:
            await _ensure_is_admin_column()
            admin_headers = await _make_admin(client, "admin_ov1")
            assert admin_headers

            user_headers = await db_gate.register_headers(client, "normal_ov1")
            r = await client.get("/api/v1/admin/overview", headers=user_headers)
            assert r.status_code == 403, r.text
            assert "管理员" in r.json()["detail"]

            r = await client.get("/api/v1/admin/overview", headers=admin_headers)
            assert r.status_code == 200, r.text
            body = r.json()
            assert isinstance(body, dict)
            assert body["user_count"] >= 2
            assert any(u["username"] == "admin_ov1" for u in body["users"])

    _run(_scenario())


def test_ban_blocks_login_unban_restores():
    """封禁后该用户登录失败（403），解封后恢复登录。"""

    async def _scenario():
        async with db_gate.make_client(APP) as client:
            await _ensure_is_admin_column()
            admin_headers = await _make_admin(client, "admin_ban1")
            await db_gate.register_headers(client, "victim1")

            r = await client.post(
                "/api/v1/admin/users/victim1/ban", headers=admin_headers
            )
            assert r.status_code == 200, r.text
            assert r.json()["disabled"] is True

            r = await client.post(
                "/api/v1/auth/login",
                json={"username": "victim1", "password": "secret123"},
            )
            assert r.status_code == 403, r.text
            assert "停用" in r.json()["detail"]

            r = await client.post(
                "/api/v1/admin/users/victim1/unban", headers=admin_headers
            )
            assert r.status_code == 200, r.text
            assert r.json()["disabled"] is False

            r = await client.post(
                "/api/v1/auth/login",
                json={"username": "victim1", "password": "secret123"},
            )
            assert r.status_code == 200, r.text

    _run(_scenario())
