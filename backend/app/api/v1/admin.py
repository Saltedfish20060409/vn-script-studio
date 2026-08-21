"""Operator admin API — ban / unban accounts (ADMIN_USERNAMES gated)."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import User
from app.security import get_admin_user

router = APIRouter(prefix="/admin", tags=["admin"])


class AdminUserOut(BaseModel):
    id: str
    username: str
    email: Optional[str] = None
    disabled_at: Optional[datetime] = None
    created_at: Optional[datetime] = None


class BanOut(BaseModel):
    ok: bool = True
    username: str
    disabled: bool
    message: str = ""


def _out(user: User) -> AdminUserOut:
    return AdminUserOut(
        id=user.id,
        username=user.username,
        email=user.email,
        disabled_at=user.disabled_at,
        created_at=user.created_at,
    )


@router.get("/users", response_model=List[AdminUserOut])
async def list_users(
    disabled_only: bool = False,
    limit: int = Query(50, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_admin_user),
):
    q = select(User).order_by(User.created_at.desc()).limit(limit)
    if disabled_only:
        q = q.where(User.disabled_at.is_not(None))
    rows = (await db.execute(q)).scalars().all()
    return [_out(u) for u in rows]


@router.post("/users/{username}/ban", response_model=BanOut)
async def ban_user(
    username: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    name = username.strip()
    if not name:
        raise HTTPException(status_code=400, detail="用户名不能为空")
    if name == admin.username:
        raise HTTPException(status_code=400, detail="不能封禁自己的账号")
    result = await db.execute(select(User).where(User.username == name))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    user.disabled_at = datetime.now(timezone.utc)
    await db.commit()
    return BanOut(ok=True, username=name, disabled=True, message="已停用")


@router.post("/users/{username}/unban", response_model=BanOut)
async def unban_user(
    username: str,
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_admin_user),
):
    name = username.strip()
    if not name:
        raise HTTPException(status_code=400, detail="用户名不能为空")
    result = await db.execute(select(User).where(User.username == name))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    user.disabled_at = None
    await db.commit()
    return BanOut(ok=True, username=name, disabled=False, message="已解禁")
