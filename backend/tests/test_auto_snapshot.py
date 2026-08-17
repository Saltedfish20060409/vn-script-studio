"""API tests: automatic cloud backup snapshots on save."""

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


def test_put_save_creates_auto_snapshot_then_throttles():
    """First save creates an auto backup; a second save within the interval
    does not (time throttle), and unchanged content dedupes anyway."""
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "autosnap_owner")
            r = await client.post(
                "/api/v1/projects",
                json={"title": "自动备份项目", "from_demo": True},
                headers=headers,
            )
            assert r.status_code == 200, r.text
            pid = r.json()["id"]

            # First save → auto snapshot appears (server creates one on PUT).
            r = await client.put(
                f"/api/v1/projects/{pid}",
                json={
                    "updated_at": r.json()["updatedAt"],
                    "data": r.json(),
                },
                headers=headers,
            )
            assert r.status_code == 200, r.text
            snaps = (await client.get(
                f"/api/v1/projects/{pid}/snapshots", headers=headers
            )).json()
            auto = [s for s in snaps if s["label"].startswith("自动备份")]
            assert auto, "first save should produce an auto backup snapshot"
            count_after_first = len(snaps)

            # Second save right away → throttled (no new auto snapshot).
            r = await client.get(f"/api/v1/projects/{pid}", headers=headers)
            proj = r.json()
            r = await client.put(
                f"/api/v1/projects/{pid}",
                json={"updated_at": proj["updatedAt"], "data": proj},
                headers=headers,
            )
            assert r.status_code == 200, r.text
            snaps2 = (await client.get(
                f"/api/v1/projects/{pid}/snapshots", headers=headers
            )).json()
            assert len(snaps2) == count_after_first, "second save must be throttled"

    _run(_scenario())


def test_maybe_auto_snapshot_respects_min_interval():
    """Service-level: interval throttle + dedupe both return without rows."""
    from app.services.snapshots import maybe_auto_snapshot

    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "autosnap_svc")
            r = await client.post(
                "/api/v1/projects",
                json={"title": "服务层自动备份", "from_demo": True},
                headers=headers,
            )
            pid = r.json()["id"]
            proj = (await client.get(f"/api/v1/projects/{pid}", headers=headers)).json()

            from app.domain.types import VnProject

            vn = VnProject.model_validate(proj)

            async with db_gate.SessionLocal() as db:
                # fresh project, no snapshots yet → creates one
                created = await maybe_auto_snapshot(db, pid, vn, min_interval_minutes=60)
                await db.commit()
                assert created is True

                # immediately again → throttled
                created2 = await maybe_auto_snapshot(db, pid, vn, min_interval_minutes=60)
                await db.commit()
                assert created2 is False

    _run(_scenario())
