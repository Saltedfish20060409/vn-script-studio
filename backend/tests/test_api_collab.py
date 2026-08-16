"""API tests: collaboration — members, chapter locks, permission roles."""

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


def _mk_project():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            owner_headers = await db_gate.register_headers(client, "collab_owner")
            r = await client.post(
                "/api/v1/projects",
                json={"title": "协作项目"},
                headers=owner_headers,
            )
            assert r.status_code == 200, r.text
            return {"pid": r.json()["id"], "owner": owner_headers}

    return _run(_scenario())


def test_member_crud_and_roles():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            owner_headers = await db_gate.register_headers(client, "c_owner_a")
            editor_headers = await db_gate.register_headers(client, "c_editor_a")
            viewer_headers = await db_gate.register_headers(client, "c_viewer_a")
            outsider_headers = await db_gate.register_headers(client, "c_outsider_a")

            r = await client.post(
                "/api/v1/projects", json={"title": "协作A"}, headers=owner_headers
            )
            pid = r.json()["id"]

            # add editor + viewer
            r = await client.post(
                f"/api/v1/projects/{pid}/members",
                json={"username": "c_editor_a", "role": "editor"},
                headers=owner_headers,
            )
            assert r.status_code == 200, r.text
            r = await client.post(
                f"/api/v1/projects/{pid}/members",
                json={"username": "c_viewer_a", "role": "viewer"},
                headers=owner_headers,
            )
            assert r.status_code == 200, r.text

            # owner lists members (owner row synthesized + 2 members)
            r = await client.get(f"/api/v1/projects/{pid}/members", headers=owner_headers)
            assert r.status_code == 200
            body = r.json()
            assert body["owner"]["username"] == "c_owner_a"
            assert len(body["members"]) == 2

            # editor can read project (was 404 before membership)
            r = await client.get(f"/api/v1/projects/{pid}", headers=editor_headers)
            assert r.status_code == 200, r.text

            # viewer can read but not write (patch title → 403)
            r = await client.get(f"/api/v1/projects/{pid}", headers=viewer_headers)
            assert r.status_code == 200
            r = await client.patch(
                f"/api/v1/projects/{pid}",
                json={"title": "改名"},
                headers=viewer_headers,
            )
            assert r.status_code == 403

            # outsider still 404 (existence not leaked)
            r = await client.get(f"/api/v1/projects/{pid}", headers=outsider_headers)
            assert r.status_code == 404

            # non-owner cannot manage members
            r = await client.post(
                f"/api/v1/projects/{pid}/members",
                json={"username": "c_outsider_a", "role": "viewer"},
                headers=editor_headers,
            )
            assert r.status_code == 403

            # remove viewer → back to 404 for them
            r = await client.delete(
                f"/api/v1/projects/{pid}/members/{body['members'][1]['userId']}",
                headers=owner_headers,
            )
            assert r.status_code == 200, r.text
            r = await client.get(f"/api/v1/projects/{pid}", headers=viewer_headers)
            assert r.status_code == 404

    _run(_scenario())


def test_invite_link_joins_member():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            owner_headers = await db_gate.register_headers(client, "inv_owner")
            joiner_headers = await db_gate.register_headers(client, "inv_joiner")

            r = await client.post(
                "/api/v1/projects", json={"title": "邀请项目"}, headers=owner_headers
            )
            pid = r.json()["id"]

            # owner creates invite
            r = await client.post(
                f"/api/v1/projects/{pid}/invites",
                json={"role": "editor"},
                headers=owner_headers,
            )
            assert r.status_code == 200, r.text
            token = r.json()["token"]
            assert token

            # list invites shows it
            r = await client.get(f"/api/v1/projects/{pid}/invites", headers=owner_headers)
            assert r.status_code == 200
            assert any(i["token"] == token for i in r.json()["invites"])

            # joiner accepts → becomes editor, invite consumed
            r = await client.post(
                "/api/v1/projects/invites/accept",
                json={"token": token},
                headers=joiner_headers,
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["projectId"] == pid
            assert body["alreadyMember"] is False
            assert body["role"] == "editor"

            # joiner can now read + write
            r = await client.get(f"/api/v1/projects/{pid}", headers=joiner_headers)
            assert r.status_code == 200
            r = await client.patch(
                f"/api/v1/projects/{pid}",
                json={"title": "改"},
                headers=joiner_headers,
            )
            assert r.status_code == 200

            # invite is one-time (consumed)
            r = await client.get(f"/api/v1/projects/{pid}/invites", headers=owner_headers)
            assert not any(i["token"] == token for i in r.json()["invites"])

            # accepting again is idempotent (already member)
            r = await client.post(
                "/api/v1/projects/invites/accept",
                json={"token": token},
                headers=joiner_headers,
            )
            assert r.status_code == 404  # invite gone → invalid

    _run(_scenario())


def test_chapter_lock_lifecycle():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            owner_headers = await db_gate.register_headers(client, "lock_owner")
            other_headers = await db_gate.register_headers(client, "lock_other")

            r = await client.post(
                "/api/v1/projects", json={"title": "锁项目"}, headers=owner_headers
            )
            pid = r.json()["id"]
            ch = "ch1"

            # owner locks chapter
            r = await client.post(
                f"/api/v1/projects/{pid}/locks/{ch}", headers=owner_headers
            )
            assert r.status_code == 200, r.text
            assert r.json()["chapterId"] == ch

            # list shows the lock
            r = await client.get(f"/api/v1/projects/{pid}/locks", headers=owner_headers)
            assert r.status_code == 200
            assert any(l["chapterId"] == ch for l in r.json()["locks"])

            # other user (non-member) → 404
            r = await client.post(
                f"/api/v1/projects/{pid}/locks/{ch}", headers=other_headers
            )
            assert r.status_code == 404

            # owner releases → gone
            r = await client.delete(
                f"/api/v1/projects/{pid}/locks/{ch}", headers=owner_headers
            )
            assert r.status_code == 200
            r = await client.get(f"/api/v1/projects/{pid}/locks", headers=owner_headers)
            assert not any(l["chapterId"] == ch for l in r.json()["locks"])

    _run(_scenario())
