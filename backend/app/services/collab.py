"""Collaboration services — project members, chapter locks, inline comments.

Event delivery goes through ``app.services.event_bus``: in-process queues by
default, bridged across uvicorn workers via Redis pub/sub when ``REDIS_URL``
is configured (see event_bus.py).
"""

from __future__ import annotations

import secrets
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChapterLock, ProjectComment, ProjectInvite, ProjectMember, User

LOCK_TTL = timedelta(minutes=10)
LOCK_HEARTBEAT = timedelta(minutes=5)
INVITE_TTL = timedelta(days=7)


def _now() -> datetime:
    return datetime.now(timezone.utc)


# --------------------------------------------------------------------------
# Members
# --------------------------------------------------------------------------


async def list_members(db: AsyncSession, project_id: str) -> List[Dict[str, Any]]:
    res = await db.execute(
        select(ProjectMember, User.username).join(User, User.id == ProjectMember.user_id)
        .where(ProjectMember.project_id == project_id)
        .order_by(ProjectMember.joined_at)
    )
    return [
        {"userId": m.user_id, "username": username, "role": m.role, "joinedAt": m.joined_at.isoformat()}
        for m, username in res.all()
    ]


async def add_member(
    db: AsyncSession,
    project_id: str,
    *,
    username: str,
    role: str,
    actor_role: str,
) -> Dict[str, Any]:
    if actor_role != "owner":
        raise HTTPException(status_code=403, detail="仅项目所有者可管理成员")
    if role not in ("editor", "viewer"):
        raise HTTPException(status_code=400, detail="角色必须为 editor 或 viewer")
    username = (username or "").strip()
    if not username:
        raise HTTPException(status_code=400, detail="用户名不能为空")
    res = await db.execute(select(User).where(User.username == username))
    user = res.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail=f"用户 {username} 不存在")
    existing = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user.id,
        )
    )
    if existing.scalar_one_or_none() is not None:
        raise HTTPException(status_code=400, detail="该用户已是项目成员")
    row = ProjectMember(
        id=str(uuid4()),
        project_id=project_id,
        user_id=user.id,
        role=role,
        joined_at=_now(),
    )
    db.add(row)
    try:
        await db.commit()
    except IntegrityError:
        # Concurrent add — the (project_id, user_id) unique constraint caught
        # a duplicate that slipped past the read above.
        await db.rollback()
        raise HTTPException(status_code=400, detail="该用户已是项目成员") from None
    return {"userId": user.id, "username": user.username, "role": role}


async def update_member_role(
    db: AsyncSession,
    project_id: str,
    user_id: str,
    *,
    role: str,
    actor_role: str,
) -> None:
    if actor_role != "owner":
        raise HTTPException(status_code=403, detail="仅项目所有者可管理成员")
    if role not in ("editor", "viewer"):
        raise HTTPException(status_code=400, detail="角色必须为 editor 或 viewer")
    res = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
    )
    row = res.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="成员不存在")
    row.role = role
    await db.commit()


async def remove_member(
    db: AsyncSession,
    project_id: str,
    user_id: str,
    *,
    actor_role: str,
) -> None:
    if actor_role != "owner":
        raise HTTPException(status_code=403, detail="仅项目所有者可管理成员")
    await db.execute(
        delete(ProjectMember).where(
            ProjectMember.project_id == project_id,
            ProjectMember.user_id == user_id,
        )
    )
    await db.commit()


# --------------------------------------------------------------------------
# Chapter locks
# --------------------------------------------------------------------------


async def acquire_lock(
    db: AsyncSession,
    project_id: str,
    chapter_id: str,
    user_id: str,
) -> Dict[str, Any]:
    """Claim a chapter lock (or heartbeat-extend an existing one held by the user).

    Atomic upsert: the (project_id, chapter_id) unique constraint guarantees a
    single lock row per chapter, so concurrent editors cannot double-lock.
    """
    now = _now()

    # Existing row → extend or reject. Read-then-act is fine here because the
    # unique constraint makes a concurrent INSERT impossible once a row exists.
    res = await db.execute(
        select(ChapterLock).where(
            ChapterLock.project_id == project_id,
            ChapterLock.chapter_id == chapter_id,
        )
    )
    row = res.scalar_one_or_none()
    if row is not None:
        if row.user_id != user_id:
            if row.expires_at > now:
                raise HTTPException(
                    status_code=423,
                    detail=f"该章正被其他成员编辑（锁至 {row.expires_at.isoformat()}）",
                )
            # Stale lock → reclaim
            row.user_id = user_id
        row.expires_at = now + LOCK_TTL
        row.updated_at = now
    else:
        # No row yet — insert. Under concurrency both editors may attempt this;
        # the unique constraint turns the loser into a no-op, and we then read
        # the winner's row below.
        from sqlalchemy.dialects.postgresql import insert as pg_insert

        stmt = pg_insert(ChapterLock).values(
            id=str(uuid4()),
            project_id=project_id,
            chapter_id=chapter_id,
            user_id=user_id,
            expires_at=now + LOCK_TTL,
            updated_at=now,
        )
        stmt = stmt.on_conflict_do_nothing(
            index_elements=[ChapterLock.project_id, ChapterLock.chapter_id]
        )
        await db.execute(stmt)
        await db.commit()
        res = await db.execute(
            select(ChapterLock).where(
                ChapterLock.project_id == project_id,
                ChapterLock.chapter_id == chapter_id,
            )
        )
        row = res.scalar_one()
        if row.user_id != user_id and row.expires_at > now:
            raise HTTPException(
                status_code=423,
                detail=f"该章正被其他成员编辑（锁至 {row.expires_at.isoformat()}）",
            )
        return {
            "chapterId": chapter_id,
            "userId": row.user_id,
            "expiresAt": row.expires_at.isoformat(),
        }

    await db.commit()
    return {"chapterId": chapter_id, "userId": user_id, "expiresAt": row.expires_at.isoformat()}


async def release_lock(
    db: AsyncSession,
    project_id: str,
    chapter_id: str,
    user_id: str,
) -> bool:
    res = await db.execute(
        delete(ChapterLock).where(
            ChapterLock.project_id == project_id,
            ChapterLock.chapter_id == chapter_id,
            ChapterLock.user_id == user_id,
        )
    )
    await db.commit()
    return (res.rowcount or 0) > 0


async def list_locks(db: AsyncSession, project_id: str) -> List[Dict[str, Any]]:
    """Active locks (expired ones are pruned lazily)."""
    now = _now()
    await db.execute(
        delete(ChapterLock).where(
            ChapterLock.project_id == project_id,
            ChapterLock.expires_at <= now,
        )
    )
    await db.commit()
    res = await db.execute(
        select(ChapterLock, User.username)
        .join(User, User.id == ChapterLock.user_id)
        .where(ChapterLock.project_id == project_id)
    )
    return [
        {
            "chapterId": lock.chapter_id,
            "userId": lock.user_id,
            "username": username,
            "expiresAt": lock.expires_at.isoformat(),
        }
        for lock, username in res.all()
    ]


async def assert_chapters_unlocked(
    db: AsyncSession,
    project_id: str,
    chapter_ids: List[str],
    user_id: str,
) -> None:
    """Raise 423 when any chapter is actively locked by another member.

    Lock enforcement for chapter-scoped saves: a save that touches locked
    chapters must be rejected (unless the caller explicitly forces).
    """
    now = _now()
    for cid in chapter_ids:
        res = await db.execute(
            select(ChapterLock)
            .where(
                ChapterLock.project_id == project_id,
                ChapterLock.chapter_id == cid,
                ChapterLock.expires_at > now,
            )
        )
        lock = res.scalar_one_or_none()
        if lock is None or lock.user_id == user_id:
            continue
        ures = await db.execute(select(User.username).where(User.id == lock.user_id))
        username = ures.scalar_one_or_none() or "其他成员"
        raise HTTPException(
            status_code=423,
            detail={
                "code": "chapter_locked",
                "message": f"章节正被 {username} 编辑，请等待其释放锁后再保存",
                "chapterId": cid,
                "userId": lock.user_id,
                "username": username,
                "expiresAt": lock.expires_at.isoformat(),
            },
        )


# --------------------------------------------------------------------------
# Invite links
# --------------------------------------------------------------------------


async def create_invite(
    db: AsyncSession,
    project_id: str,
    *,
    role: str,
    created_by: str,
    actor_role: str,
    ttl: timedelta = INVITE_TTL,
) -> Dict[str, Any]:
    if actor_role != "owner":
        raise HTTPException(status_code=403, detail="仅项目所有者可生成邀请链接")
    if role not in ("editor", "viewer"):
        raise HTTPException(status_code=400, detail="角色必须为 editor 或 viewer")
    row = ProjectInvite(
        id=str(uuid4()),
        project_id=project_id,
        token=secrets.token_urlsafe(32),
        role=role,
        created_by=created_by,
        expires_at=_now() + ttl,
        created_at=_now(),
    )
    db.add(row)
    await db.commit()
    return {
        "token": row.token,
        "role": row.role,
        "expiresAt": row.expires_at.isoformat(),
    }


async def list_invites(db: AsyncSession, project_id: str) -> List[Dict[str, Any]]:
    now = _now()
    await db.execute(
        delete(ProjectInvite).where(
            ProjectInvite.project_id == project_id,
            ProjectInvite.expires_at <= now,
        )
    )
    await db.commit()
    res = await db.execute(
        select(ProjectInvite)
        .where(ProjectInvite.project_id == project_id)
        .order_by(ProjectInvite.created_at.desc())
    )
    return [
        {
            "token": r.token,
            "role": r.role,
            "expiresAt": r.expires_at.isoformat(),
        }
        for r in res.scalars().all()
    ]


async def revoke_invite(
    db: AsyncSession,
    project_id: str,
    token: str,
    *,
    actor_role: str,
) -> None:
    if actor_role != "owner":
        raise HTTPException(status_code=403, detail="仅项目所有者可撤销邀请")
    res = await db.execute(
        delete(ProjectInvite).where(
            ProjectInvite.project_id == project_id,
            ProjectInvite.token == token,
        )
    )
    await db.commit()
    if (res.rowcount or 0) == 0:
        raise HTTPException(status_code=404, detail="邀请不存在")


async def accept_invite(
    db: AsyncSession,
    token: str,
    user: User,
) -> Dict[str, Any]:
    """Join a project via invite token (current authenticated user)."""
    res = await db.execute(select(ProjectInvite).where(ProjectInvite.token == token))
    invite = res.scalar_one_or_none()
    if invite is None:
        raise HTTPException(status_code=404, detail="邀请无效或已被撤销")
    if invite.expires_at <= _now():
        raise HTTPException(status_code=410, detail="邀请已过期")

    # Already a member? Idempotent — just return the project.
    existing = await db.execute(
        select(ProjectMember).where(
            ProjectMember.project_id == invite.project_id,
            ProjectMember.user_id == user.id,
        )
    )
    if existing.scalar_one_or_none() is not None:
        await db.commit()
        return {"projectId": invite.project_id, "alreadyMember": True, "role": None}

    row = ProjectMember(
        id=str(uuid4()),
        project_id=invite.project_id,
        user_id=user.id,
        role=invite.role,
        joined_at=_now(),
    )
    db.add(row)
    # One-time use: delete the invite after successful join.
    await db.delete(invite)
    try:
        await db.commit()
    except IntegrityError:
        # Concurrent accept — unique (project_id, user_id) constraint caught
        # the duplicate; the other request already joined. The invite may have
        # been consumed by them; treat as already-member.
        await db.rollback()
        return {"projectId": invite.project_id, "alreadyMember": True, "role": None}
    return {"projectId": invite.project_id, "alreadyMember": False, "role": invite.role}


# --------------------------------------------------------------------------
# Comments (collaboration stage C)
# --------------------------------------------------------------------------


def _comment_dict(c: ProjectComment, username: str) -> Dict[str, Any]:
    return {
        "id": c.id,
        "projectId": c.project_id,
        "chapterId": c.chapter_id,
        "anchor": c.anchor,
        "parentId": c.parent_id or "",
        "userId": c.user_id,
        "username": username,
        "text": c.text,
        "resolved": c.resolved,
        "createdAt": c.created_at.isoformat(),
        "updatedAt": c.updated_at.isoformat(),
    }


async def list_comments(
    db: AsyncSession,
    project_id: str,
    *,
    chapter_id: Optional[str] = None,
) -> List[Dict[str, Any]]:
    stmt = (
        select(ProjectComment, User.username)
        .join(User, User.id == ProjectComment.user_id)
        .where(ProjectComment.project_id == project_id)
        .order_by(ProjectComment.created_at.asc())
    )
    if chapter_id:
        stmt = stmt.where(ProjectComment.chapter_id == chapter_id)
    res = await db.execute(stmt)
    return [_comment_dict(c, username) for c, username in res.all()]


async def create_comment(
    db: AsyncSession,
    project_id: str,
    chapter_id: str,
    user_id: str,
    *,
    text: str,
    anchor: str = "",
    parent_id: Optional[str] = None,
) -> Dict[str, Any]:
    text = (text or "").strip()
    if not text:
        raise HTTPException(status_code=400, detail="批注内容不能为空")
    if len(text) > 5000:
        raise HTTPException(status_code=400, detail="批注过长（最多 5000 字）")
    if parent_id:
        pres = await db.execute(
            select(ProjectComment).where(
                ProjectComment.id == parent_id,
                ProjectComment.project_id == project_id,
            )
        )
        parent = pres.scalar_one_or_none()
        if parent is None:
            raise HTTPException(status_code=404, detail="回复的批注不存在")
        if parent.parent_id:
            raise HTTPException(
                status_code=400, detail="回复层级最多两层，请直接回复原批注"
            )
    now = _now()
    row = ProjectComment(
        id=str(uuid4()),
        project_id=project_id,
        chapter_id=chapter_id,
        anchor=anchor or "",
        parent_id=parent_id or None,
        user_id=user_id,
        text=text,
        resolved=False,
        created_at=now,
        updated_at=now,
    )
    db.add(row)
    await db.commit()
    await db.refresh(row)
    ures = await db.execute(select(User.username).where(User.id == user_id))
    username = ures.scalar_one_or_none() or "成员"
    return _comment_dict(row, username)


async def update_comment(
    db: AsyncSession,
    project_id: str,
    comment_id: str,
    *,
    actor_id: str,
    text: Optional[str] = None,
    resolved: Optional[bool] = None,
) -> Dict[str, Any]:
    res = await db.execute(
        select(ProjectComment).where(
            ProjectComment.id == comment_id,
            ProjectComment.project_id == project_id,
        )
    )
    row = res.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="批注不存在")
    if row.user_id != actor_id and text is not None:
        raise HTTPException(status_code=403, detail="只能修改自己的批注")
    if text is not None:
        text = text.strip()
        if not text:
            raise HTTPException(status_code=400, detail="批注内容不能为空")
        row.text = text
    if resolved is not None:
        row.resolved = resolved
    row.updated_at = _now()
    await db.commit()
    await db.refresh(row)
    ures = await db.execute(select(User.username).where(User.id == row.user_id))
    username = ures.scalar_one_or_none() or "成员"
    return _comment_dict(row, username)


async def delete_comment(
    db: AsyncSession,
    project_id: str,
    comment_id: str,
    *,
    actor_id: str,
) -> None:
    res = await db.execute(
        select(ProjectComment).where(
            ProjectComment.id == comment_id,
            ProjectComment.project_id == project_id,
        )
    )
    row = res.scalar_one_or_none()
    if row is None:
        raise HTTPException(status_code=404, detail="批注不存在")
    if row.user_id != actor_id:
        raise HTTPException(status_code=403, detail="只能删除自己的批注")
    await db.delete(row)
    await db.commit()


# --------------------------------------------------------------------------
# Event bus (SSE) — cross-worker via Redis when configured (see event_bus.py)
# --------------------------------------------------------------------------

from app.services import event_bus

subscribe = event_bus.subscribe
unsubscribe = event_bus.unsubscribe


def member_event(project_id: str, kind: str, payload: Dict[str, Any]) -> None:
    event_bus.member_event(project_id, kind, payload)


def lock_event(project_id: str, kind: str, payload: Dict[str, Any]) -> None:
    event_bus.lock_event(project_id, kind, payload)


def comment_event(project_id: str, kind: str, payload: Dict[str, Any]) -> None:
    event_bus.comment_event(project_id, kind, payload)
