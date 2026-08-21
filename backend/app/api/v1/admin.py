"""Operator admin API — ban / unban / grant-admin + anomaly-flagged user list."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_db
from app.models import User
from app.models.tables import LlmUsage, Project
from app.security import get_admin_user
from app.services.admin_access import count_db_admins

router = APIRouter(prefix="/admin", tags=["admin"])

# Soft thresholds — BYOK so token caps are advisory; storage/signup patterns matter more.
_PROJECTS_WARN = 40
_PROJECTS_DANGER = 70
_NEW_HOURS = 48
_NEW_BUSY_PROJECTS = 8
_CALLS_WARN = 80
_TOKENS_DANGER = 1_000_000


class AdminUserOut(BaseModel):
    id: str
    username: str
    email: Optional[str] = None
    disabled_at: Optional[datetime] = None
    is_admin: bool = False
    created_at: Optional[datetime] = None
    project_count: int = 0
    tokens_today: int = 0
    calls_today: int = 0
    flags: List[str] = Field(default_factory=list)
    flag_labels: List[str] = Field(default_factory=list)
    severity: Literal["ok", "warn", "danger"] = "ok"


class BanOut(BaseModel):
    ok: bool = True
    username: str
    disabled: bool
    message: str = ""


class AdminFlagOut(BaseModel):
    ok: bool = True
    username: str
    is_admin: bool
    message: str = ""


class AdminOverviewOut(BaseModel):
    user_count: int
    disabled_count: int
    admin_count: int = 0
    danger_count: int
    warn_count: int
    max_projects_per_user: int
    users: List[AdminUserOut]


def _flag_user(
    *,
    project_count: int,
    tokens_today: int,
    calls_today: int,
    created_at: Optional[datetime],
    disabled_at: Optional[datetime],
    max_projects: int,
) -> tuple[List[str], List[str], Literal["ok", "warn", "danger"]]:
    flags: List[str] = []
    labels: List[str] = []
    severity: Literal["ok", "warn", "danger"] = "ok"

    if disabled_at is not None:
        flags.append("disabled")
        labels.append("已封禁")

    cap = max_projects if max_projects > 0 else 80
    if project_count >= cap:
        flags.append("projects_at_cap")
        labels.append(f"项目达上限（{project_count}/{cap}）")
        severity = "danger"
    elif project_count >= _PROJECTS_DANGER:
        flags.append("projects_high")
        labels.append(f"项目偏多（{project_count}）")
        severity = "danger"
    elif project_count >= _PROJECTS_WARN:
        flags.append("projects_warn")
        labels.append(f"项目较多（{project_count}）")
        if severity == "ok":
            severity = "warn"

    now = datetime.now(timezone.utc)
    created = created_at
    if created is not None and created.tzinfo is None:
        created = created.replace(tzinfo=timezone.utc)
    if (
        created is not None
        and created >= now - timedelta(hours=_NEW_HOURS)
        and project_count >= _NEW_BUSY_PROJECTS
    ):
        flags.append("new_and_busy")
        labels.append(f"新号{_NEW_HOURS}h 内已建 {project_count} 个项目")
        severity = "danger"

    if tokens_today >= _TOKENS_DANGER:
        flags.append("tokens_high")
        labels.append(f"今日 token 很高（{tokens_today}）")
        severity = "danger"
    elif calls_today >= _CALLS_WARN:
        flags.append("calls_warn")
        labels.append(f"今日 LLM 调用较多（{calls_today}）")
        if severity == "ok":
            severity = "warn"

    return flags, labels, severity


async def _load_admin_users(
    db: AsyncSession,
    settings: Settings,
    *,
    disabled_only: bool,
    anomalies_only: bool,
    limit: int,
) -> List[AdminUserOut]:
    q = select(User).order_by(User.created_at.desc()).limit(max(limit, 200))
    if disabled_only:
        q = q.where(User.disabled_at.is_not(None))
    users = list((await db.execute(q)).scalars().all())
    if not users:
        return []

    ids = [u.id for u in users]
    proj_rows = (
        await db.execute(
            select(Project.owner_id, func.count())
            .where(Project.owner_id.in_(ids))
            .group_by(Project.owner_id)
        )
    ).all()
    proj_map = {str(r[0]): int(r[1] or 0) for r in proj_rows}

    start = datetime.combine(
        datetime.now(timezone.utc).date(), time.min, tzinfo=timezone.utc
    )
    usage_rows = (
        await db.execute(
            select(
                LlmUsage.user_id,
                func.coalesce(func.sum(LlmUsage.total_tokens), 0),
                func.count(LlmUsage.id),
            )
            .where(LlmUsage.user_id.in_(ids), LlmUsage.created_at >= start)
            .group_by(LlmUsage.user_id)
        )
    ).all()
    usage_map = {
        str(r[0]): (int(r[1] or 0), int(r[2] or 0)) for r in usage_rows
    }

    cap = int(getattr(settings, "max_projects_per_user", 80) or 80)
    out: List[AdminUserOut] = []
    for u in users:
        pc = proj_map.get(u.id, 0)
        tokens, calls = usage_map.get(u.id, (0, 0))
        flags, labels, severity = _flag_user(
            project_count=pc,
            tokens_today=tokens,
            calls_today=calls,
            created_at=u.created_at,
            disabled_at=u.disabled_at,
            max_projects=cap,
        )
        if bool(getattr(u, "is_admin", False)):
            flags = [*flags, "admin"]
            labels = [*labels, "管理员"]
        if anomalies_only and severity == "ok" and u.disabled_at is None:
            continue
        out.append(
            AdminUserOut(
                id=u.id,
                username=u.username,
                email=u.email,
                disabled_at=u.disabled_at,
                is_admin=bool(getattr(u, "is_admin", False)),
                created_at=u.created_at,
                project_count=pc,
                tokens_today=tokens,
                calls_today=calls,
                flags=flags,
                flag_labels=labels,
                severity=severity,
            )
        )

    rank = {"danger": 0, "warn": 1, "ok": 2}
    out.sort(
        key=lambda row: (
            0 if row.is_admin else 1,
            0 if row.disabled_at is None else 1,
            rank.get(row.severity, 9),
            -row.project_count,
            row.username,
        )
    )
    return out[:limit]


@router.get("/overview", response_model=AdminOverviewOut)
async def admin_overview(
    disabled_only: bool = False,
    anomalies_only: bool = False,
    limit: int = Query(100, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    _admin: User = Depends(get_admin_user),
):
    users = await _load_admin_users(
        db,
        settings,
        disabled_only=disabled_only,
        anomalies_only=anomalies_only,
        limit=limit,
    )
    total = int(
        (
            await db.execute(select(func.count()).select_from(User))
        ).scalar_one()
        or 0
    )
    disabled = int(
        (
            await db.execute(
                select(func.count())
                .select_from(User)
                .where(User.disabled_at.is_not(None))
            )
        ).scalar_one()
        or 0
    )
    return AdminOverviewOut(
        user_count=total,
        disabled_count=disabled,
        admin_count=await count_db_admins(db),
        danger_count=sum(1 for u in users if u.severity == "danger"),
        warn_count=sum(1 for u in users if u.severity == "warn"),
        max_projects_per_user=int(
            getattr(settings, "max_projects_per_user", 80) or 80
        ),
        users=users,
    )


@router.get("/users", response_model=List[AdminUserOut])
async def list_users(
    disabled_only: bool = False,
    anomalies_only: bool = False,
    limit: int = Query(100, ge=1, le=200),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
    _admin: User = Depends(get_admin_user),
):
    return await _load_admin_users(
        db,
        settings,
        disabled_only=disabled_only,
        anomalies_only=anomalies_only,
        limit=limit,
    )


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


@router.post("/users/{username}/grant-admin", response_model=AdminFlagOut)
async def grant_admin(
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
    if user.disabled_at is not None:
        raise HTTPException(status_code=400, detail="请先解禁再授予管理员")
    user.is_admin = True
    await db.commit()
    return AdminFlagOut(ok=True, username=name, is_admin=True, message="已设为管理员")


@router.post("/users/{username}/revoke-admin", response_model=AdminFlagOut)
async def revoke_admin(
    username: str,
    db: AsyncSession = Depends(get_db),
    admin: User = Depends(get_admin_user),
):
    name = username.strip()
    if not name:
        raise HTTPException(status_code=400, detail="用户名不能为空")
    result = await db.execute(select(User).where(User.username == name))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=404, detail="用户不存在")
    if not user.is_admin:
        return AdminFlagOut(
            ok=True, username=name, is_admin=False, message="本来就不是管理员"
        )
    remaining = await count_db_admins(db)
    if remaining <= 1:
        raise HTTPException(status_code=400, detail="不能撤销最后一位管理员")
    if name == admin.username:
        raise HTTPException(
            status_code=400, detail="不能撤销自己的管理员（请让其他管理员操作）"
        )
    user.is_admin = False
    await db.commit()
    return AdminFlagOut(
        ok=True, username=name, is_admin=False, message="已撤销管理员"
    )
