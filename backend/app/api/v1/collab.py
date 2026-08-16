"""Collaboration API — members, chapter locks, live events (SSE)."""

from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Project, User
from app.security import get_current_user
from app.services import collab
from app.services.projects import (
    get_owned_project,
    get_project_readable,
)

router = APIRouter(prefix="/projects", tags=["collab"])


class MemberIn(BaseModel):
    username: str = Field(min_length=1, max_length=64)
    role: str = "editor"


class MemberRoleIn(BaseModel):
    role: str = Field(pattern="^(editor|viewer)$")


async def _owner_info(db: AsyncSession, project_id: str) -> dict:
    res = await db.execute(
        select(Project.owner_id, User.username)
        .join(User, User.id == Project.owner_id)
        .where(Project.id == project_id)
    )
    row = res.first()
    if not row:
        return {}
    return {"userId": row[0], "username": row[1], "role": "owner"}


@router.get("/{project_id}/members")
async def list_members(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_project_readable(db, user, project_id)
    owner = await _owner_info(db, project_id)
    members = await collab.list_members(db, project_id)
    return {"owner": owner, "members": members}


@router.post("/{project_id}/members")
async def add_member(
    project_id: str,
    body: MemberIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await get_owned_project(db, user, project_id)
    actor_role = "owner" if row.owner_id == user.id else "editor"
    out = await collab.add_member(
        db, project_id, username=body.username, role=body.role, actor_role=actor_role
    )
    collab.member_event(project_id, "added", out)
    return out


@router.patch("/{project_id}/members/{member_user_id}")
async def change_member_role(
    project_id: str,
    member_user_id: str,
    body: MemberRoleIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await get_owned_project(db, user, project_id)
    actor_role = "owner" if row.owner_id == user.id else "editor"
    await collab.update_member_role(
        db, project_id, member_user_id, role=body.role, actor_role=actor_role
    )
    collab.member_event(project_id, "role_changed", {"userId": member_user_id, "role": body.role})
    return {"ok": True}


@router.delete("/{project_id}/members/{member_user_id}")
async def delete_member(
    project_id: str,
    member_user_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await get_owned_project(db, user, project_id)
    actor_role = "owner" if row.owner_id == user.id else "editor"
    await collab.remove_member(db, project_id, member_user_id, actor_role=actor_role)
    collab.member_event(project_id, "removed", {"userId": member_user_id})
    return {"ok": True}


@router.get("/{project_id}/locks")
async def get_locks(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_project_readable(db, user, project_id)
    return {"locks": await collab.list_locks(db, project_id)}


@router.post("/{project_id}/locks/{chapter_id}")
async def lock_chapter(
    project_id: str,
    chapter_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_owned_project(db, user, project_id)
    out = await collab.acquire_lock(db, project_id, chapter_id, user.id)
    collab.lock_event(project_id, "acquired", out)
    return out


@router.delete("/{project_id}/locks/{chapter_id}")
async def unlock_chapter(
    project_id: str,
    chapter_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_owned_project(db, user, project_id)
    await collab.release_lock(db, project_id, chapter_id, user.id)
    collab.lock_event(project_id, "released", {"chapterId": chapter_id, "userId": user.id})
    return {"ok": True}


@router.get("/{project_id}/events")
async def project_events(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """SSE stream of project collaboration events (members / locks)."""
    await get_project_readable(db, user, project_id)
    queue = collab.subscribe(project_id)

    async def event_stream() -> AsyncIterator[str]:
        async def _sse(data: dict) -> str:
            return f"data: {json.dumps(data, ensure_ascii=False)}\n\n"

        try:
            while True:
                try:
                    evt = await asyncio.wait_for(queue.get(), timeout=20)
                except asyncio.TimeoutError:
                    yield ": keepalive\n\n"
                    continue
                yield await _sse(evt)
        finally:
            collab.unsubscribe(project_id, queue)

    from fastapi.responses import StreamingResponse

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
