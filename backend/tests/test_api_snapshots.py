"""API tests: /projects/{id}/snapshots create · list · restore · delete (+dedupe)."""

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


async def _create_project(client, headers, title="快照项目") -> str:
    r = await client.post(
        "/api/v1/projects", json={"title": title, "from_demo": True}, headers=headers
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_snapshot_create_list_delete():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "snap_user")
            pid = await _create_project(client, headers)

            # create
            r = await client.post(
                f"/api/v1/projects/{pid}/snapshots",
                json={"label": "第一版"},
                headers=headers,
            )
            assert r.status_code == 200, r.text
            snap = r.json()
            snap_id = snap["id"]
            assert snap["label"] == "第一版"
            assert snap["deduped"] is False
            assert snap["contentHash"]

            # list
            r = await client.get(f"/api/v1/projects/{pid}/snapshots", headers=headers)
            assert r.status_code == 200
            items = r.json()
            assert len(items) == 1
            assert items[0]["id"] == snap_id
            assert items[0]["label"] == "第一版"

            # delete
            r = await client.delete(
                f"/api/v1/projects/{pid}/snapshots/{snap_id}", headers=headers
            )
            assert r.status_code == 200
            assert r.json()["ok"] is True

            # gone
            r = await client.get(f"/api/v1/projects/{pid}/snapshots", headers=headers)
            assert r.json() == []

            # deleting again → 404
            r = await client.delete(
                f"/api/v1/projects/{pid}/snapshots/{snap_id}", headers=headers
            )
            assert r.status_code == 404

    _run(_scenario())


def test_snapshot_dedupe_identical_content():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "dedupe_user")
            pid = await _create_project(client, headers)

            r1 = await client.post(
                f"/api/v1/projects/{pid}/snapshots",
                json={"label": "v1"},
                headers=headers,
            )
            first = r1.json()
            assert first["deduped"] is False

            # identical project content → deduped, same row id
            r2 = await client.post(
                f"/api/v1/projects/{pid}/snapshots",
                json={"label": "v1 again"},
                headers=headers,
            )
            second = r2.json()
            assert second["deduped"] is True
            assert second["id"] == first["id"]
            assert second["contentHash"] == first["contentHash"]

            # still exactly one snapshot row
            r = await client.get(f"/api/v1/projects/{pid}/snapshots", headers=headers)
            assert len(r.json()) == 1

    _run(_scenario())


def test_snapshot_restore_reverts_changes():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "restore_user")
            pid = await _create_project(client, headers, title="原始标题")

            r = await client.post(
                f"/api/v1/projects/{pid}/snapshots",
                json={"label": "baseline"},
                headers=headers,
            )
            snap_id = r.json()["id"]

            # change the project after the snapshot
            r = await client.patch(
                f"/api/v1/projects/{pid}",
                json={"title": "改动后的标题"},
                headers=headers,
            )
            assert r.json()["title"] == "改动后的标题"

            # restore → title reverts to the snapshot's payload
            r = await client.post(
                f"/api/v1/projects/{pid}/snapshots/{snap_id}/restore",
                headers=headers,
            )
            assert r.status_code == 200, r.text
            assert r.json()["title"] == "原始标题"

            # persisted in DB
            r = await client.get(f"/api/v1/projects/{pid}", headers=headers)
            assert r.json()["title"] == "原始标题"

    _run(_scenario())


def test_snapshot_restore_missing_404():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "missing_snap")
            pid = await _create_project(client, headers)
            r = await client.post(
                f"/api/v1/projects/{pid}/snapshots/no-such-snap/restore",
                headers=headers,
            )
            assert r.status_code == 404

    _run(_scenario())
