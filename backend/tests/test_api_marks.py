"""API 测试：/projects/{id}/marks/revise（模型被 mock）——改写 / 建议 / 错误路径。"""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import db_gate
import pytest

from app.core.mark_revise import MarkReviseResult

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(
        not db_gate.DB_AVAILABLE,
        reason="PostgreSQL test DB unreachable (set DATABASE_URL_TEST)",
    ),
]

APP = db_gate.make_app()
PATCH_TARGET = "app.api.v1.marks.revise_marked_text"


def _run(coro):
    return asyncio.run(coro)


async def _demo_project(client, headers) -> str:
    r = await client.post(
        "/api/v1/projects", json={"title": "标记批改项目", "from_demo": True}, headers=headers
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_rewrite_mark_returns_replacement():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "mark_user")
            pid = await _demo_project(client, headers)

            seen: dict[str, object] = {}

            async def fake_revise(config, **kwargs):
                seen.update(kwargs)
                assert config.apiKey == "test-key"
                return MarkReviseResult(replacement="他把手举到眼前，停了半息。", model="test-model")

            with patch(PATCH_TARGET, new=fake_revise):
                r = await client.post(
                    f"/api/v1/projects/{pid}/marks/revise",
                    json={
                        "chapter_id": "ch1",
                        "quote": "他慢慢抬起手，举到眼前。",
                        "prefix": "窗外的雾在退。",
                        "suffix": "那双手不是他的。",
                        "instruction": "更冷一点",
                        "intent": "rewrite",
                    },
                    headers=headers,
                )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["replacement"] == "他把手举到眼前，停了半息。"
            assert body["advice"] == ""
            assert body["changed"] is True
            assert body["model"] == "test-model"
            # 端点把上下文与要求如实传下去
            assert seen["quote"] == "他慢慢抬起手，举到眼前。"
            assert seen["instruction"] == "更冷一点"
            assert seen["intent"] == "rewrite"

    _run(_scenario())


def test_advice_mark_returns_advice_without_replacement():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "mark_advice_user")
            pid = await _demo_project(client, headers)

            async def fake_revise(config, **kwargs):
                assert kwargs["intent"] == "advice"
                return MarkReviseResult(advice="这里信息空转：三句都在写'感觉'。改成具体动作。")

            with patch(PATCH_TARGET, new=fake_revise):
                r = await client.post(
                    f"/api/v1/projects/{pid}/marks/revise",
                    json={"chapter_id": "ch1", "quote": "他感到一阵说不清的恐惧。", "intent": "advice"},
                    headers=headers,
                )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["advice"].startswith("这里信息空转")
            assert body["replacement"] == ""
            # advice 模式下没有改造正文，就不该标成"已改动"
            assert body["changed"] is False

    _run(_scenario())


def test_unchanged_replacement_is_flagged_as_not_changed():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "mark_same_user")
            pid = await _demo_project(client, headers)

            async def fake_revise(config, **kwargs):
                return MarkReviseResult(replacement=kwargs["quote"])  # 原样返回

            with patch(PATCH_TARGET, new=fake_revise):
                r = await client.post(
                    f"/api/v1/projects/{pid}/marks/revise",
                    json={"chapter_id": "ch1", "quote": "原句不动。"},
                    headers=headers,
                )
            assert r.status_code == 200, r.text
            assert r.json()["changed"] is False

    _run(_scenario())


def test_empty_quote_is_rejected_before_calling_model():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "mark_empty_user")
            pid = await _demo_project(client, headers)

            called = {"n": 0}

            async def fake_revise(config, **kwargs):  # pragma: no cover - 不该被调用
                called["n"] += 1
                return MarkReviseResult(replacement="x")

            with patch(PATCH_TARGET, new=fake_revise):
                r = await client.post(
                    f"/api/v1/projects/{pid}/marks/revise",
                    json={"chapter_id": "ch1", "quote": "   "},
                    headers=headers,
                )
            assert r.status_code == 400
            assert called["n"] == 0

    _run(_scenario())


def test_model_error_surfaces_as_502():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "mark_err_user")
            pid = await _demo_project(client, headers)

            async def fake_revise(config, **kwargs):
                return MarkReviseResult(error="处理失败：upstream 500")

            with patch(PATCH_TARGET, new=fake_revise):
                r = await client.post(
                    f"/api/v1/projects/{pid}/marks/revise",
                    json={"chapter_id": "ch1", "quote": "随便一句。"},
                    headers=headers,
                )
            assert r.status_code == 502
            assert "upstream 500" in r.json()["detail"]

    _run(_scenario())


def test_warnings_are_passed_through_and_candidates_returned():
    """生成后自检没修好的问题要如实回传；多候选要一次给出 1–3 版。"""

    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "mark_warn_user")
            pid = await _demo_project(client, headers)

            async def fake_revise(config, **kwargs):
                assert kwargs["candidates"] == 3
                return MarkReviseResult(
                    replacement="他把手举到眼前。",
                    candidates=["他把手举到眼前。", "他抬起手，停在半空。", "手举起来了。"],
                    warnings=["改写后长度是原文的 3.2 倍（要求接近原文）"],
                    model="test-model",
                )

            with patch(PATCH_TARGET, new=fake_revise):
                r = await client.post(
                    f"/api/v1/projects/{pid}/marks/revise",
                    json={"quote": "他慢慢抬起手，举到眼前。", "candidates": 3},
                    headers=headers,
                )
            assert r.status_code == 200, r.text
            body = r.json()
            assert len(body["candidates"]) == 3
            assert body["warnings"] and "长度" in body["warnings"][0]

    _run(_scenario())


def test_marks_hint_reports_style_memory_state():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "mark_hint_user")
            pid = await _demo_project(client, headers)

            r = await client.get(f"/api/v1/projects/{pid}/marks/hint", headers=headers)
            assert r.status_code == 200, r.text
            assert r.json()["hasStyleMemory"] is False

    _run(_scenario())


def test_marks_require_auth_and_ownership():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "mark_owner")
            pid = await _demo_project(client, headers)

            r = await client.post(
                f"/api/v1/projects/{pid}/marks/revise",
                json={"quote": "x"},
            )
            assert r.status_code in (401, 403)

            other = await db_gate.register_headers(client, "mark_outsider")
            r = await client.post(
                f"/api/v1/projects/{pid}/marks/revise",
                json={"quote": "x"},
                headers=other,
            )
            assert r.status_code == 404

    _run(_scenario())
