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


def test_account_saved_base_url_is_stored_and_becomes_effective():
    """账号里存的 Base URL 必须**存得下、且真的生效**。

    守的是线上真实反馈（用户截图）：账号存储模式下填了 Base URL、界面提示"已保存"，
    但「当前生效」显示的是另一个域名。真因是前端把键写成 `base_url`
    （后端 schema 叫 `api_base_url`），Pydantic 静默忽略 → 账号里那列一直是
    建表默认的 `https://api.deepseek.com`，于是**用户自己的 Key 被发到他没有指定的域名**。
    键名守卫在 `test_settings_put_contract.py`；这一条走完整链路证明"存进去 = 会生效"。
    """
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "llm_baseurl")
            r = await client.put(
                "/api/v1/settings",
                headers=headers,
                json={
                    "api_key": "sk-test-relay-key",
                    "api_base_url": "https://relay.example.test/v1",
                    "api_model": "space-bunny",
                },
            )
            assert r.status_code == 200, r.text
            assert r.json()["api_base_url"] == "https://relay.example.test/v1"
            # 读回也要是它（而不是建表默认值）
            r = await client.get("/api/v1/settings", headers=headers)
            assert r.json()["api_base_url"] == "https://relay.example.test/v1"
            assert r.json()["api_model"] == "space-bunny"

            # 生效值：把 SSRF 守卫里的 DNS 解析换掉，避免这条测试看网络脸色
            # （守卫本身另有测试；这里要证明的是"存的地址会被用"）。
            with patch(
                "app.core.llm_client_override._is_safe_base_url", return_value=True
            ):
                r = await client.get("/api/v1/settings/models", headers=headers)
            assert r.status_code == 200, r.text
            active = r.json()["active"]
            assert active is not None
            assert active["base_url"] == "https://relay.example.test/v1", (
                "账号里存的 Base URL 没有生效——用户填的地址被忽略了"
            )
            assert active["model"] == "space-bunny"
            assert active["source"] == "user"

    _run(_scenario())


def test_wrong_key_name_does_not_silently_change_the_saved_url():
    """用错的键名（`base_url`）不能改动已存的地址——它会被忽略，而不是被当别名。

    这条把"静默忽略"这个事实钉在接口层：将来若有人给 schema 加 `base_url` 别名，
    这里会红，那时应当连同前端一起改，而不是让两份真源长期并存。
    """
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "llm_baseurl_alias")
            await client.put(
                "/api/v1/settings",
                headers=headers,
                json={"api_key": "sk-test-relay-key", "api_base_url": "https://kept.example.test/v1"},
            )
            r = await client.put(
                "/api/v1/settings",
                headers=headers,
                json={"base_url": "https://ignored.example.test/v1"},
            )
            assert r.status_code == 200, r.text
            assert r.json()["api_base_url"] == "https://kept.example.test/v1"

    _run(_scenario())


def test_obviously_unusable_base_url_is_rejected_at_save_time():
    """明显用不了的接口地址在**保存时**就报 400，别存下来再在请求时被静默换掉。

    为什么这条重要：请求时的安全守卫过不了就会**回落**到服务端地址，而界面不会说
    （用户看到的正是"我填的地址没生效、当前生效是别的域名"）。保存时拦住 = 当场给话。
    """
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "llm_badurl")
            for bad in (
                "http://localhost:11434",
                "api.deepseek.com",
                "https://192.168.1.10/v1",
            ):
                r = await client.put(
                    "/api/v1/settings", headers=headers, json={"api_base_url": bad}
                )
                assert r.status_code == 400, f"{bad} 本该被拒：{r.status_code} {r.text}"
                assert "https" in r.json()["detail"]

            # 合法地址照常能存（保存时不查 DNS，所以不存在的域名也能先存下来）
            r = await client.put(
                "/api/v1/settings",
                headers=headers,
                json={"api_base_url": "https://ok.example.test/v1"},
            )
            assert r.status_code == 200, r.text
            assert r.json()["api_base_url"] == "https://ok.example.test/v1"

            # 空串 = 清空，仍然合法
            r = await client.put(
                "/api/v1/settings", headers=headers, json={"api_base_url": ""}
            )
            assert r.status_code == 200, r.text
            assert r.json()["api_base_url"] == ""

    _run(_scenario())


def test_models_endpoint_reports_a_rejected_base_url():
    """/settings/models 必须如实报告"你保存的地址没被采用"。

    为什么必须有这条：请求时的守卫会把不可用的地址**静默换成服务端地址**，
    用户看到的就是"我填的地址没生效"（真实反馈的两行数字打架）。
    让前端比较域名去猜会误报；服务端在这里是**确切知道**丢了哪个地址的，
    所以由它给出 `url_rejected`，界面照说即可。

    造状态的方式：先走 HTTP 存一个合法地址与 Key，再直接改库把它换成守卫会拒的地址
    ——HTTP 层现在会拦下这类地址（那是另一条测试），但历史数据与其他客户端
    仍可能留下这种状态，这里验的是**读取与上报**这一半。
    """
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "llm_rejected_url")
            r = await client.put(
                "/api/v1/settings",
                headers=headers,
                json={"api_key": "sk-test-key", "api_base_url": "https://ok.example.test/v1"},
            )
            assert r.status_code == 200, r.text
            # 正常情况下不该报"被拒"。这里把守卫换成桩：`_is_safe_base_url` 是**含 DNS** 的，
            # 而本用例要验的是"上报有没有接上"，不是守卫本身。
            # （第一版没换桩、用了 `ok.example.test`——`.test` 是保留域名、解析不到，
            #   守卫本来就该拒它，于是断言在**正确**的行为上红了。）
            with patch(
                "app.core.llm_client_override._is_safe_base_url", return_value=True
            ):
                r = await client.get("/api/v1/settings/models", headers=headers)
            assert r.json()["active"]["url_rejected"] == ""

            from sqlalchemy import select

            from app.models import User, UserSettings

            bad = "https://192.168.1.10/v1"
            async with db_gate.SessionLocal() as session:
                user = (
                    await session.execute(
                        select(User).where(User.username == "llm_rejected_url")
                    )
                ).scalar_one()
                row = (
                    await session.execute(
                        select(UserSettings).where(UserSettings.user_id == user.id)
                    )
                ).scalar_one()
                row.api_base_url = bad
                await session.commit()

            r = await client.get("/api/v1/settings/models", headers=headers)
            active = r.json()["active"]
            assert active["url_rejected"] == bad
            assert active["source"] == "user"
            # 实际生效的地址确实被换掉了（与 url_rejected 同时出现才说得通）
            assert active["base_url"] != bad

    _run(_scenario())


def test_declared_model_window_round_trips_and_is_clamped():
    """用户声明的模型窗口：存得下、读得回、填错不会打穿预算。

    为什么要这条：上下文预算按模型窗口夹一次；窗口只有用户自己知道
    （预设表收不全，撑爆窗口会被上游直接拒答）。

    说明：老测试库里 `user_settings` 缺 `api_context_window_k` 的情况由
    `db_gate.create_all` 统一按元数据补列（见那里的注释），所以这里不再单独补。
    """
    async def _scenario():
        async with db_gate.make_client(APP) as client:
            headers = await db_gate.register_headers(client, "llm_window")

            # 默认：没声明（0 = 自动）
            r = await client.get("/api/v1/settings", headers=headers)
            assert r.status_code == 200, r.text
            assert r.json().get("api_context_window_k", 0) == 0

            # 声明 32k：读得回
            r = await client.put(
                "/api/v1/settings", headers=headers, json={"api_context_window_k": 32}
            )
            assert r.status_code == 200, r.text
            assert r.json()["api_context_window_k"] == 32
            r = await client.get("/api/v1/settings", headers=headers)
            assert r.json()["api_context_window_k"] == 32

            # 超大值夹到上限（配置项写错不该把预算打成天文数字）
            r = await client.put(
                "/api/v1/settings", headers=headers, json={"api_context_window_k": 999_999}
            )
            assert r.json()["api_context_window_k"] == 10_000

            # 负值 = 明确"不用夹"，统一记成 -1
            r = await client.put(
                "/api/v1/settings", headers=headers, json={"api_context_window_k": -7}
            )
            assert r.json()["api_context_window_k"] == -1

            # 回到自动
            r = await client.put(
                "/api/v1/settings", headers=headers, json={"api_context_window_k": 0}
            )
            assert r.json()["api_context_window_k"] == 0

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
