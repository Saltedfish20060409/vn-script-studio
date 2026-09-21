"""待审列表 → 设定条目：端到端（真库 + 真接口）。

这条链路是评论里那句话的底线：「全是自己生成、编辑自由度太小」——
AI 只能把设定**提议**进待审列表，作者勾了「接受」，条目才真的进设定库。
这里验证：提议不入库、待审列表看得到、接受才入库、同名不重复、接受后立刻可被检索。
"""

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


async def _setup(client, headers) -> str:
    r = await client.post(
        "/api/v1/projects",
        json={"title": "设定条目待审测试", "genre": "fantasy"},
        headers=headers,
    )
    assert r.status_code in (200, 201), r.text
    return r.json()["id"]


async def _insert_proposal(project_id: str, cand) -> str:  # noqa: ANN001
    from app.core.fact_extract import FactCandidate
    from app.services import analysis_inbox as inbox_svc

    if not isinstance(cand, FactCandidate):
        cand = FactCandidate(**cand)
    async with db_gate.SessionLocal() as session:
        rows = await inbox_svc.insert_candidates(session, project_id, [cand])
        await session.commit()
        assert rows, "候选没能入待审（dedupe 冲突？）"
        return rows[0].id


def test_proposed_lore_entry_lands_only_after_accept():
    async def _scenario():
        await db_gate.create_all()
        await db_gate.truncate_all()

        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "lore_reviewer")
            project_id = await _setup(client, headers)

            # 1) 模拟 AI 提议：只进待审，不进设定库
            item_id = await _insert_proposal(
                project_id,
                {
                    "kind": "lore_entry",
                    "payload": {
                        "title": "青云门",
                        "body": "正道第一大派，掌门玄真。",
                        "keywords": ["青云", "掌门"],
                    },
                    "evidence": [{"source": "agent", "quote": "附件第一节"}],
                    "dedupe_key": "lore:青云门",
                },
            )

            r = await client.get(f"/api/v1/projects/{project_id}", headers=headers)
            assert r.status_code == 200, r.text
            assert r.json().get("loreEntries") in (None, []), "提议阶段不该写入设定库"

            # 待审列表里必须看得到（否则提议等于白提）
            r = await client.get(
                f"/api/v1/projects/{project_id}/analysis/facts/inbox", headers=headers
            )
            assert r.status_code == 200, r.text
            items = [i for i in r.json()["items"] if i["kind"] == "lore_entry"]
            assert len(items) == 1
            assert items[0]["payload"]["title"] == "青云门"
            assert items[0]["payload"]["keywords"] == ["青云", "掌门"]
            assert items[0]["evidence"][0]["quote"] == "附件第一节"

            # 2) 作者接受 → 才进设定库
            r = await client.post(
                f"/api/v1/projects/{project_id}/analysis/facts/accept",
                json={"ids": [item_id]},
                headers=headers,
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["acceptedIds"] == [item_id]
            entries = body["project"]["loreEntries"]
            assert len(entries) == 1
            assert entries[0]["title"] == "青云门"
            assert entries[0]["body"].startswith("正道第一大派")
            assert entries[0]["keywords"] == ["青云", "掌门"]

            # 3) 同名再来一条：接受但判为已存在，不重复入库
            dup_id = await _insert_proposal(
                project_id,
                {
                    "kind": "lore_entry",
                    "payload": {"title": " 青云门 ", "body": "重复的写法"},
                    "evidence": [],
                    "dedupe_key": "lore:青云门-dup",
                },
            )
            r = await client.post(
                f"/api/v1/projects/{project_id}/analysis/facts/accept",
                json={"ids": [dup_id]},
                headers=headers,
            )
            assert r.status_code == 200, r.text
            assert r.json()["skippedIds"] == [dup_id]
            assert len(r.json()["project"]["loreEntries"]) == 1

    asyncio.run(_scenario())


def test_accepted_entry_is_retrievable_by_the_agent_tool():
    """接受之后，Agent 的 search_lore 立刻能取到它（不必等重建上下文）。"""

    async def _scenario():
        from app.core.agent_tools import run_agent_tool
        from app.core.fact_extract import accept_lore_entry
        from app.domain.types import VnProject

        await db_gate.create_all()
        await db_gate.truncate_all()

        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "lore_tool_user")
            project_id = await _setup(client, headers)
            r = await client.get(f"/api/v1/projects/{project_id}", headers=headers)
            assert r.status_code == 200, r.text

        vn = VnProject.model_validate(r.json())
        vn = accept_lore_entry(
            vn, title="洗剑池", body="洗剑池在后山，水深三丈。", keywords=["洗剑池"]
        )
        ok, out = run_agent_tool("search_lore", {"query": "洗剑池在哪"}, project=vn)
        assert ok
        assert "水深三丈" in out

    asyncio.run(_scenario())
