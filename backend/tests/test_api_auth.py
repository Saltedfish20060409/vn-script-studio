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
    from sqlalchemy import select

    from app.models import User
    from datetime import datetime, timezone

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
