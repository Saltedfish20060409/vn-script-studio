"""API tests: admin gating (403 for normal users) + ban/unban login flow."""

from __future__ import annotations

import asyncio

import db_gate
import pytest
from sqlalchemy import select, text

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


async def _ensure_is_admin_column() -> None:
    """幂等补齐 users.is_admin（与 0022 迁移一致）：兼容旧结构的测试库。

    conftest 的 create_all 只会建缺失的表、不会给已有表加列，所以这里显式
    补一次，避免旧测试库上整个模块因缺列而挂。
    """
    async with db_gate.SessionLocal() as session:
        await session.execute(
            text(
                "ALTER TABLE users "
                "ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT false"
            )
        )
        await session.commit()


async def _make_admin(client, username: str) -> dict:
    """注册一个用户、直接在库中置 is_admin=True，重新登录拿 token。

    必须先有一个 admin 存在，否则 ensure_admin_access 的「首个登录者升
    admin」bootstrap 会把普通用户也变成管理员，403 断言就测不到了。
    """
    from app.models import User

    await db_gate.register_headers(client, username)
    async with db_gate.SessionLocal() as session:
        result = await session.execute(select(User).where(User.username == username))
        user = result.scalar_one()
        user.is_admin = True
        await session.commit()
    r = await client.post(
        "/api/v1/auth/login",
        json={"username": username, "password": "secret123"},
    )
    assert r.status_code == 200, r.text
    return {"Authorization": f"Bearer {r.json()['access_token']}"}


def test_non_admin_cannot_access_overview():
    """普通用户访问 /admin/overview 得 403；管理员得 200 且返回 dict。"""

    async def _scenario():
        async with db_gate.make_client(APP) as client:
            await _ensure_is_admin_column()
            admin_headers = await _make_admin(client, "admin_ov1")
            assert admin_headers

            user_headers = await db_gate.register_headers(client, "normal_ov1")
            r = await client.get("/api/v1/admin/overview", headers=user_headers)
            assert r.status_code == 403, r.text
            assert "管理员" in r.json()["detail"]

            r = await client.get("/api/v1/admin/overview", headers=admin_headers)
            assert r.status_code == 200, r.text
            body = r.json()
            assert isinstance(body, dict)
            assert body["user_count"] >= 2
            assert any(u["username"] == "admin_ov1" for u in body["users"])

    _run(_scenario())


def test_ban_blocks_login_unban_restores():
    """封禁后该用户登录失败（403），解封后恢复登录。"""

    async def _scenario():
        async with db_gate.make_client(APP) as client:
            await _ensure_is_admin_column()
            admin_headers = await _make_admin(client, "admin_ban1")
            await db_gate.register_headers(client, "victim1")

            r = await client.post(
                "/api/v1/admin/users/victim1/ban", headers=admin_headers
            )
            assert r.status_code == 200, r.text
            assert r.json()["disabled"] is True

            r = await client.post(
                "/api/v1/auth/login",
                json={"username": "victim1", "password": "secret123"},
            )
            assert r.status_code == 403, r.text
            assert "停用" in r.json()["detail"]

            r = await client.post(
                "/api/v1/admin/users/victim1/unban", headers=admin_headers
            )
            assert r.status_code == 200, r.text
            assert r.json()["disabled"] is False

            r = await client.post(
                "/api/v1/auth/login",
                json={"username": "victim1", "password": "secret123"},
            )
            assert r.status_code == 200, r.text

    _run(_scenario())


def test_email_diag_reports_unverified_account():
    """「收不到验证邮件」排查接口：只读，管理员可用，普通用户 403。

    用户反馈收不到验证邮件时，运维要能一眼看出：账号在不在、邮件发了几封、
    点开没、最近一封什么时候发的。
    """

    async def _scenario():
        from unittest.mock import AsyncMock, patch

        async with db_gate.make_client(APP) as client:
            await _ensure_is_admin_column()
            admin_headers = await _make_admin(client, "admin_diag1")

            with patch("app.api.v1.auth.send_verify_email", new_callable=AsyncMock):
                r = await client.post(
                    "/api/v1/auth/register",
                    json={
                        "username": "diaguser",
                        "email": "diaguser@example.com",
                        "password": "secret123",
                    },
                )
                assert r.status_code == 200, r.text

            user_headers = await db_gate.register_headers(client, "normal_diag1")
            r = await client.get(
                "/api/v1/admin/email-diag?q=diaguser@example.com",
                headers=user_headers,
            )
            assert r.status_code == 403, r.text

            r = await client.get(
                "/api/v1/admin/email-diag?q=diaguser@example.com",
                headers=admin_headers,
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["matched_by"] == "email"
            assert body["username"] == "diaguser"
            assert body["email_verified"] is False
            assert body["verify_sends"] == 1
            assert body["verify_clicks"] == 0
            assert body["hint"]

            # 用户名同样可查
            r = await client.get(
                "/api/v1/admin/email-diag?q=diaguser", headers=admin_headers
            )
            assert r.status_code == 200, r.text
            assert r.json()["matched_by"] == "username"

            # 查不到时给出近似账号，方便发现"填错一位"
            r = await client.get(
                "/api/v1/admin/email-diag?q=diaguser@example.org",
                headers=admin_headers,
            )
            assert r.status_code == 200, r.text
            body = r.json()
            assert body["matched_by"] == "none"
            assert any(s["username"] == "diaguser" for s in body["similar"])

    _run(_scenario())


def test_ai_usage_groups_by_capability():
    """AI 用量按能力分类：能看出"钱花在哪个能力上"，而不是只有一个总量。

    背景：llm_usage.kind 曾经被写死成 "llm"，30 天 448 次调用全是同一个标签，
    完全无法分析。这个接口是"该往哪投"的决策依据，所以要钉住聚合口径。
    """

    async def _scenario():
        from datetime import datetime, timezone

        from app.models.tables import LlmUsage

        async with db_gate.make_client(APP) as client:
            await _ensure_is_admin_column()
            admin_headers = await _make_admin(client, "admin_usage1")

            async with db_gate.SessionLocal() as session:
                session.add_all(
                    [
                        LlmUsage(
                            user_id="u1",
                            kind="chapter_revise",
                            model="m",
                            total_tokens=1000,
                            created_at=datetime.now(timezone.utc),
                        ),
                        LlmUsage(
                            user_id="u1",
                            kind="chapter_revise",
                            model="m",
                            total_tokens=500,
                            created_at=datetime.now(timezone.utc),
                        ),
                        LlmUsage(
                            user_id="u2",
                            kind="facts",
                            model="m",
                            total_tokens=300,
                            created_at=datetime.now(timezone.utc),
                        ),
                    ]
                )
                await session.commit()

            r = await client.get("/api/v1/admin/ai-usage", headers=admin_headers)
            assert r.status_code == 200, r.text
            body = r.json()
            by = {k["kind"]: k for k in body["byKind"]}

            assert by["chapter_revise"]["calls"] == 2
            assert by["chapter_revise"]["tokens"] == 1500
            assert by["chapter_revise"]["users"] == 1
            assert by["facts"]["calls"] == 1
            assert by["facts"]["users"] == 1
            assert body["totals"]["calls"] == 3
            assert body["totals"]["tokens"] == 1800
            # 分类带中文标签，便于直接看
            assert by["chapter_revise"]["label"]

            # 普通用户不能看
            user_headers = await db_gate.register_headers(client, "normal_usage1")
            r = await client.get("/api/v1/admin/ai-usage", headers=user_headers)
            assert r.status_code == 403, r.text

    _run(_scenario())
