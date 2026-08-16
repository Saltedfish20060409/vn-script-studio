"""API tests: /auth register · login · me (+ error paths)."""

from __future__ import annotations

import asyncio

import pytest

import db_gate

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


def test_register_login_me_roundtrip():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            # register → token
            r = await client.post(
                "/api/v1/auth/register",
                json={"username": "alice", "password": "secret123"},
            )
            assert r.status_code == 200, r.text
            token = r.json()["access_token"]
            assert token

            # me with token
            r = await client.get(
                "/api/v1/auth/me", headers={"Authorization": f"Bearer {token}"}
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["username"] == "alice"
            assert body["id"]

            # login with the same credentials → new token
            r = await client.post(
                "/api/v1/auth/login",
                json={"username": "alice", "password": "secret123"},
            )
            assert r.status_code == 200, r.text
            assert r.json()["access_token"]

    _run(_scenario())


def test_login_wrong_password_401():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            await client.post(
                "/api/v1/auth/register",
                json={"username": "bob", "password": "secret123"},
            )
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
            payload = {"username": "carol", "password": "secret123"}
            r1 = await client.post("/api/v1/auth/register", json=payload)
            assert r1.status_code == 200, r1.text
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
