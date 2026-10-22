"""删号（DELETE /api/v1/auth/me）：确认门槛、级联范围、与他人数据的关系。

背景：这是「注销账号」在服务端的唯一实现。它不可恢复，所以这里钉住的不是
"接口能通"，而是四条容易出事的边界：

1. 三重确认（用户名 + 密码 + 最后一位管理员）任何一条不满足都不许删；
2. 删干净：账号、名下项目、分享链接、用量记录、加入别人项目的成员行；
3. 不越界：**别人**的项目还在，别人挂在本人批注下的回复也不陪葬；
4. 删完之后：旧 token 立刻失效、同用户名 / 邮箱可以重新注册。
"""

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
    """兼容旧测试库：users.is_admin 由 0022 引入，create_all 不会补老表的列。"""
    async with db_gate.SessionLocal() as session:
        await session.execute(
            text(
                "ALTER TABLE users "
                "ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT false"
            )
        )
        await session.commit()


async def _delete(client, headers: dict, password: str, confirm: str):
    # httpx 的 client.delete() 不接受 json=，删号需要请求体，所以走 request()。
    return await client.request(
        "DELETE",
        "/api/v1/auth/me",
        json={"password": password, "confirm": confirm},
        headers=headers,
    )


async def _make_project(client, headers: dict, title: str = "要被删掉的剧本") -> str:
    r = await client.post("/api/v1/projects", json={"title": title}, headers=headers)
    assert r.status_code == 200, r.text
    return r.json()["id"]


def test_delete_account_requires_username_and_password():
    """用户名敲错 → 400；密码错 → 403；两次失败后账号必须完好无损。"""

    async def _scenario():
        async with db_gate.make_client(APP) as client:
            await _ensure_is_admin_column()
            headers = await db_gate.register_headers(client, "del_confirm")
            pid = await _make_project(client, headers)

            r = await _delete(client, headers, "secret123", "del_confirm_typo")
            assert r.status_code == 400, r.text

            r = await _delete(client, headers, "wrong-password", "del_confirm")
            assert r.status_code == 403, r.text

            # 账号与项目都还在，会话也还有效
            r = await client.get("/api/v1/auth/me", headers=headers)
            assert r.status_code == 200, r.text
            assert r.json()["username"] == "del_confirm"
            r = await client.get(f"/api/v1/projects/{pid}", headers=headers)
            assert r.status_code == 200, r.text

    _run(_scenario())


def test_delete_account_purges_own_data_and_releases_username():
    """删号后：账号 / 项目 / 分享 / token 全部作废，用户名与邮箱可以重新注册。"""

    async def _scenario():
        async with db_gate.make_client(APP) as client:
            await _ensure_is_admin_column()
            headers = await db_gate.register_headers(client, "del_full")
            pid = await _make_project(client, headers)
            r = await client.post(f"/api/v1/projects/{pid}/shares", headers=headers)
            assert r.status_code == 200, r.text
            token = r.json()["token"]

            r = await client.get(f"/api/v1/shares/{token}")
            assert r.status_code == 200, r.text

            r = await _delete(client, headers, "secret123", "del_full")
            assert r.status_code == 200, r.text
            assert r.json()["ok"] is True

            # 1) 账号行没了，旧 access token 立即失效（sub 查不到人）
            async with db_gate.SessionLocal() as session:
                from app.models import User

                left = (
                    await session.execute(
                        select(User).where(User.username == "del_full")
                    )
                ).scalar_one_or_none()
                assert left is None
            r = await client.get("/api/v1/auth/me", headers=headers)
            assert r.status_code == 401, r.text

            # 2) 项目与公开分享页都没了
            r = await client.get(f"/api/v1/projects/{pid}", headers=headers)
            assert r.status_code == 401, r.text
            r = await client.get(f"/api/v1/shares/{token}")
            assert r.status_code == 404, r.text

            # 3) 登录失败
            r = await client.post(
                "/api/v1/auth/login",
                json={"username": "del_full", "password": "secret123"},
            )
            assert r.status_code == 401, r.text

            # 4) 用户名与邮箱已释放，能重新注册一个全新账号
            r = await db_gate.register_headers(client, "del_full")
            assert r
            r = await client.get("/api/v1/auth/me", headers=r)
            assert r.status_code == 200, r.text
            # 新账号是空的：旧作品不会跟着回来
            r = await client.get("/api/v1/projects", headers=r)
            assert r.status_code == 200, r.text
            assert [p["id"] for p in r.json()] != [pid]

    _run(_scenario())


def test_delete_account_keeps_other_users_project_and_their_replies():
    """本人的批注随号删除，但别人项目还在，别人挂在他批注下的回复保留为顶层。"""

    async def _scenario():
        async with db_gate.make_client(APP) as client:
            await _ensure_is_admin_column()
            owner = await db_gate.register_headers(client, "keep_owner")
            guest = await db_gate.register_headers(client, "keep_guest")

            pid = await _make_project(client, owner, "主人的剧本")
            r = await client.post(
                f"/api/v1/projects/{pid}/members",
                json={"username": "keep_guest", "role": "editor"},
                headers=owner,
            )
            assert r.status_code == 200, r.text

            # 客人在主人的项目里留一条批注，主人回一条
            r = await client.post(
                f"/api/v1/projects/{pid}/comments",
                json={"chapter_id": "ch1", "text": "客人说的话"},
                headers=guest,
            )
            assert r.status_code == 200, r.text
            guest_comment_id = r.json()["id"]
            r = await client.post(
                f"/api/v1/projects/{pid}/comments",
                json={"chapter_id": "ch1", "text": "主人的回复", "parent_id": guest_comment_id},
                headers=owner,
            )
            assert r.status_code == 200, r.text

            # 客人删号
            r = await _delete(client, guest, "secret123", "keep_guest")
            assert r.status_code == 200, r.text

            # 主人的项目还在，客人的批注没了，主人的回复被提升为顶层
            r = await client.get(f"/api/v1/projects/{pid}", headers=owner)
            assert r.status_code == 200, r.text
            r = await client.get(
                f"/api/v1/projects/{pid}/comments", headers=owner
            )
            assert r.status_code == 200, r.text
            texts = [c["text"] for c in r.json()["comments"]]
            assert "客人说的话" not in texts
            assert "主人的回复" in texts
            survivor = next(c for c in r.json()["comments"] if c["text"] == "主人的回复")
            # 响应里是 camelCase：parentId 为空串 = 已提升为顶层批注
            assert survivor["parentId"] in (None, "")

            # 成员表里不再有已删账号
            r = await client.get(f"/api/v1/projects/{pid}/members", headers=owner)
            assert r.status_code == 200, r.text
            names = [m.get("username") for m in r.json()["members"]]
            assert "keep_guest" not in names

    _run(_scenario())


def test_last_admin_cannot_delete_self():
    """最后一位管理员不能自删：否则站点失去唯一的管理入口。"""

    async def _scenario():
        async with db_gate.make_client(APP) as client:
            await _ensure_is_admin_column()
            headers = await db_gate.register_headers(client, "admin_solo")
            async with db_gate.SessionLocal() as session:
                from app.models import User

                user = (
                    await session.execute(
                        select(User).where(User.username == "admin_solo")
                    )
                ).scalar_one()
                user.is_admin = True
                await session.commit()

            r = await _delete(client, headers, "secret123", "admin_solo")
            assert r.status_code == 400, r.text
            assert "管理员" in r.json()["detail"]

            # 再给一位管理员，就能删了
            other = await db_gate.register_headers(client, "admin_second")
            assert other
            async with db_gate.SessionLocal() as session:
                from app.models import User

                user = (
                    await session.execute(
                        select(User).where(User.username == "admin_second")
                    )
                ).scalar_one()
                user.is_admin = True
                await session.commit()

            r = await _delete(client, headers, "secret123", "admin_solo")
            assert r.status_code == 200, r.text

    _run(_scenario())


def test_delete_account_clears_soft_reference_rows():
    """无外键的软引用（成员 / 锁 / 用量 / 作业）不能留成幽灵行。"""

    async def _scenario():
        async with db_gate.make_client(APP) as client:
            await _ensure_is_admin_column()
            owner = await db_gate.register_headers(client, "soft_owner")
            helper = await db_gate.register_headers(client, "soft_helper")
            pid = await _make_project(client, owner)
            r = await client.post(
                f"/api/v1/projects/{pid}/members",
                json={"username": "soft_helper", "role": "editor"},
                headers=owner,
            )
            assert r.status_code == 200, r.text
            r = await client.post(f"/api/v1/projects/{pid}/locks/ch1", headers=helper)
            assert r.status_code == 200, r.text

            async with db_gate.SessionLocal() as session:
                from app.models import ChapterLock, LlmUsage, ProjectMember, User

                helper_row = (
                    await session.execute(
                        select(User).where(User.username == "soft_helper")
                    )
                ).scalar_one()
                helper_id = helper_row.id
                session.add(
                    LlmUsage(
                        user_id=helper_id,
                        kind="agent",
                        model="m",
                        total_tokens=10,
                    )
                )
                await session.commit()

            r = await _delete(client, helper, "secret123", "soft_helper")
            assert r.status_code == 200, r.text

            async with db_gate.SessionLocal() as session:
                from app.models import ChapterLock, LlmUsage, ProjectMember

                assert (
                    await session.execute(
                        select(ProjectMember).where(ProjectMember.user_id == helper_id)
                    )
                ).scalar_one_or_none() is None
                assert (
                    await session.execute(
                        select(ChapterLock).where(ChapterLock.user_id == helper_id)
                    )
                ).scalar_one_or_none() is None
                assert (
                    await session.execute(
                        select(LlmUsage).where(LlmUsage.user_id == helper_id)
                    )
                ).scalars().all() == []

    _run(_scenario())
