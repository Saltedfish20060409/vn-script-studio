"""API 测试：/projects/{id}/recap（模型被 mock）——范围、错误路径、鉴权。"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import db_gate
import pytest

from app.core.recap import RecapResult

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(
        not db_gate.DB_AVAILABLE,
        reason="PostgreSQL test DB unreachable (set DATABASE_URL_TEST)",
    ),
]

APP = db_gate.make_app()
PATCH_TARGET = "app.api.v1.recap.run_recap"


def _run(coro):
    return asyncio.run(coro)


async def _project_with_volumes(client, headers) -> tuple[str, list[str]]:
    """建项目 → 加两卷 → 已有章节全归第一卷 → 再补一章归第二卷。

    返回 (项目 id, 第一卷里的章节 id 列表)：示例项目的章节数与 id 都不固定，
    测试里不能写死（写成固定值会随示例内容变化而 brittle）。
    """
    r = await client.post(
        "/api/v1/projects", json={"title": "前情提要项目", "from_demo": True}, headers=headers
    )
    assert r.status_code == 200, r.text
    pid = r.json()["id"]

    r = await client.get(f"/api/v1/projects/{pid}", headers=headers)
    project = r.json()
    for ch in project["chapters"]:
        ch["volumeId"] = "v1"
    vol1_ids = [ch["id"] for ch in project["chapters"]]
    assert vol1_ids, "示例项目应该有章节"
    project["volumes"] = [
        {"id": "v1", "title": "第一卷 春"},
        {"id": "v2", "title": "第二卷 夏"},
    ]
    project["chapters"].append(
        {
            "id": "ch-new",
            "title": "夏之一",
            "blocks": [],
            "prose": "第二卷的开头。",
            "volumeId": "v2",
        }
    )
    r = await client.put(
        f"/api/v1/projects/{pid}",
        json={"data": project, "force": True},
        headers=headers,
    )
    assert r.status_code == 200, r.text
    return pid, vol1_ids


def test_recap_before_a_volume_returns_text():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "recap_user")
            pid, vol1_ids = await _project_with_volumes(client, headers)

            seen: dict[str, object] = {}

            async def fake_recap(config, **kwargs):
                seen.update(kwargs)
                assert config.apiKey == "test-key"
                return RecapResult(
                    text="林越在一具陌生的身体里醒来，先确认自己顶替了另一个人。\n尚未收回的线索：无。",
                    model="test-model",
                    chapters_used=len(kwargs["chapter_ids"]),
                    archives_used=0,
                    included=["章节×1"],
                )

            with patch(PATCH_TARGET, new=fake_recap):
                r = await client.post(
                    f"/api/v1/projects/{pid}/recap",
                    json={"volume_id": "v2", "mode": "before"},
                    headers=headers,
                )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["text"].startswith("林越")
            assert body["model"] == "test-model"
            assert body["label"] and "第二卷" in body["label"]
            assert body["chaptersUsed"] == len(vol1_ids)
            # 只把第一卷的章节交给模型（不能把第二卷的内容当前情）
            assert seen["chapter_ids"] == vol1_ids

    _run(_scenario())


def test_recap_whole_volume_mode():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "recap_vol_user")
            pid, _ = await _project_with_volumes(client, headers)
            seen: dict[str, object] = {}

            async def fake_recap(config, **kwargs):
                seen.update(kwargs)
                return RecapResult(text="回顾本卷。", chapters_used=1)

            with patch(PATCH_TARGET, new=fake_recap):
                r = await client.post(
                    f"/api/v1/projects/{pid}/recap",
                    json={"volume_id": "v2", "mode": "volume"},
                    headers=headers,
                )
            assert r.status_code == 200, r.text
            assert seen["chapter_ids"] == ["ch-new"]

    _run(_scenario())


def test_first_volume_has_nothing_to_recap_and_does_not_call_model():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "recap_first_user")
            pid, _ = await _project_with_volumes(client, headers)

            called = {"n": 0}

            async def fake_recap(config, **kwargs):  # pragma: no cover - 不该被调用
                called["n"] += 1
                return RecapResult(text="x")

            with patch(PATCH_TARGET, new=fake_recap):
                r = await client.post(
                    f"/api/v1/projects/{pid}/recap",
                    json={"volume_id": "v1", "mode": "before"},
                    headers=headers,
                )
            assert r.status_code == 400
            assert called["n"] == 0

    _run(_scenario())


def test_volume_mode_without_volume_id_is_400():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "recap_badmode_user")
            pid, _ = await _project_with_volumes(client, headers)
            r = await client.post(
                f"/api/v1/projects/{pid}/recap",
                json={"mode": "volume"},
                headers=headers,
            )
            assert r.status_code == 400

    _run(_scenario())


def test_model_error_surfaces_as_502():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "recap_err_user")
            pid, _ = await _project_with_volumes(client, headers)

            async def fake_recap(config, **kwargs):
                return RecapResult(error="生成失败：upstream 500")

            with patch(PATCH_TARGET, new=fake_recap):
                r = await client.post(
                    f"/api/v1/projects/{pid}/recap",
                    json={"volume_id": "v2", "mode": "before"},
                    headers=headers,
                )
            assert r.status_code == 502
            assert "upstream 500" in r.json()["detail"]

    _run(_scenario())


def test_recap_requires_auth_and_ownership():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "recap_owner")
            pid, _ = await _project_with_volumes(client, headers)

            r = await client.post(f"/api/v1/projects/{pid}/recap", json={})
            assert r.status_code in (401, 403)

            other = await db_gate.register_headers(client, "recap_outsider")
            r = await client.post(f"/api/v1/projects/{pid}/recap", json={}, headers=other)
            assert r.status_code == 404

    _run(_scenario())
