"""API tests: LLM settings catalogue + test-connection endpoint."""

from __future__ import annotations

import asyncio
from unittest.mock import AsyncMock, patch

import db_gate
import httpx
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


def _ok_response(model: str = "deepseek-chat") -> httpx.Response:
    return httpx.Response(
        200,
        json={
            "choices": [{"message": {"content": "pong"}}],
            "model": model,
        },
        request=httpx.Request("POST", "https://api.deepseek.com/v1/chat/completions"),
    )


def test_model_catalogue_shape():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "llm_models")
            r = await client.get("/api/v1/settings/models", headers=headers)
            assert r.status_code == 200, r.text
            body = r.json()
            assert len(body["presets"]) >= 5
            assert body["active"] is not None  # server test key always present
            assert body["active"]["model"]
            assert body["active"]["source"] in ("user", "server", "client")

    _run(_scenario())


def test_test_llm_success():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "llm_test_ok")
            with patch(
                "app.core.llm_http.chat_completions",
                new_callable=AsyncMock,
                return_value=_ok_response("deepseek-chat"),
            ) as mocked:
                r = await client.post(
                    "/api/v1/settings/test-llm",
                    json={
                        "api_key": "sk-test",
                        "base_url": "https://api.deepseek.com",
                        "model": "deepseek-chat",
                    },
                    headers=headers,
                )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["ok"] is True
            assert body["model"] == "deepseek-chat"
            assert body["latency_ms"] >= 0
            mocked.assert_awaited_once()

    _run(_scenario())


def test_test_llm_upstream_error_reports_failure():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "llm_test_fail")
            with patch(
                "app.core.llm_http.chat_completions",
                new_callable=AsyncMock,
                side_effect=RuntimeError("DeepSeek API 401: bad key"),
            ):
                r = await client.post(
                    "/api/v1/settings/test-llm",
                    json={
                        "api_key": "sk-bad",
                        "base_url": "https://api.deepseek.com",
                        "model": "deepseek-chat",
                    },
                    headers=headers,
                )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["ok"] is False
            assert "401" in body["error"]

    _run(_scenario())


def test_test_llm_uses_request_headers():
    """Browser X-LLM-* headers are used to reach the upstream model."""

    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "llm_hdr")
            headers = {
                **headers,
                "X-LLM-Api-Key": "sk-from-browser",
                "X-LLM-Base-Url": "https://api.moonshot.cn",
                "X-LLM-Model": "moonshot-v1-32k",
            }
            with patch(
                "app.core.llm_http.chat_completions",
                new_callable=AsyncMock,
                return_value=_ok_response("moonshot-v1-32k"),
            ) as mocked:
                r = await client.post(
                    "/api/v1/settings/test-llm", json={}, headers=headers
                )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["ok"] is True
            cfg = mocked.await_args.args[0]
            assert cfg.apiKey == "sk-from-browser"
            assert cfg.baseUrl == "https://api.moonshot.cn"
            assert cfg.model == "moonshot-v1-32k"

    _run(_scenario())


def test_test_llm_missing_key_rejected():
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "llm_test_nokey")
            with patch(
                "app.api.v1.settings.resolve_llm_credentials",
                new_callable=AsyncMock,
                return_value={"api_key": "", "base_url": "", "model": ""},
            ):
                r = await client.post(
                    "/api/v1/settings/test-llm", json={}, headers=headers
                )
            assert r.status_code == 400
            assert "API Key" in r.json()["detail"]

    _run(_scenario())


def test_test_llm_rejects_unsafe_base_url():
    """SSRF 回归：请求体自带非 https/内网地址必须 400，且绝不发起上游请求。"""

    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "llm_ssrf_meta")
            with patch(
                "app.core.llm_http.chat_completions", new_callable=AsyncMock
            ) as mocked:
                for bad in (
                    "http://169.254.169.254/latest/meta-data",
                    "http://127.0.0.1:8000/admin",
                ):
                    r = await client.post(
                        "/api/v1/settings/test-llm",
                        json={"api_key": "sk-x", "base_url": bad},
                        headers=headers,
                    )
                    assert r.status_code == 400, f"{bad}: {r.text}"
                    assert "base_url" in r.json()["detail"]
            mocked.assert_not_awaited()

    _run(_scenario())


def test_test_llm_custom_url_requires_own_key_never_sends_server_key():
    """关键回归：自定义 base_url 不带 key 必须 400——否则服务器 key 会被
    发往用户指定的任意地址（credential-exfiltrating SSRF）。"""

    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "llm_ssrf_bind")
            with patch(
                "app.api.v1.settings.resolve_llm_credentials",
                new_callable=AsyncMock,
                return_value={
                    "api_key": "sk-server-secret-do-not-leak",
                    "base_url": "",
                    "model": "",
                },
            ), patch(
                "app.core.llm_http.chat_completions", new_callable=AsyncMock
            ) as mocked:
                r = await client.post(
                    "/api/v1/settings/test-llm",
                    # api.moonshot.cn 是可解析的公网 https 主机（过 SSRF 守卫），
                    # 因此会走到「自定义地址必须自带 key」的层绑定校验。
                    json={"base_url": "https://api.moonshot.cn"},
                    headers=headers,
                )
            assert r.status_code == 400, r.text
            assert "API Key" in r.json()["detail"]
            mocked.assert_not_awaited()

    _run(_scenario())
