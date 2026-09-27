"""保存路径的长度上限：超长字段必须是 400 + 说清是哪一项，而不是 500。

**这是那次线上故障的回归用例**（2026-09-26）：
用户在「类型 / 题材」贴了一段长文本 → Postgres `value too long for
character varying(128)` → DataError 没人接 → 500（响应体只有
`Internal Server Error`）→ 界面显示"保存失败"，而**此后每次自动保存都继续失败**，
那个项目的改动一直没落盘（连续 15 次全 500）。

所以这里钉三件事：
1. 超长 genre → 400，且错误信息里有人话（字段名 + 上限 + 现在多少字）；
2. 超长 title → 400；
3. **修好之后必须还能正常保存** —— 只钉"会拒绝"会让这条路彻底走不通。
"""

from __future__ import annotations

import asyncio

import db_gate
import pytest

from app.core.field_limits import GENRE_LABEL, GENRE_MAX, TITLE_LABEL, TITLE_MAX

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(
        not db_gate.DB_AVAILABLE,
        reason="PostgreSQL test DB unreachable (set DATABASE_URL_TEST)",
    ),
]

APP = db_gate.make_app()


def test_overlong_genre_is_400_not_500_and_says_which_field():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "limit_genre")
            r = await client.post(
                "/api/v1/projects", json={"title": "超长类型项目"}, headers=headers
            )
            assert r.status_code == 200, r.text
            pid = r.json()["id"]
            proj = (
                await client.get(f"/api/v1/projects/{pid}", headers=headers)
            ).json()

            proj["genre"] = "科幻" * 80  # 160 字，超过 varchar(128)
            r = await client.put(
                f"/api/v1/projects/{pid}", json={"data": proj}, headers=headers
            )
            assert r.status_code == 400, (
                f"超长 genre 应当是 400（可读原因），实际 {r.status_code}: {r.text[:200]}"
            )
            detail = r.json()["detail"]
            assert GENRE_LABEL in detail
            assert str(GENRE_MAX) in detail
            assert "Internal Server Error" not in detail

            # 修好之后必须能存进去（否则等于把用户的路堵死）
            proj["genre"] = "科幻"
            r = await client.put(
                f"/api/v1/projects/{pid}", json={"data": proj}, headers=headers
            )
            assert r.status_code == 200, r.text
            assert r.json()["genre"] == "科幻"

    asyncio.run(_scenario())


def test_overlong_title_is_rejected_on_create_and_patch():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "limit_title")

            r = await client.post(
                "/api/v1/projects",
                json={"title": "题" * (TITLE_MAX + 1)},
                headers=headers,
            )
            assert r.status_code == 400, r.text
            assert TITLE_LABEL in r.json()["detail"]

            r = await client.post(
                "/api/v1/projects", json={"title": "正常标题"}, headers=headers
            )
            assert r.status_code == 200, r.text
            pid = r.json()["id"]

            # PATCH 是重命名路径（桌面右键 / 剧本库改名都走它）
            r = await client.patch(
                f"/api/v1/projects/{pid}",
                json={"title": "长" * (TITLE_MAX + 1)},
                headers=headers,
            )
            assert r.status_code == 400, r.text
            assert TITLE_LABEL in r.json()["detail"]

            r = await client.patch(
                f"/api/v1/projects/{pid}", json={"title": "改名后"}, headers=headers
            )
            assert r.status_code == 200, r.text
            assert r.json()["title"] == "改名后"

    asyncio.run(_scenario())


def test_scoped_save_is_not_rejected_for_an_untouched_long_field():
    """分章保存只合并声明过的顶层字段：没声明的超长值不该拦下一次"只改正文"的保存。

    这条防的是"修 bug 修出假 400"：客户端手里存着旧的超长 genre（例如用户还没去改），
    而这次保存只声明了 chapter_ids —— 它根本不会写进 genre 列，就不该被拒。
    """

    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "limit_scoped")
            r = await client.post(
                "/api/v1/projects", json={"title": "分章保存项目"}, headers=headers
            )
            assert r.status_code == 200, r.text
            pid = r.json()["id"]
            proj = (
                await client.get(f"/api/v1/projects/{pid}", headers=headers)
            ).json()
            chapter_id = proj["chapters"][0]["id"]
            proj["chapters"][0]["prose"] = "正文改了一下"

            proj["genre"] = "类" * (GENRE_MAX + 1)  # 客户端里的超长值，但这次不写它
            r = await client.put(
                f"/api/v1/projects/{pid}",
                json={"data": proj, "chapter_ids": [chapter_id]},
                headers=headers,
            )
            assert r.status_code == 200, (
                f"只声明了 chapter_ids 时不该因为未声明的超长字段被拒: {r.text[:200]}"
            )

    asyncio.run(_scenario())
