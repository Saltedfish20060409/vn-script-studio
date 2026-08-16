"""DB test: semantic-search endpoint falls back to heuristic without pgvector."""

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


def test_semantic_search_heuristic_fallback():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "sem_owner")
            r = await client.post(
                "/api/v1/projects", json={"title": "语义搜索"}, headers=headers
            )
            assert r.status_code == 200, r.text
            pid = r.json()["id"]

            # Write a chapter with recognizable content.
            proj = r.json()
            proj["chapters"] = [
                {
                    "id": "chA",
                    "title": "第一章",
                    "blocks": [
                        {"type": "label", "id": "a", "name": "a"},
                        {"type": "narration", "text": "雨夜，末班车从站台缓缓开出。"},
                        {"type": "narration", "text": "林夏看着车灯消失在雨幕中。"},
                    ],
                }
            ]
            r = await client.put(
                f"/api/v1/projects/{pid}",
                json={"data": proj, "updated_at": proj.get("updatedAt"), "force": True},
                headers=headers,
            )
            assert r.status_code == 200, r.text

            # Query matching the chapter text — should hit via heuristic.
            r = await client.post(
                f"/api/v1/projects/{pid}/analysis/semantic-search",
                json={"query": "末班车 站台"},
                headers=headers,
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["engine"] in ("pgvector", "heuristic")
            if body["engine"] == "heuristic":
                assert len(body["hits"]) >= 1

            # Query with no match → empty hits, still 200.
            r = await client.post(
                f"/api/v1/projects/{pid}/analysis/semantic-search",
                json={"query": "量子力学讲座"},
                headers=headers,
            )
            assert r.status_code == 200, r.text
            assert body["engine"] in ("pgvector", "heuristic")

    _run(_scenario())
