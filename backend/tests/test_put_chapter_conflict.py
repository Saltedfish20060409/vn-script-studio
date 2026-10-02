"""P0 hotfix: chapter-scoped PUT must honor updated_at conflict (409)."""

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


def test_chapter_scoped_put_stale_updated_at_409():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "put409_scoped")
            r = await client.post(
                "/api/v1/projects",
                json={"title": "冲突测", "from_demo": True},
                headers=headers,
            )
            assert r.status_code == 200, r.text
            pid = r.json()["id"]

            r = await client.get(f"/api/v1/projects/{pid}", headers=headers)
            assert r.status_code == 200
            proj = r.json()
            stale_ua = proj["updatedAt"]
            ch_id = proj["chapters"][0]["id"]

            # Advance server clock via a forced save so stale_ua is behind.
            proj["chapters"][0] = {
                **proj["chapters"][0],
                "prose": (proj["chapters"][0].get("prose") or "") + "·bump",
            }
            r = await client.put(
                f"/api/v1/projects/{pid}",
                json={
                    "data": proj,
                    "updated_at": stale_ua,
                    "force": True,
                    "chapter_ids": [ch_id],
                },
                headers=headers,
            )
            assert r.status_code == 200, r.text
            fresh = r.json()
            assert fresh["updatedAt"] != stale_ua

            # Stale chapter-scoped PUT must 409 (this used to skip conflict check).
            emptyish = dict(fresh)
            emptyish["chapters"] = [
                {
                    **c,
                    "prose": "",
                    "blocks": [{"type": "label", "id": "start", "name": "start"}],
                }
                if c["id"] == ch_id
                else c
                for c in fresh["chapters"]
            ]
            r = await client.put(
                f"/api/v1/projects/{pid}",
                json={
                    "data": emptyish,
                    "updated_at": stale_ua,
                    "chapter_ids": [ch_id],
                },
                headers=headers,
            )
            assert r.status_code == 409, r.text
            detail = r.json()["detail"]
            if isinstance(detail, dict):
                msg = detail.get("message") or ""
            else:
                msg = str(detail)
            assert "刷新将获取最新数据" in msg
            assert "保留本地将覆盖服务器版本" in msg

            # force still bypasses.
            r = await client.put(
                f"/api/v1/projects/{pid}",
                json={
                    "data": emptyish,
                    "updated_at": stale_ua,
                    "force": True,
                    "chapter_ids": [ch_id],
                },
                headers=headers,
            )
            assert r.status_code == 200, r.text

    _run(_scenario())


def test_chapter_scoped_put_matching_updated_at_ok():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "put409_ok")
            r = await client.post(
                "/api/v1/projects",
                json={"title": "冲突测ok", "from_demo": True},
                headers=headers,
            )
            pid = r.json()["id"]
            proj = (await client.get(f"/api/v1/projects/{pid}", headers=headers)).json()
            ch_id = proj["chapters"][0]["id"]
            proj["chapters"][0] = {
                **proj["chapters"][0],
                "prose": "匹配时间戳可写",
            }
            r = await client.put(
                f"/api/v1/projects/{pid}",
                json={
                    "data": proj,
                    "updated_at": proj["updatedAt"],
                    "chapter_ids": [ch_id],
                },
                headers=headers,
            )
            assert r.status_code == 200, r.text

    _run(_scenario())
