"""API tests: share landing page includes chapter text previews."""

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


def test_share_returns_preview_with_chapter_text():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "pub_owner")
            r = await client.post(
                "/api/v1/projects",
                json={"title": "发布页项目", "from_demo": True},
                headers=headers,
            )
            assert r.status_code == 200, r.text
            pid = r.json()["id"]

            r = await client.post(
                f"/api/v1/projects/{pid}/shares", headers=headers
            )
            assert r.status_code == 200, r.text
            token = r.json()["token"]

            # Public endpoint — no auth headers.
            r = await client.get(f"/api/v1/shares/{token}")
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["title"] == "发布页项目"
            preview = body.get("preview") or {}
            previews = preview.get("chapterPreviews") or []
            assert previews, "demo project must yield chapter previews"
            first = previews[0]
            assert first["chapterId"] and first["title"]
            assert first["text"], "preview must include chapter text"
            stats = preview.get("stats") or {}
            assert stats.get("chapters") >= 1
            assert stats.get("words", 0) > 0
            chars = preview.get("characters") or []
            assert chars, "preview should list characters"

    _run(_scenario())


def test_share_missing_404():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            r = await client.get("/api/v1/shares/no-such-token-xyz")
            assert r.status_code == 404

    _run(_scenario())
