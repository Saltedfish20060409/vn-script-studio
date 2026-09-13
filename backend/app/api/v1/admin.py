"""Operator admin API — ban / unban / grant-admin + anomaly-flagged user list."""

from __future__ import annotations

from datetime import datetime, time, timedelta, timezone
from typing import List, Literal, Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import Text, cast, func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.app_logging import app_logger
from app.db import get_db
from app.models import User
from app.models.tables import LlmUsage, Project, ProjectChapterRow
from app.security import get_admin_user
from app.services.admin_access import count_db_admins

router = APIRouter(prefix="/admin", tags=["admin"])

# Security audit log (A09): every privilege / ban change must be traceable.
# 必须自带 handler，否则这些审计行在容器日志里根本看不到（见 core/app_logging.py）。
audit_logger = app_logger("vnss.audit")

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


class EmailDiagOut(BaseModel):
    """「收不到验证邮件」排查结果（只读，见 /admin/email-diag）。"""

    query: str
    matched_by: Literal["email", "username", "none"] = "none"
    username: Optional[str] = None
    email: Optional[str] = None
    email_verified: bool = False
    created_at: Optional[datetime] = None
    verify_sends: int = 0
    verify_clicks: int = 0
    reset_sends: int = 0
    reset_clicks: int = 0
    last_verify_sent_at: Optional[datetime] = None
    last_click_lag_s: Optional[int] = None
    similar: List[dict] = Field(default_factory=list)
    hint: str = ""


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


@router.get("/email-diag", response_model=EmailDiagOut)
async def email_diag(
    q: str = Query(..., min_length=3, max_length=255),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_admin_user),
):
    """用户反馈「收不到验证邮件」时的一句话排查入口（只读）。

    一次给出：账号是否存在、邮箱是否已验证、验证邮件发了几封/点了没、
    最近一封什么时候发的、同域名还有没有别的待验证账号。省掉翻日志 + 手写 SQL。
    """
    from app.models.tables import AuthEmailToken

    ident = q.strip()
    matched = "none"
    user: Optional[User] = None
    if "@" in ident:
        row = await db.execute(
            select(User).where(func.lower(User.email) == ident.lower())
        )
        user = row.scalar_one_or_none()
        if user is not None:
            matched = "email"
    else:
        row = await db.execute(select(User).where(User.username == ident))
        user = row.scalar_one_or_none()
        if user is not None:
            matched = "username"

    out = EmailDiagOut(query=ident, matched_by=matched)
    if user is None:
        # 近似的账号（用户名/邮箱含关键字），用来兜住"填错一位/域名写错"的情况。
        # 带 @ 时额外按 @ 前面那段搜，这样把 example.org 写成 example.com 也能找到人。
        terms = [ident]
        if "@" in ident:
            local = ident.split("@")[0].strip()
            if local and local != ident:
                terms.append(local)
        conds = []
        for term in terms:
            like = f"%{term}%"
            conds.append(User.username.ilike(like))
            conds.append(User.email.ilike(like))
        rows = await db.execute(
            select(User.username, User.email, User.email_verified_at)
            .where(or_(*conds))
            .limit(8)
        )
        out.similar = [
            {
                "username": r[0],
                "email": r[1],
                "verified": r[2] is not None,
            }
            for r in rows.all()
        ]
        out.hint = (
            "没有这个账号：用户很可能是用另一个邮箱/用户名注册的，"
            "或注册请求本身失败了（看 server 日志里的 register 400）。"
        )
        return out

    out.username = user.username
    out.email = user.email
    out.email_verified = user.email_verified_at is not None
    out.created_at = user.created_at

    agg = await db.execute(
        select(
            AuthEmailToken.purpose,
            func.count().label("sends"),
            func.count(AuthEmailToken.used_at).label("clicks"),
            func.max(AuthEmailToken.created_at).label("last_sent"),
        )
        .where(AuthEmailToken.user_id == user.id)
        .group_by(AuthEmailToken.purpose)
    )
    for purpose, sends, clicks, last_sent in agg.all():
        if purpose == "verify":
            out.verify_sends = int(sends)
            out.verify_clicks = int(clicks)
            out.last_verify_sent_at = last_sent
        elif purpose == "reset":
            out.reset_sends = int(sends)
            out.reset_clicks = int(clicks)

    last_click = await db.execute(
        select(AuthEmailToken)
        .where(AuthEmailToken.user_id == user.id)
        .where(AuthEmailToken.purpose == "verify")
        .where(AuthEmailToken.used_at.is_not(None))
        .order_by(AuthEmailToken.used_at.desc())
        .limit(1)
    )
    token_row = last_click.scalar_one_or_none()
    if token_row is not None and token_row.used_at is not None:
        out.last_click_lag_s = int(
            (token_row.used_at - token_row.created_at).total_seconds()
        )

    if out.email_verified:
        out.hint = "邮箱已验证，说明邮件链路是通的（用户可能在重复点重发）。"
    elif out.verify_sends == 0:
        out.hint = "账号存在但一封验证邮件都没成功发出，查注册时的 send 报错。"
    elif out.verify_clicks == 0:
        dom = (user.email or "").split("@")[-1].lower()
        out.hint = (
            f"发出 {out.verify_sends} 封、一次都没点开：大概率在 {dom} 的垃圾邮件箱，"
            "或用户注册完就离开了。可让用户在邮箱里搜「vnscriptstudio」。"
        )
    else:
        out.hint = "点开过但当前未验证：可能是点了过期/已用过的链接。"
    return out


@router.get("/funnel")
async def admin_funnel(
    days: int = Query(30, ge=1, le=365),
    db: AsyncSession = Depends(get_db),
    _admin: User = Depends(get_admin_user),
):
    """激活漏斗（见 docs/roadmap-2026-09.md 方向 B）。

    - 漏斗按「首次发生」口径统计，避免重复动作把数字撑大；
    - 只读，不做任何写操作。
    """
    from app.core.analytics import (
        AI_CALL,
        EXPORT_DONE,
        PLAYTEST_OPENED,
        PROJECT_CREATED,
        PROSE_SAVED,
        RPY_GENERATED,
        SAMPLE_CREATED,
        SHARE_CREATED,
    )
    from app.models.tables import ProductEvent

    since = datetime.now(timezone.utc) - timedelta(days=days)

    # 各事件的唯一用户数（首次口径天然成立：同一用户只会有一次 first_* 写入，
    # 这里用 distinct 再兜一层）
    rows = (
        await db.execute(
            select(ProductEvent.name, func.count(func.distinct(ProductEvent.user_id)))
            .where(ProductEvent.created_at >= since)
            .group_by(ProductEvent.name)
        )
    ).all()
    counts = {str(r[0]): int(r[1] or 0) for r in rows}

    # 注册 / 验证 / 建项目 / 写过正文 / 用过 AI 直接从业务表算（更准）
    total_users = int(
        (await db.execute(select(func.count()).select_from(User))).scalar_one() or 0
    )
    verified = int(
        (
            await db.execute(
                select(func.count())
                .select_from(User)
                .where(User.email_verified_at.is_not(None))
            )
        ).scalar_one()
        or 0
    )
    users_with_project = int(
        (
            await db.execute(select(func.count(func.distinct(Project.owner_id))))
        ).scalar_one()
        or 0
    )
    users_with_prose = int(
        (
            await db.execute(
                select(func.count(func.distinct(Project.owner_id)))
                .select_from(ProjectChapterRow)
                .join(Project, Project.id == ProjectChapterRow.project_id)
                .where(
                    func.length(cast(ProjectChapterRow.blocks, Text)) > 60
                )
            )
        ).scalar_one()
        or 0
    )
    users_with_ai = int(
        (
            await db.execute(select(func.count(func.distinct(LlmUsage.user_id))))
        ).scalar_one()
        or 0
    )

    funnel = [
        {"key": "signup", "label": "注册", "users": total_users},
        {"key": "verified", "label": "邮箱已验证", "users": verified},
        {"key": "project", "label": "建过项目", "users": users_with_project},
        {"key": "prose", "label": "写过正文", "users": users_with_prose},
        {"key": "ai", "label": "用过 AI", "users": users_with_ai},
        {
            "key": "rpy",
            "label": "生成过 RPY",
            "users": counts.get(RPY_GENERATED, 0),
        },
        {
            "key": "playtest",
            "label": "试玩过",
            "users": counts.get(PLAYTEST_OPENED, 0),
        },
        {
            "key": "export",
            "label": "导出过",
            "users": counts.get(EXPORT_DONE, 0),
        },
    ]

    event_totals = {
        "sample_created": counts.get(SAMPLE_CREATED, 0),
        "project_created": counts.get(PROJECT_CREATED, 0),
        "prose_saved": counts.get(PROSE_SAVED, 0),
        "ai_call": counts.get(AI_CALL, 0),
        "share_created": counts.get(SHARE_CREATED, 0),
        "playtest_opened": counts.get(PLAYTEST_OPENED, 0),
        "export_done": counts.get(EXPORT_DONE, 0),
    }

    return {
        "days": days,
        "funnel": funnel,
        "events": event_totals,
        "notes": (
            "漏斗为累计口径；各步人数为该动作的累计去重人数"
            "（数据库口径用注册/验证/建项目/写正文/用 AI，事件口径用 rpy/试玩/导出）。"
        ),
    }


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
    # SECURITY (M-2): ban invalidates all of the user's sessions immediately.
    user.token_version = (user.token_version or 0) + 1
    await db.commit()
    audit_logger.info(
        "audit action=ban actor=%s target=%s ok=true", admin.username, name
    )
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
    audit_logger.info(
        "audit action=unban actor=%s target=%s ok=true", _admin.username, name
    )
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
    audit_logger.info(
        "audit action=grant_admin actor=%s target=%s ok=true", _admin.username, name
    )
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
    audit_logger.info(
        "audit action=revoke_admin actor=%s target=%s ok=true", admin.username, name
    )
    return AdminFlagOut(
        ok=True, username=name, is_admin=False, message="已撤销管理员"
    )
