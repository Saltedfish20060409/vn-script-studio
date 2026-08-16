"""API tests: /projects CRUD, import, and cross-user permission isolation."""

from __future__ import annotations

import asyncio
import json

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


def test_create_list_rename_delete():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "owner1")

            # create
            r = await client.post(
                "/api/v1/projects",
                json={"title": "我的第一个剧本"},
                headers=headers,
            )
            assert r.status_code == 200, r.text
            project = r.json()
            pid = project["id"]
            assert pid.startswith("proj-")
            assert project["title"] == "我的第一个剧本"

            # list
            r = await client.get("/api/v1/projects", headers=headers)
            assert r.status_code == 200
            ids = [p["id"] for p in r.json()]
            assert pid in ids

            # rename (patch)
            r = await client.patch(
                f"/api/v1/projects/{pid}",
                json={"title": "改名后的剧本", "genre": "悬疑"},
                headers=headers,
            )
            assert r.status_code == 200, r.text
            assert r.json()["title"] == "改名后的剧本"
            assert r.json()["genre"] == "悬疑"

            # delete
            r = await client.delete(f"/api/v1/projects/{pid}", headers=headers)
            assert r.status_code == 200
            assert r.json()["ok"] is True

            # gone
            r = await client.get(f"/api/v1/projects/{pid}", headers=headers)
            assert r.status_code == 404

    _run(_scenario())


def test_import_json_form():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "importer")

            payload = {
                "title": "导入剧本",
                "genre": "日常",
                "characters": [
                    {
                        "id": "c1",
                        "defineName": "yuki",
                        "displayName": "雪",
                        "voice": "轻柔",
                        "bio": "图书管理员",
                    }
                ],
                "chapters": [
                    {
                        "id": "ch1",
                        "title": "第一章",
                        "blocks": [
                            {"type": "narration", "text": "今天也在下雨。"},
                            {
                                "type": "dialogue",
                                "characterId": "c1",
                                "text": "伞借你。",
                            },
                        ],
                    }
                ],
            }
            r = await client.post(
                "/api/v1/projects/import",
                data={"json_body": json.dumps(payload, ensure_ascii=False)},
                headers=headers,
            )
            assert r.status_code == 200, r.text
            project = r.json()
            assert project["title"] == "导入剧本"
            assert project["genre"] == "日常"
            assert len(project["characters"]) == 1
            assert project["characters"][0]["displayName"] == "雪"
            assert len(project["chapters"]) == 1

            # imported project appears in the owner's list
            r = await client.get("/api/v1/projects", headers=headers)
            assert any(p["id"] == project["id"] for p in r.json())

    _run(_scenario())


def test_import_rejects_bad_json_400():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "badimporter")
            r = await client.post(
                "/api/v1/projects/import",
                data={"json_body": "{not-json"},
                headers=headers,
            )
            assert r.status_code == 400

    _run(_scenario())


def test_owner_cannot_read_other_users_project_404():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            # user A owns a project
            headers_a = await db_gate.register_headers(client, "user_a")
            r = await client.post(
                "/api/v1/projects", json={"title": "A 的剧本"}, headers=headers_a
            )
            pid = r.json()["id"]

            # user B cannot read / list it
            headers_b = await db_gate.register_headers(client, "user_b")
            r = await client.get(f"/api/v1/projects/{pid}", headers=headers_b)
            assert r.status_code == 404

            r = await client.get("/api/v1/projects", headers=headers_b)
            assert all(p["id"] != pid for p in r.json())

            # B cannot rename or delete it either
            r = await client.patch(
                f"/api/v1/projects/{pid}", json={"title": "劫持"}, headers=headers_b
            )
            assert r.status_code == 404
            r = await client.delete(f"/api/v1/projects/{pid}", headers=headers_b)
            assert r.status_code == 404

            # A still owns it untouched
            r = await client.get(f"/api/v1/projects/{pid}", headers=headers_a)
            assert r.status_code == 200
            assert r.json()["title"] == "A 的剧本"

    _run(_scenario())


def test_projects_require_auth_401():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            r = await client.get("/api/v1/projects")
            assert r.status_code == 401
            r = await client.post("/api/v1/projects", json={"title": "x"})
            assert r.status_code == 401

    _run(_scenario())
