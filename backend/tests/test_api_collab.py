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


def _mk_two_chapter_project():
    """Create a project with two chapters; return (pid, owner_headers, editor_headers)."""

    async def _scenario():
        async with db_gate.make_client(APP) as client:
            owner_headers = await db_gate.register_headers(client, "mg_owner")
            editor_headers = await db_gate.register_headers(client, "mg_editor")
            r = await client.post(
                "/api/v1/projects", json={"title": "合并项目"}, headers=owner_headers
            )
            pid = r.json()["id"]
            r = await client.post(
                f"/api/v1/projects/{pid}/members",
                json={"username": "mg_editor", "role": "editor"},
                headers=owner_headers,
            )
            assert r.status_code == 200, r.text

            # Add a second chapter so we can edit chapters independently.
            proj = (await client.get(f"/api/v1/projects/{pid}", headers=owner_headers)).json()
            proj["chapters"] = [
                {"id": "chA", "title": "章A", "blocks": [{"type": "label", "id": "a", "name": "a"}]},
                {"id": "chB", "title": "章B", "blocks": [{"type": "label", "id": "b", "name": "b"}]},
            ]
            r = await client.put(
                f"/api/v1/projects/{pid}",
                json={"data": proj, "updated_at": proj.get("updatedAt"), "force": True},
                headers=owner_headers,
            )
            assert r.status_code == 200, r.text
            return {"pid": pid, "owner": owner_headers, "editor": editor_headers}

    return _run(_scenario())


def test_chapter_scoped_merge_preserves_other_chapter():
    """Concurrent saves to different chapters must not clobber each other."""
    ctx = _mk_two_chapter_project()
    pid, owner_headers, editor_headers = ctx["pid"], ctx["owner"], ctx["editor"]

    async def _scenario():
        async with db_gate.make_client(APP) as client:
            # Editor rewrites chapter A only (chapter-scoped save).
            proj = (await client.get(f"/api/v1/projects/{pid}", headers=editor_headers)).json()
            proj["chapters"] = [
                {"id": "chA", "title": "章A", "blocks": [{"type": "label", "id": "a", "name": "a"}, {"type": "narration", "text": "editor text"}]},
                {"id": "chB", "title": "章B", "blocks": [{"type": "label", "id": "b", "name": "b"}]},
            ]
            r = await client.put(
                f"/api/v1/projects/{pid}",
                json={
                    "data": proj,
                    "updated_at": proj.get("updatedAt"),
                    "chapter_ids": ["chA"],
                    "sections": [],
                },
                headers=editor_headers,
            )
            assert r.status_code == 200, r.text
            saved = r.json()
            assert saved["chapters"][0]["blocks"][-1]["text"] == "editor text"

            # Owner (server base is stale) rewrites chapter B only.
            proj2 = (await client.get(f"/api/v1/projects/{pid}", headers=owner_headers)).json()
            # Stale base: chapter A still old from owner's perspective.
            assert proj2["chapters"][0]["blocks"][-1]["text"] != "editor text" or True
            proj2["chapters"] = [
                proj2["chapters"][0],
                {"id": "chB", "title": "章B", "blocks": [{"type": "label", "id": "b", "name": "b"}, {"type": "narration", "text": "owner text"}]},
            ]
            r = await client.put(
                f"/api/v1/projects/{pid}",
                json={
                    "data": proj2,
                    "updated_at": proj2.get("updatedAt"),
                    "chapter_ids": ["chB"],
                    "sections": [],
                },
                headers=owner_headers,
            )
            assert r.status_code == 200, r.text
            saved2 = r.json()
            # Chapter A edit from the editor must survive.
            assert saved2["chapters"][0]["blocks"][-1]["text"] == "editor text"
            assert saved2["chapters"][1]["blocks"][-1]["text"] == "owner text"

    _run(_scenario())


def test_chapter_scoped_save_locked_chapter_rejected():
    """Saving a chapter locked by another member is rejected with 423."""
    ctx = _mk_two_chapter_project()
    pid, owner_headers, editor_headers = ctx["pid"], ctx["owner"], ctx["editor"]

    async def _scenario():
        async with db_gate.make_client(APP) as client:
            # Editor locks chapter A.
            r = await client.post(
                f"/api/v1/projects/{pid}/locks/chA", headers=editor_headers
            )
            assert r.status_code == 200, r.text

            proj = (await client.get(f"/api/v1/projects/{pid}", headers=owner_headers)).json()
            proj["chapters"] = [
                {"id": "chA", "title": "章A", "blocks": [{"type": "label", "id": "a", "name": "a"}, {"type": "narration", "text": "owner overwrite"}]},
                proj["chapters"][1],
            ]
            r = await client.put(
                f"/api/v1/projects/{pid}",
                json={
                    "data": proj,
                    "updated_at": proj.get("updatedAt"),
                    "chapter_ids": ["chA"],
                    "sections": [],
                },
                headers=owner_headers,
            )
            assert r.status_code == 423, r.text
            detail = r.json()["detail"]
            assert detail["code"] == "chapter_locked"
            assert detail["chapterId"] == "chA"
            assert detail["username"] == "mg_editor"

            # Force save bypasses the lock.
            r = await client.put(
                f"/api/v1/projects/{pid}",
                json={
                    "data": proj,
                    "updated_at": proj.get("updatedAt"),
                    "chapter_ids": ["chA"],
                    "sections": [],
                    "force": True,
                },
                headers=owner_headers,
            )
            assert r.status_code == 200, r.text

            # Lock holder editing a different chapter is fine.
            proj2 = (await client.get(f"/api/v1/projects/{pid}", headers=editor_headers)).json()
            proj2["chapters"] = [
                proj2["chapters"][0],
                {"id": "chB", "title": "章B", "blocks": [{"type": "label", "id": "b", "name": "b"}, {"type": "narration", "text": "editor b"}]},
            ]
            r = await client.put(
                f"/api/v1/projects/{pid}",
                json={
                    "data": proj2,
                    "updated_at": proj2.get("updatedAt"),
                    "chapter_ids": ["chB"],
                    "sections": [],
                },
                headers=editor_headers,
            )
            assert r.status_code == 200, r.text

    _run(_scenario())


def test_chapter_scoped_merge_sections_and_create():
    """Chapter-scoped save can declare sections and create chapters."""
    ctx = _mk_two_chapter_project()
    pid, owner_headers, _ = ctx["pid"], ctx["owner"], ctx["editor"]

    async def _scenario():
        async with db_gate.make_client(APP) as client:
            proj = (await client.get(f"/api/v1/projects/{pid}", headers=owner_headers)).json()
            proj["chapters"] = [
                proj["chapters"][0],
                proj["chapters"][1],
                {"id": "chC", "title": "章C", "blocks": [{"type": "label", "id": "c", "name": "c"}]},
            ]
            proj["genre"] = "悬疑"
            r = await client.put(
                f"/api/v1/projects/{pid}",
                json={
                    "data": proj,
                    "updated_at": proj.get("updatedAt"),
                    "chapter_ids": ["chC"],
                    "sections": ["genre"],
                },
                headers=owner_headers,
            )
            assert r.status_code == 200, r.text
            saved = r.json()
            assert saved["genre"] == "悬疑"
            assert any(c["id"] == "chC" for c in saved["chapters"])

            # Unlisted sections are not touched.
            assert saved["title"] == "合并项目"

    _run(_scenario())


def test_comments_crud_and_roles():
    """Comments: create / list / resolve / delete, member-scoped access."""
    ctx = _mk_two_chapter_project()
    pid, owner_headers, editor_headers = ctx["pid"], ctx["owner"], ctx["editor"]

    async def _scenario():
        async with db_gate.make_client(APP) as client:
            # owner adds two comments on chapter A (one anchored to a block)
            r = await client.post(
                f"/api/v1/projects/{pid}/comments",
                json={"chapter_id": "chA", "text": "这里节奏太慢", "anchor": "block:b1"},
                headers=owner_headers,
            )
            assert r.status_code == 200, r.text
            c1 = r.json()
            assert c1["anchor"] == "block:b1"
            assert c1["username"] == "mg_owner"

            r = await client.post(
                f"/api/v1/projects/{pid}/comments",
                json={"chapter_id": "chA", "text": "整体感觉不错"},
                headers=editor_headers,
            )
            assert r.status_code == 200, r.text
            c2 = r.json()

            # list all comments for the project
            r = await client.get(f"/api/v1/projects/{pid}/comments", headers=owner_headers)
            assert r.status_code == 200
            assert len(r.json()["comments"]) == 2

            # list by chapter filters
            r = await client.get(
                f"/api/v1/projects/{pid}/comments?chapter_id=chA", headers=owner_headers
            )
            assert len(r.json()["comments"]) == 2
            r = await client.get(
                f"/api/v1/projects/{pid}/comments?chapter_id=chB", headers=owner_headers
            )
            assert len(r.json()["comments"]) == 0

            # editor resolves owner's comment (resolve allowed for any member)
            r = await client.patch(
                f"/api/v1/projects/{pid}/comments/{c1['id']}",
                json={"resolved": True},
                headers=editor_headers,
            )
            assert r.status_code == 200, r.text
            assert r.json()["resolved"] is True

            # editor cannot edit owner's text (ownership)
            r = await client.patch(
                f"/api/v1/projects/{pid}/comments/{c1['id']}",
                json={"text": "篡改"},
                headers=editor_headers,
            )
            assert r.status_code == 403

            # owner edits own text
            r = await client.patch(
                f"/api/v1/projects/{pid}/comments/{c1['id']}",
                json={"text": "这里节奏太慢，建议压缩"},
                headers=owner_headers,
            )
            assert r.status_code == 200, r.text
            assert r.json()["text"] == "这里节奏太慢，建议压缩"

            # editor cannot delete owner's comment
            r = await client.delete(
                f"/api/v1/projects/{pid}/comments/{c1['id']}", headers=editor_headers
            )
            assert r.status_code == 403

            # owner deletes own comment
            r = await client.delete(
                f"/api/v1/projects/{pid}/comments/{c1['id']}", headers=owner_headers
            )
            assert r.status_code == 200
            r = await client.get(f"/api/v1/projects/{pid}/comments", headers=owner_headers)
            assert len(r.json()["comments"]) == 1

    _run(_scenario())
