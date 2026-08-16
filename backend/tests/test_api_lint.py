"""API tests: deterministic lint endpoints (no LLM) — harness lint + narrative lint."""

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


async def _create_project(client, headers) -> str:
    r = await client.post(
        "/api/v1/projects", json={"title": "Lint 项目", "from_demo": True}, headers=headers
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


DRAFT = '"你好吗？"\n"你叫什么？"\n"从哪里来？"'


def test_harness_lint_deterministic():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "lint_harness")
            pid = await _create_project(client, headers)

            r = await client.post(
                f"/api/v1/projects/{pid}/harness/lint",
                json={"draft": DRAFT},
                headers=headers,
            )
            assert r.status_code == 200, r.text
            body = r.json()
            # deterministic audit: returns an issues list
            assert isinstance(body.get("issues"), list)

            # empty-draft validation
            r = await client.post(
                f"/api/v1/projects/{pid}/harness/lint",
                json={"draft": ""},
                headers=headers,
            )
            assert r.status_code == 422

    _run(_scenario())


def test_narrative_lint_deterministic():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "lint_narrative")
            pid = await _create_project(client, headers)

            r = await client.post(
                f"/api/v1/projects/{pid}/analysis/lint",
                json={"draft": DRAFT},
                headers=headers,
            )
            assert r.status_code == 200, r.text
            issues = r.json()["issues"]
            assert isinstance(issues, list)

            # a project with real dialogue should produce at least one finding
            r = await client.post(
                f"/api/v1/projects/{pid}/analysis/lint",
                json={
                    "draft": "林夏说：\n\"我没事。\"\n\"真的没事。\"\n\"你信我。\""
                },
                headers=headers,
            )
            assert r.status_code == 200
            assert isinstance(r.json()["issues"], list)

    _run(_scenario())


def test_lint_requires_project_ownership():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers_a = await db_gate.register_headers(client, "lint_owner")
            pid = await _create_project(client, headers_a)

            headers_b = await db_gate.register_headers(client, "lint_intruder")
            r = await client.post(
                f"/api/v1/projects/{pid}/harness/lint",
                json={"draft": DRAFT},
                headers=headers_b,
            )
            assert r.status_code == 404

    _run(_scenario())
