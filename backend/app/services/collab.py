"""Collaboration services — project members, chapter locks, in-process event bus.

Event bus is process-local (same limitation as the job store): fine for a
single uvicorn worker, documented for multi-worker deployments.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set
from uuid import uuid4

from fastapi import HTTPException
from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import ChapterLock, ProjectMember, User

LOCK_TTL = timedelta(minutes=10)
LOCK_HEARTBEAT = timedelta(minutes=5)


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
    await db.commit()
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
    """Claim a chapter lock (or heartbeat-extend an existing one held by the user)."""
    now = _now()
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
        row = ChapterLock(
            id=str(uuid4()),
            project_id=project_id,
            chapter_id=chapter_id,
            user_id=user_id,
            expires_at=now + LOCK_TTL,
            updated_at=now,
        )
        db.add(row)
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


# --------------------------------------------------------------------------
# In-process event bus (SSE)
# --------------------------------------------------------------------------

_subscribers: Dict[str, Set[asyncio.Queue]] = {}


def subscribe(project_id: str) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=200)
    _subscribers.setdefault(project_id, set()).add(q)
    return q


def unsubscribe(project_id: str, q: asyncio.Queue) -> None:
    subs = _subscribers.get(project_id)
    if subs:
        subs.discard(q)
        if not subs:
            _subscribers.pop(project_id, None)


def broadcast(project_id: str, event: Dict[str, Any]) -> None:
    subs = _subscribers.get(project_id)
    if not subs:
        return
    for q in list(subs):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass  # slow subscriber — drop event


def member_event(project_id: str, kind: str, payload: Dict[str, Any]) -> None:
    broadcast(project_id, {"type": "member", "kind": kind, **payload})


def lock_event(project_id: str, kind: str, payload: Dict[str, Any]) -> None:
    broadcast(project_id, {"type": "lock", "kind": kind, **payload})
