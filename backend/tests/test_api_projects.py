"""API tests: /projects CRUD, import, and cross-user permission isolation."""

from __future__ import annotations

import asyncio
import json

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


def test_list_reports_chapter_count():
    """列表接口要给每个剧本的章数（桌面图标角标用），且与详情接口一致。"""

    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "chapters_count_owner")

            created: list[tuple[str, str]] = []
            for label, payload in (
                ("空白剧本", {"title": "空白剧本"}),
                ("示例剧本", {"title": "示例", "from_demo": True}),
            ):
                r = await client.post("/api/v1/projects", json=payload, headers=headers)
                assert r.status_code == 200, r.text
                created.append((label, r.json()["id"]))

            r = await client.get("/api/v1/projects", headers=headers)
            assert r.status_code == 200, r.text
            by_id = {p["id"]: p for p in r.json()}

            for label, pid in created:
                detail = (await client.get(f"/api/v1/projects/{pid}", headers=headers)).json()
                expected = len(detail.get("chapters") or [])
                # 新建项目至少带一章（空白剧本也有第一章）
                assert expected >= 1, f"{label} 应该有默认章节"
                assert by_id[pid]["chapters_count"] == expected, (
                    f"{label}: 列表说 {by_id[pid]['chapters_count']} 章，详情是 {expected} 章"
                )

    _run(_scenario())


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


def test_scoped_save_persists_volumes_and_map_measure():
    """卷与地图比例尺都要能被 scoped save（只声明 sections）真正写进工程。

    这两处都是"新加的项目级字段"，而保存链路是**白名单**式的：前端 diff 声明了哪一节，
    后端才从 payload 里取哪一节。漏一处就会**静默丢掉**（实测踩过：点"+卷"后卷不出现）。
    """

    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "scoped_sections")
            r = await client.post(
                "/api/v1/projects", json={"from_demo": True}, headers=headers
            )
            assert r.status_code == 200, r.text
            pid = r.json()["id"]

            r = await client.get(f"/api/v1/projects/{pid}", headers=headers)
            project = r.json()
            project["volumes"] = [{"id": "v1", "title": "第一卷"}]
            project["chapters"][0]["volumeId"] = "v1"
            project["mapMeasure"] = {
                "scale": "urban",
                "px": 100,
                "km": 1,
                "transport": "walk",
            }
            # scoped save：只声明这两节
            r = await client.put(
                f"/api/v1/projects/{pid}",
                json={
                    "data": project,
                    "sections": ["volumes", "mapMeasure"],
                    "chapter_ids": [project["chapters"][0]["id"]],
                    "force": True,
                },
                headers=headers,
            )
            assert r.status_code == 200, r.text

            r = await client.get(f"/api/v1/projects/{pid}", headers=headers)
            saved = r.json()
            assert [v["title"] for v in saved.get("volumes") or []] == ["第一卷"]
            assert saved["mapMeasure"]["scale"] == "urban"
            assert saved["mapMeasure"]["km"] == 1
            assert saved["chapters"][0]["volumeId"] == "v1"

    _run(_scenario())


def test_save_auto_populates_writing_ledger():
    """账本走「保存时自动」这条线（用户什么都不用说）。

    依据（2026-09 线上实测）：需要用户主动下命令的能力几乎没人用——agent_jobs
    累计 2 次、账本 0 个项目有内容；而"保存时自动刷新"的章节摘要 159/159 全覆盖。
    所以账本也接到保存路径上（services/projects.py::sync_row_from_vn）。
    """

    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "ledger_auto1")

            # 1) 新建（走 create_project_row）就应带账本，不用等第一次保存
            r = await client.post(
                "/api/v1/projects", json={"from_demo": True}, headers=headers
            )
            assert r.status_code == 200, r.text
            project = r.json()
            pid = project["id"]
            chapter_ids = [c["id"] for c in project["chapters"]]
            assert chapter_ids

            ledger = project.get("writingLedger") or {}
            facts = ledger.get("chapterFacts") or []
            assert facts, "新建示例项目时账本就该有内容"
            assert {f["chapterId"] for f in facts} == set(chapter_ids)
            assert all(f.get("sourceHash") for f in facts)
            assert all(f.get("facts") for f in facts)
            assert ledger.get("events")

            # 2) 保存一次不改变内容 → 幂等（没有重复行、事件不增长）
            facts_before = {f["chapterId"]: f["sourceHash"] for f in facts}
            events_before = len(ledger.get("events") or [])
            r = await client.put(
                f"/api/v1/projects/{pid}",
                json={"data": project},
                headers=headers,
            )
            assert r.status_code == 200, r.text
            saved = r.json()
            ledger2 = saved.get("writingLedger") or {}
            assert len(ledger2.get("chapterFacts") or []) == len(facts)
            assert len(ledger2.get("events") or []) == events_before
            assert {
                f["chapterId"]: f["sourceHash"] for f in ledger2["chapterFacts"]
            } == facts_before

            # 3) 改一章正文再保存 → 只有这一章的指纹变化，账本被重算
            target = saved["chapters"][0]
            blocks = list(target.get("blocks") or [])
            speaker = (saved.get("characters") or [{}])[0].get("id") or "char1"
            blocks.append(
                {"type": "dialogue", "characterId": speaker, "text": "新增的一句台词。"}
            )
            saved["chapters"][0] = {**target, "blocks": blocks}
            r = await client.put(
                f"/api/v1/projects/{pid}",
                json={"data": saved, "chapter_ids": [target["id"]]},
                headers=headers,
            )
            assert r.status_code == 200, r.text
            ledger3 = r.json().get("writingLedger") or {}
            after = {f["chapterId"]: f["sourceHash"] for f in ledger3["chapterFacts"]}
            assert after[target["id"]] != facts_before[target["id"]]
            for cid in chapter_ids:
                if cid != target["id"]:
                    assert after[cid] == facts_before[cid]
            # 幂等依然成立：事件数没有因为重算而膨胀
            assert len(ledger3.get("events") or []) == events_before

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


def test_delete_project_with_children_cascades():
    """Deleting a project that has been actively used must succeed and clean
    up child rows (chapter rows, members, comments, locks, snapshots, shares)."""
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            owner_headers = await db_gate.register_headers(client, "del_owner")
            member_headers = await db_gate.register_headers(client, "del_member")

            r = await client.post(
                "/api/v1/projects", json={"title": "要删除的项目"}, headers=owner_headers
            )
            pid = r.json()["id"]

            # Save a chapter (writes project_chapter_rows)
            proj = r.json()
            proj["chapters"] = [
                {"id": "ch1", "title": "第一章", "blocks": [{"type": "label", "id": "a", "name": "a"}]}
            ]
            r = await client.put(
                f"/api/v1/projects/{pid}",
                json={"data": proj, "updated_at": proj.get("updatedAt"), "force": True},
                headers=owner_headers,
            )
            assert r.status_code == 200, r.text

            # Add a member, a lock, a comment, a snapshot, a share
            r = await client.post(
                f"/api/v1/projects/{pid}/members",
                json={"username": "del_member", "role": "editor"},
                headers=owner_headers,
            )
            assert r.status_code == 200, r.text
            r = await client.post(
                f"/api/v1/projects/{pid}/locks/ch1", headers=member_headers
            )
            assert r.status_code == 200, r.text
            r = await client.post(
                f"/api/v1/projects/{pid}/comments",
                json={"chapter_id": "ch1", "text": "批注"},
                headers=owner_headers,
            )
            assert r.status_code == 200, r.text
            r = await client.post(
                f"/api/v1/projects/{pid}/snapshots",
                json={"label": "v1"},
                headers=owner_headers,
            )
            assert r.status_code == 200, r.text
            r = await client.post(
                f"/api/v1/projects/{pid}/shares", headers=owner_headers
            )
            assert r.status_code == 200, r.text

            # Now delete — must succeed and cascade everything.
            r = await client.delete(f"/api/v1/projects/{pid}", headers=owner_headers)
            assert r.status_code == 200, r.text

            # Project gone.
            r = await client.get(f"/api/v1/projects/{pid}", headers=owner_headers)
            assert r.status_code == 404

            # Child rows gone from the DB.
            from sqlalchemy import text
            from sqlalchemy.ext.asyncio import create_async_engine

            engine = create_async_engine(
                db_gate.TEST_DB_URL
                if hasattr(db_gate, "TEST_DB_URL")
                else "postgresql+asyncpg://vnss:vnss@localhost:54102/vnss_test"
            )
            async with engine.connect() as conn:
                for table in (
                    "project_chapter_rows",
                    "project_members",
                    "chapter_locks",
                    "project_comments",
                    "project_snapshots",
                    "shares",
                ):
                    r2 = await conn.execute(
                        text(f"SELECT count(*) FROM {table} WHERE project_id = :p"),
                        {"p": pid},
                    )
                    assert r2.scalar() == 0, f"{table} 残留行"
            await engine.dispose()

    _run(_scenario())


def test_project_stats_reports_words_and_activity():
    """Saving chapters records word deltas; /stats aggregates them."""
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "stats_owner")

            r = await client.post(
                "/api/v1/projects", json={"title": "统计项目"}, headers=headers
            )
            pid = r.json()["id"]

            # Save a chapter with prose → should record activity delta.
            proj = r.json()
            proj["chapters"] = [
                {
                    "id": "ch1",
                    "title": "第一章",
                    "blocks": [
                        {"type": "label", "id": "a", "name": "a"},
                        {"type": "narration", "text": "雨夜，末班车从站台缓缓开出。"},
                        {"type": "dialogue", "characterId": "lx", "text": "我们走吧"},
                    ],
                }
            ]
            r = await client.put(
                f"/api/v1/projects/{pid}",
                json={"data": proj, "updated_at": proj.get("updatedAt"), "force": True},
                headers=headers,
            )
            assert r.status_code == 200, r.text

            # Stats endpoint reports per-chapter words and today's activity.
            r = await client.get(f"/api/v1/projects/{pid}/stats", headers=headers)
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["totals"]["chapters"] == 1
            assert body["totals"]["words"] == 16  # 12 narration + 4 dialogue
            assert body["chapters"][0]["words"] == 16
            assert body["chapters"][0]["dialogueRatio"] == round(4 / 16, 3)
            assert body["chapters"][0]["speakers"] == ["lx"]
            assert len(body["activity"]) >= 1
            assert body["activity"][-1]["net"] == 16
            assert body["activity"][-1]["edits"] == 1

    _run(_scenario())


def test_templates_list_and_create():
    """GET /projects/templates lists scaffolds; POST with template_id creates."""
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "tmpl_owner")

            r = await client.get("/api/v1/projects/templates", headers=headers)
            assert r.status_code == 200, r.text
            templates = r.json()["templates"]
            ids = {t["id"] for t in templates}
            assert {"slice_of_life", "mystery", "isekai"} <= ids

            r = await client.post(
                "/api/v1/projects",
                json={"template_id": "mystery", "title": "我的谜题"},
                headers=headers,
            )
            assert r.status_code == 200, r.text
            proj = r.json()
            assert proj["title"] == "我的谜题"
            assert len(proj["chapters"]) == 1
            # Fresh ids (not the template's canned ones).
            assert proj["chapters"][0]["id"] != "start"

            # Unknown template → 400 (not silent, not 500).
            r2 = await client.post(
                "/api/v1/projects",
                json={"template_id": "does-not-exist"},
                headers=headers,
            )
            assert r2.status_code == 400

    _run(_scenario())
