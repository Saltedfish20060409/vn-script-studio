"""API tests: POST /projects/{id}/voice-check (LLM mocked) + voiceReports persistence."""

from __future__ import annotations

import asyncio
from unittest.mock import patch

import db_gate
import pytest

from app.core.voice_check import VoiceIssue, VoiceReport

pytestmark = [
    pytest.mark.db,
    pytest.mark.skipif(
        not db_gate.DB_AVAILABLE,
        reason="PostgreSQL test DB unreachable (set DATABASE_URL_TEST)",
    ),
]

APP = db_gate.make_app()

PATCH_TARGET = "app.api.v1.projects.run_voice_check"


def _run(coro):
    return asyncio.run(coro)


async def _create_demo_project(client, headers) -> str:
    r = await client.post(
        "/api/v1/projects", json={"title": "声线检查项目", "from_demo": True}, headers=headers
    )
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_voice_check_endpoint_and_persistence():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "voice_user")
            pid = await _create_demo_project(client, headers)

            async def fake_voice_check(config, project, chapterId=None):
                assert config.apiKey == "test-key"
                return VoiceReport(
                    summary="整体稳定，霖夏的克制感保持良好。",
                    issues=[
                        VoiceIssue(
                            character="林夏",
                            severity="info",
                            quote="伞借你。",
                            note="符合人设",
                            suggestion="保持即可",
                        )
                    ],
                    model="test-model",
                )

            with patch(PATCH_TARGET, new=fake_voice_check):
                r = await client.post(
                    f"/api/v1/projects/{pid}/voice-check",
                    json={"chapter_id": "ch1"},
                    headers=headers,
                )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["summary"] == "整体稳定，霖夏的克制感保持良好。"
            assert body["model"] == "test-model"
            assert body["persisted"] is True
            assert len(body["issues"]) == 1
            assert body["issues"][0]["character"] == "林夏"

            # report is persisted in project JSONB (voiceReports non-empty)
            r = await client.get(f"/api/v1/projects/{pid}", headers=headers)
            assert r.status_code == 200
            reports = r.json().get("voiceReports") or []
            assert len(reports) == 1
            report = reports[0]
            assert report["chapterId"] == "ch1"
            assert report["summary"].startswith("整体稳定")
            assert report["model"] == "test-model"
            assert report["stale"] is False
            assert report["fingerprint"]

    _run(_scenario())


def test_voice_check_whole_project_without_chapter():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "voice_all")
            pid = await _create_demo_project(client, headers)

            async def fake_voice_check(config, project, chapterId=None):
                assert chapterId is None
                return VoiceReport(
                    summary="全篇基调一致。",
                    issues=[],
                    model="test-model",
                )

            with patch(PATCH_TARGET, new=fake_voice_check):
                r = await client.post(
                    f"/api/v1/projects/{pid}/voice-check",
                    json={},
                    headers=headers,
                )
            assert r.status_code == 200, r.text
            assert r.json()["summary"] == "全篇基调一致。"
            assert r.json()["issues"] == []

            r = await client.get(f"/api/v1/projects/{pid}", headers=headers)
            reports = r.json().get("voiceReports") or []
            assert reports and reports[0]["chapterId"] is None

    _run(_scenario())


def test_voice_check_requires_llm_credentials():
    """With an empty API key the endpoint must 400 before calling the LLM."""
    from app.config import get_settings

    app = db_gate.make_app()
    empty_key_settings = db_gate.test_settings().model_copy(
        update={"deepseek_api_key": ""}
    )
    app.dependency_overrides[get_settings] = lambda: empty_key_settings

    async def _scenario():
        async with db_gate.make_client(app) as client:
            headers = await db_gate.register_headers(client, "voice_nokey")
            pid = await _create_demo_project(client, headers)
            r = await client.post(
                f"/api/v1/projects/{pid}/voice-check", json={}, headers=headers
            )
            assert r.status_code == 400

    _run(_scenario())
