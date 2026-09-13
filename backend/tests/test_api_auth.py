"""API tests: /auth register · login · me (+ error paths)."""

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


def _run(coro):
    return asyncio.run(coro)


async def _register(client, username: str, email: str, password: str = "secret123"):
    with patch(
        "app.api.v1.auth.send_verify_email", new_callable=AsyncMock
    ) as mocked:
        r = await client.post(
            "/api/v1/auth/register",
            json={"username": username, "email": email, "password": password},
        )
        assert r.status_code == 200, r.text
        mocked.assert_awaited_once()
    return r.json()


async def _verify_latest(client, email: str):
    """Mark the user verified directly via DB for login tests."""
    from datetime import datetime, timezone

    from sqlalchemy import select

    from app.models import User

    async with db_gate.SessionLocal() as session:
        result = await session.execute(select(User).where(User.email == email))
        user = result.scalar_one()
        user.email_verified_at = datetime.now(timezone.utc)
        await session.commit()


def test_register_login_me_roundtrip():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            body = await _register(client, "alice", "alice@example.com")
            assert body["ok"] is True
            assert body["email"] == "alice@example.com"

            # unverified → login blocked
            r = await client.post(
                "/api/v1/auth/login",
                json={"username": "alice", "password": "secret123"},
            )
            assert r.status_code == 403

            await _verify_latest(client, "alice@example.com")

            r = await client.post(
                "/api/v1/auth/login",
                json={"username": "alice", "password": "secret123"},
            )
            assert r.status_code == 200, r.text
            token = r.json()["access_token"]
            assert token

            r = await client.get(
                "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
            )
            assert r.status_code == 200, r.text
            me = r.json()
            assert me["username"] == "alice"
            assert me["email"] == "alice@example.com"
            assert me["email_verified"] is True

            # login by email works
            r = await client.post(
                "/api/v1/auth/login",
                json={"username": "alice@example.com", "password": "secret123"},
            )
            assert r.status_code == 200, r.text

    _run(_scenario())


def test_login_wrong_password_401():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            await _register(client, "bob", "bob@example.com")
            await _verify_latest(client, "bob@example.com")
            r = await client.post(
                "/api/v1/auth/login",
                json={"username": "bob", "password": "wrong-password"},
            )
            assert r.status_code == 401
            r = await client.post(
                "/api/v1/auth/login",
                json={"username": "nobody", "password": "whatever1"},
            )
            assert r.status_code == 401

    _run(_scenario())


def test_register_duplicate_username_400():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            payload = {
                "username": "carol",
                "email": "carol@example.com",
                "password": "secret123",
            }
            with patch("app.api.v1.auth.send_verify_email", new_callable=AsyncMock):
                r1 = await client.post("/api/v1/auth/register", json=payload)
            assert r1.status_code == 200, r1.text
            with patch("app.api.v1.auth.send_verify_email", new_callable=AsyncMock):
                r2 = await client.post("/api/v1/auth/register", json=payload)
            assert r2.status_code == 400, r2.text

    _run(_scenario())


def test_me_without_token_401():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            r = await client.get("/api/v1/auth/me")
            assert r.status_code == 401
            r = await client.get(
                "/api/v1/auth/me", headers={"Authorization": "Bearer not-a-jwt"}
            )
            assert r.status_code == 401

    _run(_scenario())


def test_register_invalid_payload_422():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            r = await client.post(
                "/api/v1/auth/register",
                json={"username": "x", "password": "short"},
            )
            assert r.status_code == 422

    _run(_scenario())


def test_login_refresh_cookie_roundtrip():
    """M-4: refresh token travels in an HttpOnly cookie; /refresh uses it;
    /logout clears it."""

    async def _scenario():
        async with db_gate.make_client(APP) as client:
            await _register(client, "dave", "dave@example.com")
            await _verify_latest(client, "dave@example.com")
            r = await client.post(
                "/api/v1/auth/login",
                json={"username": "dave", "password": "secret123"},
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["access_token"]
            # Response body must NOT expose the refresh token (cookie-only).
            assert body.get("refresh_token") in (None, "")

            # Cookie was set by the server.
            assert "vnss_refresh" in client.cookies
            assert client.cookies["vnss_refresh"]

            # /refresh with no body works (token comes from cookie).
            r = await client.post("/api/v1/auth/refresh")
            assert r.status_code == 200, r.text
            assert r.json()["access_token"]

            # /logout clears the cookie.
            r = await client.post("/api/v1/auth/logout")
            assert r.status_code == 200, r.text
            assert "vnss_refresh" not in client.cookies

            # Refresh after logout → 401.
            r = await client.post("/api/v1/auth/refresh")
            assert r.status_code == 401

    _run(_scenario())


def test_resend_verification_accepts_username_and_email():
    """重发验证邮件既认邮箱也认用户名，且两条静默分支都要给出可执行的提示。

    线上反馈"重发也收不到"的根因之一：只按邮箱查，用户填了用户名（或另一个邮箱）
    时静默返回 200、其实一封信都没发。
    """

    async def _scenario():
        async with db_gate.make_client(APP) as client:
            await _register(client, "resenduser", "resenduser@example.com")

            with patch(
                "app.api.v1.auth.send_verify_email", new_callable=AsyncMock
            ) as mocked:
                # 用用户名重发 → 真的发信
                r = await client.post(
                    "/api/v1/auth/resend-verification", json={"email": "resenduser"}
                )
                assert r.status_code == 200, r.text
                mocked.assert_awaited_once()
                assert "已发送" in r.json()["message"]

                # 用邮箱重发 → 也真的发信
                mocked.reset_mock()
                r = await client.post(
                    "/api/v1/auth/resend-verification",
                    json={"email": "resenduser@example.com"},
                )
                assert r.status_code == 200, r.text
                mocked.assert_awaited_once()

                # 查不到账号 → 不发信，但要告诉用户去核对/走找回密码
                mocked.reset_mock()
                r = await client.post(
                    "/api/v1/auth/resend-verification",
                    json={"email": "nobody-here@example.com"},
                )
                assert r.status_code == 200, r.text
                mocked.assert_not_awaited()
                assert "没查到" in r.json()["message"]

            # 已验证账号 → 不发信，提示直接登录
            await _verify_latest(client, "resenduser@example.com")
            with patch(
                "app.api.v1.auth.send_verify_email", new_callable=AsyncMock
            ) as mocked:
                r = await client.post(
                    "/api/v1/auth/resend-verification", json={"email": "resenduser"}
                )
                assert r.status_code == 200, r.text
                mocked.assert_not_awaited()
                assert "已经验证" in r.json()["message"]

            # 邮箱格式明显写错 → 400，别静默成功
            r = await client.post(
                "/api/v1/auth/resend-verification", json={"email": "not-an-email@"}
            )
            assert r.status_code == 400, r.text

    _run(_scenario())


def test_forgot_password_accepts_username():
    """找回密码也认用户名，避免用户输用户名时拿到假的"已发送"。"""

    async def _scenario():
        async with db_gate.make_client(APP) as client:
            await _register(client, "forgotuser", "forgotuser@example.com")

            with patch(
                "app.api.v1.auth.send_reset_email", new_callable=AsyncMock
            ) as mocked:
                r = await client.post(
                    "/api/v1/auth/forgot-password", json={"email": "forgotuser"}
                )
                assert r.status_code == 200, r.text
                mocked.assert_awaited_once()

                mocked.reset_mock()
                r = await client.post(
                    "/api/v1/auth/forgot-password",
                    json={"email": "ghost-account@example.com"},
                )
                assert r.status_code == 200, r.text
                mocked.assert_not_awaited()
                assert "垃圾邮件箱" in r.json()["message"]

    _run(_scenario())


def test_register_closed_403():
    async def _scenario():
        from app.config import get_settings
        from app.db import get_db
        from app.main import create_app

        closed = db_gate.test_settings().model_copy(update={"allow_registration": False})
        app = create_app()
        app.dependency_overrides[get_db] = db_gate.override_get_db
        app.dependency_overrides[get_settings] = lambda: closed
        async with db_gate.make_client(app) as client:
            r = await client.post(
                "/api/v1/auth/register",
                json={
                    "username": "closedreg",
                    "email": "closedreg@example.com",
                    "password": "secret123",
                },
            )
            assert r.status_code == 403, r.text

    _run(_scenario())
