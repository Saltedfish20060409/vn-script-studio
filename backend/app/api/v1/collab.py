"""Collaboration API — members, chapter locks, live events (SSE)."""

from __future__ import annotations

import asyncio
import json
from typing import AsyncIterator, Optional

from fastapi import APIRouter, Depends
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


class InviteIn(BaseModel):
    role: str = "editor"


class InviteAcceptIn(BaseModel):
    token: str = Field(min_length=8, max_length=128)


class CommentIn(BaseModel):
    chapter_id: str = Field(min_length=1, max_length=64)
    anchor: str = Field(default="", max_length=255)
    text: str = Field(min_length=1, max_length=5000)
    # reply thread: parent comment id (top-level when omitted)
    parent_id: Optional[str] = Field(default=None, max_length=36)


class CommentUpdateIn(BaseModel):
    text: Optional[str] = Field(default=None, min_length=1, max_length=5000)
    resolved: Optional[bool] = None


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


@router.get("/{project_id}/collab/activity")
async def collab_activity_endpoint(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Live collaboration picture: who is editing now (active locks), recent
    comments, and quick stats for the collaboration evaluation panel."""
    await get_project_readable(db, user, project_id)
    owner = await _owner_info(db, project_id)
    members = await collab.list_members(db, project_id)
    data = await collab.collab_activity(db, project_id)

    locks_by_user = data["locksByUser"]
    presence = []
    for m in [owner, *members]:
        if not m.get("userId"):
            continue
        locks_of = locks_by_user.get(m["userId"], [])
        presence.append(
            {
                "userId": m["userId"],
                "username": m["username"],
                "role": m.get("role") or "editor",
                "editingChapterIds": [l["chapterId"] for l in locks_of],
                "lastActiveAt": (
                    max(l["expiresAt"] for l in locks_of) if locks_of else None
                ),
            }
        )
    presence.sort(
        key=lambda p: (not p["editingChapterIds"], p["username"])
    )
    return {
        "presence": presence,
        "recentComments": data["comments"],
        "stats": data["stats"],
    }


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


@router.post("/{project_id}/invites")
async def create_invite(
    project_id: str,
    body: InviteIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await get_owned_project(db, user, project_id)
    actor_role = "owner" if row.owner_id == user.id else "editor"
    out = await collab.create_invite(
        db, project_id, role=body.role, created_by=user.id, actor_role=actor_role
    )
    collab.member_event(project_id, "invite_created", {"role": body.role})
    return out


@router.get("/{project_id}/invites")
async def list_invites(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_project_readable(db, user, project_id)
    return {"invites": await collab.list_invites(db, project_id)}


@router.delete("/{project_id}/invites/{token}")
async def revoke_invite(
    project_id: str,
    token: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await get_owned_project(db, user, project_id)
    actor_role = "owner" if row.owner_id == user.id else "editor"
    await collab.revoke_invite(db, project_id, token, actor_role=actor_role)
    return {"ok": True}


@router.post("/invites/accept")
async def accept_invite(
    body: InviteAcceptIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Join a project via invite token. The frontend routes invite links here."""
    return await collab.accept_invite(db, body.token.strip(), user)


# ---------------------------------------------------------------------------
# Comments (collaboration stage C)
# ---------------------------------------------------------------------------


@router.get("/{project_id}/comments")
async def get_comments(
    project_id: str,
    chapter_id: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_project_readable(db, user, project_id)
    return {
        "comments": await collab.list_comments(
            db, project_id, chapter_id=chapter_id or None
        )
    }


@router.post("/{project_id}/comments")
async def add_comment(
    project_id: str,
    body: CommentIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_project_readable(db, user, project_id)
    out = await collab.create_comment(
        db,
        project_id,
        body.chapter_id,
        user.id,
        text=body.text,
        anchor=body.anchor,
        parent_id=body.parent_id,
    )
    collab.comment_event(project_id, "added", out)
    return out


@router.patch("/{project_id}/comments/{comment_id}")
async def patch_comment(
    project_id: str,
    comment_id: str,
    body: CommentUpdateIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_project_readable(db, user, project_id)
    out = await collab.update_comment(
        db,
        project_id,
        comment_id,
        actor_id=user.id,
        text=body.text,
        resolved=body.resolved,
    )
    collab.comment_event(project_id, "updated", out)
    return out


@router.delete("/{project_id}/comments/{comment_id}")
async def remove_comment(
    project_id: str,
    comment_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_project_readable(db, user, project_id)
    await collab.delete_comment(db, project_id, comment_id, actor_id=user.id)
    collab.comment_event(
        project_id, "deleted", {"id": comment_id, "userId": user.id}
    )
    return {"ok": True}
