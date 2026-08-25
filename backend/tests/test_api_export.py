"""API tests: project markdown / docx export endpoints."""

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


def test_export_markdown_and_docx():
    """建一个 demo 项目 → markdown 导出含标题；docx 导出字节数 >1000。

    标题故意用中文：回归 Content-Disposition 非 ASCII 文件名曾导致的 500
    （Starlette latin-1 头编码），修复后走 RFC 5987 filename*。
    """

    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "exporter1")

            r = await client.post(
                "/api/v1/projects",
                json={"title": "星海拾遗·中文标题测试", "from_demo": True},
                headers=headers,
            )
            assert r.status_code == 200, r.text
            pid = r.json()["id"]
            assert pid.startswith("proj-")

            r = await client.get(
                f"/api/v1/projects/{pid}/export/markdown", headers=headers
            )
            assert r.status_code == 200, r.text
            assert "星海拾遗" in r.text
            assert r.text.lstrip().startswith("#")
            disposition = r.headers["content-disposition"]
            assert "filename*=UTF-8''" in disposition

            r = await client.get(
                f"/api/v1/projects/{pid}/export/docx", headers=headers
            )
            assert r.status_code == 200, r.text
            assert r.headers["content-type"].startswith(
                "application/vnd.openxmlformats-officedocument"
            )
            assert len(r.content) > 1000

    _run(_scenario())
