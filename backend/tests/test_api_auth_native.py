"""原生客户端（`X-Client: android`）的鉴权模式：refresh token 走响应体而不是 Cookie。

同时钉住「Web 路径不变」——Web 端仍是 Cookie-only、响应体不暴露 refresh token（M-4）。
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
NATIVE = {"X-Client": "android"}


def _run(coro):
    return asyncio.run(coro)


async def _register_verified(client, username: str, email: str, password: str = "secret123"):
    from datetime import datetime, timezone

    from sqlalchemy import select

    from app.models import User

    with patch("app.api.v1.auth.send_verify_email", new_callable=AsyncMock):
        r = await client.post(
            "/api/v1/auth/register",
            json={"username": username, "email": email, "password": password},
        )
    assert r.status_code == 200, r.text
    async with db_gate.SessionLocal() as session:
        user = (await session.execute(select(User).where(User.email == email))).scalar_one()
        user.email_verified_at = datetime.now(timezone.utc)
        await session.commit()


def test_native_login_returns_refresh_in_body_without_cookie():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            await _register_verified(client, "nativea", "nativea@example.com")
            r = await client.post(
                "/api/v1/auth/login",
                json={"username": "nativea", "password": "secret123"},
                headers=NATIVE,
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["access_token"]
            assert body["refresh_token"], "原生客户端必须在响应体拿到 refresh token"
            assert "vnss_refresh" not in client.cookies, "原生模式不应设置 Cookie"

    _run(_scenario())


def test_native_refresh_via_body_rotates_token():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            await _register_verified(client, "nativeb", "nativeb@example.com")
            login = await client.post(
                "/api/v1/auth/login",
                json={"username": "nativeb", "password": "secret123"},
                headers=NATIVE,
            )
            refresh_token = login.json()["refresh_token"]

            r = await client.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": refresh_token},
                headers=NATIVE,
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["access_token"]
            assert body["refresh_token"], "刷新后应在响应体返回轮换后的 refresh token"
            assert "vnss_refresh" not in client.cookies

            # 拿到的新 access token 可用
            me = await client.get(
                "/api/v1/auth/me",
                headers={"Authorization": f"Bearer {body['access_token']}"},
            )
            assert me.status_code == 200
            assert me.json()["username"] == "nativeb"

    _run(_scenario())


def test_native_refresh_rejects_missing_or_garbage_token():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            r = await client.post("/api/v1/auth/refresh", headers=NATIVE)
            assert r.status_code == 401
            r = await client.post(
                "/api/v1/auth/refresh",
                json={"refresh_token": "not-a-jwt"},
                headers=NATIVE,
            )
            assert r.status_code == 401

    _run(_scenario())


def test_body_refresh_token_ignored_for_web_clients():
    """Web 路径保持 Cookie-only：没有 X-Client 头时，请求体里的令牌不被采信。"""

    async def _scenario():
        async with db_gate.make_client(APP) as client:
            await _register_verified(client, "nativec", "nativec@example.com")
            login = await client.post(
                "/api/v1/auth/login",
                json={"username": "nativec", "password": "secret123"},
                headers=NATIVE,
            )
            refresh_token = login.json()["refresh_token"]

            # 新客户端（无 Cookie）+ 无 X-Client → 即便请求体带了合法令牌也必须拒绝
            async with db_gate.make_client(APP) as web:
                r = await web.post(
                    "/api/v1/auth/refresh", json={"refresh_token": refresh_token}
                )
                assert r.status_code == 401

    _run(_scenario())


def test_web_login_unchanged_cookie_only():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            await _register_verified(client, "natived", "natived@example.com")
            r = await client.post(
                "/api/v1/auth/login",
                json={"username": "natived", "password": "secret123"},
            )
            assert r.status_code == 200
            assert r.json().get("refresh_token") in (None, "")
            assert client.cookies.get("vnss_refresh")

    _run(_scenario())
