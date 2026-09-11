import logging
import re
from datetime import datetime, timezone

import jwt
from fastapi import APIRouter, Depends, HTTPException, Request, Response, status
from pydantic import EmailStr, TypeAdapter
from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.analytics import SAMPLE_CREATED, SIGNUP, record_event
from app.core.rate_limit import check_rate
from app.db import get_db
from app.models import User, UserSettings
from app.schemas import (
    EmailTokenIn,
    ForgotPasswordIn,
    LoginIn,
    OkMessageOut,
    RegisterIn,
    RegisterOut,
    ResendVerifyIn,
    ResetPasswordIn,
    TokenOut,
    UserOut,
)
from app.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
    hash_password,
    verify_password,
)
from app.services.auth_email import (
    consume_email_token,
    is_email_verified,
    issue_email_token,
    normalize_email,
    send_reset_email,
    send_verify_email,
)
from app.services.settings import DEFAULT_BG

router = APIRouter(prefix="/auth", tags=["auth"])

logger = logging.getLogger(__name__)

_email_adapter = TypeAdapter(EmailStr)

# 渠道名只允许短标识（字母/数字/下划线/连字符）。这里允许到 200 再截断，
# 免得一个手写的超长 ?ref= 让注册接口直接 422（漏斗数据不值得挡住注册）。
_REF_RE = re.compile(r"^[a-zA-Z0-9_-]{1,200}$")

# 新用户自动创建示例项目时用的标题（可删，用户随手改掉也无妨）
SAMPLE_PROJECT_TITLE = "示例 · 雨夜车站（可直接改）"


def _clean_signup_source(raw: str | None) -> str | None:
    """校验并归一化 ?ref= 渠道名；不合法就当没带。"""
    if not raw:
        return None
    value = raw.strip().lower()
    if not _REF_RE.match(value):
        return None
    return value[:64]


async def _seed_sample_project(db: AsyncSession, user: User) -> None:
    """给新用户建一个示例项目（激活用）。

    任何失败都只记日志——注册流程绝不能因为示例项目建不出来而失败。
    """
    from app.config import get_settings as _get_settings

    if not getattr(_get_settings(), "sample_project_on_signup", True):
        return
    try:
        from app.services.projects import create_project_row

        row = await create_project_row(
            db, user, title=SAMPLE_PROJECT_TITLE, from_demo=True
        )
        await record_event(
            db,
            user.id,
            SAMPLE_CREATED,
            {"is_sample": "1", "kind": "auto", "from": "signup"},
        )
        await db.commit()
        logger.info("seeded sample project for new user %s (%s)", user.username, row.id)
    except Exception as exc:  # noqa: BLE001 - 激活流程不该阻塞注册
        await db.rollback()
        logger.warning("sample project seeding failed for %s: %s", user.username, exc)


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else ""


def _tokens(user: User, settings: Settings) -> TokenOut:
    tv = user.token_version or 0
    return TokenOut(
        access_token=create_access_token(user.id, settings, token_version=tv),
        refresh_token=None,  # refresh token travels in an HttpOnly cookie
        token_type="bearer",
        expires_in=settings.access_token_expire_minutes * 60,
    )


def _set_refresh_cookie(response: Response, token: str, settings: Settings) -> None:
    """Set the refresh token as an HttpOnly, SameSite=Strict cookie.

    SECURITY (M-4): the long-lived refresh token is no longer readable by JS
    (localStorage was XSS-exfiltratable). Access token stays in memory only.
    """
    max_age = settings.refresh_token_expire_days * 24 * 3600
    response.set_cookie(
        key="vnss_refresh",
        value=token,
        max_age=max_age,
        path="/api/v1/auth/refresh",
        httponly=True,
        samesite="strict",
        # 部署在 HTTPS 后置 True（.env: COOKIE_SECURE=true），Cookie 只在 TLS 上传输。
        secure=settings.cookie_secure,
    )


def _clear_refresh_cookie(response: Response) -> None:
    response.delete_cookie(
        key="vnss_refresh", path="/api/v1/auth/refresh", samesite="strict"
    )


def _user_out(user: User, *, is_admin: bool = False) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        email=user.email,
        email_verified=is_email_verified(user),
        created_at=user.created_at,
        is_admin=is_admin,
    )


def _parse_email(raw: str) -> str:
    email = normalize_email(raw)
    try:
        _email_adapter.validate_python(email)
    except Exception as exc:
        raise HTTPException(status_code=400, detail="邮箱格式不正确") from exc
    return email


@router.post("/register", response_model=RegisterOut)
async def register(
    body: RegisterIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    if not settings.allow_registration:
        raise HTTPException(status_code=403, detail="目前暂停注册")
    ip = _client_ip(request)
    if not check_rate(ip, "register", limit=20, enabled=settings.rate_limit_enabled):
        raise HTTPException(status_code=429, detail="注册过于频繁，请稍后再试")
    if not check_rate(
        ip,
        "register_hour",
        limit=80,
        enabled=settings.rate_limit_enabled,
        window=3600,
    ):
        raise HTTPException(status_code=429, detail="该网络今日注册次数较多，请稍后再试")
    if not (settings.resend_api_key or "").strip() and not settings.auth_auto_verify:
        raise HTTPException(
            status_code=503, detail="邮件服务未配置，暂时无法注册（请联系管理员）"
        )

    username = body.username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="用户名不能为空")
    email = _parse_email(body.email)

    existing_u = await db.execute(select(User).where(User.username == username))
    if existing_u.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="用户名已存在")
    existing_e = await db.execute(select(User).where(User.email == email))
    if existing_e.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="该邮箱已被注册")

    user = User(
        username=username,
        password_hash=hash_password(body.password),
        email=email,
        email_verified_at=datetime.now(timezone.utc) if settings.auth_auto_verify else None,
    )
    user.signup_source = _clean_signup_source(body.ref)
    db.add(user)
    await db.flush()
    db.add(UserSettings(user_id=user.id, bg=dict(DEFAULT_BG)))
    await record_event(
        db, user.id, SIGNUP, {"source": user.signup_source or "direct"}
    )
    if settings.auth_auto_verify:
        await db.commit()
        await _seed_sample_project(db, user)
        return RegisterOut(
            ok=True,
            message="注册成功，请登录",
            email=email,
        )
    token = await issue_email_token(db, user, "verify")
    try:
        await send_verify_email(settings, user, token)
        await db.commit()
    except Exception as exc:  # noqa: BLE001
        await db.rollback()
        msg = str(exc)
        # Resend 会拒绝 example.com 等保留域名（测试保护）——用户常误用假邮箱
        if "Invalid `to` field" in msg or "example.com" in msg.lower():
            raise HTTPException(
                status_code=422,
                detail="该邮箱地址无法接收验证邮件（示例域名不受支持），请使用真实邮箱",
            ) from exc
        raise HTTPException(
            status_code=502, detail="验证邮件发送失败，请稍后重试或联系管理员"
        ) from exc

    # 注册成功 → 送一个示例项目，让用户一进站就有内容可写（见 roadmap 方向 A）。
    await _seed_sample_project(db, user)

    return RegisterOut(
        ok=True,
        message="注册成功，请查收邮箱并点击验证链接后再登录",
        email=email,
    )


@router.post("/login", response_model=TokenOut)
async def login(
    body: LoginIn,
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    if not check_rate(
        _client_ip(request), "login", limit=20, enabled=settings.rate_limit_enabled
    ):
        raise HTTPException(status_code=429, detail="尝试过于频繁，请稍后再试")
    ident = body.username.strip()
    if not ident:
        raise HTTPException(status_code=400, detail="请填写用户名或邮箱")

    result = await db.execute(
        select(User).where(
            or_(User.username == ident, User.email == normalize_email(ident))
        )
    )
    user = result.scalar_one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        # Security event (A09): log failed login attempts (no PII beyond the
        # submitted identifier, which the user already sent us).
        logger.warning(
            "security login_failed ip=%s ident=%s reason=bad_credentials",
            _client_ip(request),
            ident[:64],
        )
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )
    if user.disabled_at is not None:
        logger.warning(
            "security login_failed ip=%s user=%s reason=disabled",
            _client_ip(request),
            user.username,
        )
        raise HTTPException(status_code=403, detail="账号已被停用")
    if user.email and not is_email_verified(user):
        logger.info(
            "security login_failed ip=%s user=%s reason=unverified",
            _client_ip(request),
            user.username,
        )
        raise HTTPException(
            status_code=403,
            detail="邮箱尚未验证，请先查收验证邮件（可在注册页重新发送）",
        )
    from app.services.admin_access import ensure_admin_access

    await ensure_admin_access(user, settings, db)
    tokens = _tokens(user, settings)
    _set_refresh_cookie(
        response,
        create_refresh_token(user.id, settings, token_version=(user.token_version or 0)),
        settings,
    )
    return tokens


@router.post("/verify-email", response_model=OkMessageOut)
async def verify_email(
    body: EmailTokenIn,
    db: AsyncSession = Depends(get_db),
):
    user = await consume_email_token(db, body.token, "verify")
    if user is None:
        raise HTTPException(status_code=400, detail="验证链接无效或已过期")
    user.email_verified_at = datetime.now(timezone.utc)
    await db.commit()
    return OkMessageOut(ok=True, message="邮箱已验证，请返回登录")


@router.post("/resend-verification", response_model=OkMessageOut)
async def resend_verification(
    body: ResendVerifyIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    if not check_rate(
        _client_ip(request), "resend_verify", limit=10, enabled=settings.rate_limit_enabled
    ):
        raise HTTPException(status_code=429, detail="发送过于频繁，请稍后再试")
    email = _parse_email(body.email)
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    # Don't leak whether the email exists (same response whether or not).
    if user is None or is_email_verified(user):
        return OkMessageOut(ok=True, message="若该邮箱未验证，我们已尝试重新发送")
    if not (settings.resend_api_key or "").strip():
        # Don't reveal the account exists via a 503 — treat as success.
        logger.warning("security resend skipped (email service not configured)")
        return OkMessageOut(ok=True, message="若该邮箱未验证，我们已尝试重新发送")
    token = await issue_email_token(db, user, "verify")
    try:
        await send_verify_email(settings, user, token)
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.warning("resend verification send failed: %s", exc)
        return OkMessageOut(ok=True, message="若该邮箱未验证，我们已尝试重新发送")
    return OkMessageOut(ok=True, message="若该邮箱未验证，我们已尝试重新发送")


@router.post("/forgot-password", response_model=OkMessageOut)
async def forgot_password(
    body: ForgotPasswordIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    if not check_rate(
        _client_ip(request), "forgot", limit=10, enabled=settings.rate_limit_enabled
    ):
        raise HTTPException(status_code=429, detail="发送过于频繁，请稍后再试")
    email = _parse_email(body.email)
    result = await db.execute(select(User).where(User.email == email))
    user = result.scalar_one_or_none()
    if user is None or not user.email:
        return OkMessageOut(ok=True, message="若该邮箱已注册，我们已发送重置链接")
    if not (settings.resend_api_key or "").strip():
        # Don't reveal the account exists via a 503 — treat as success.
        logger.warning("security forgot skipped (email service not configured)")
        return OkMessageOut(ok=True, message="若该邮箱已注册，我们已发送重置链接")
    token = await issue_email_token(db, user, "reset")
    try:
        await send_reset_email(settings, user, token)
        await db.commit()
    except Exception as exc:
        await db.rollback()
        logger.warning("forgot password send failed: %s", exc)
        return OkMessageOut(ok=True, message="若该邮箱已注册，我们已发送重置链接")
    return OkMessageOut(ok=True, message="若该邮箱已注册，我们已发送重置链接")


@router.post("/reset-password", response_model=OkMessageOut)
async def reset_password(
    body: ResetPasswordIn,
    db: AsyncSession = Depends(get_db),
):
    user = await consume_email_token(db, body.token, "reset")
    if user is None:
        raise HTTPException(status_code=400, detail="重置链接无效或已过期")
    user.password_hash = hash_password(body.password)
    # SECURITY (M-2): password reset invalidates all previously issued tokens.
    user.token_version = (user.token_version or 0) + 1
    # Resetting via email also counts as proving ownership.
    if user.email and user.email_verified_at is None:
        user.email_verified_at = datetime.now(timezone.utc)
    await db.commit()
    return OkMessageOut(ok=True, message="密码已更新，请使用新密码登录")


@router.post("/refresh", response_model=TokenOut)
async def refresh(
    request: Request,
    response: Response,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Exchange the HttpOnly refresh cookie for a fresh access token (+ rotated cookie)."""
    if not check_rate(
        _client_ip(request), "refresh", limit=60, enabled=settings.rate_limit_enabled
    ):
        raise HTTPException(status_code=429, detail="刷新过于频繁，请稍后再试")
    rt = request.cookies.get("vnss_refresh")
    if not rt:
        raise HTTPException(status_code=401, detail="刷新令牌缺失")
    try:
        payload = decode_token(rt.strip(), settings)
    except jwt.InvalidTokenError as exc:
        raise HTTPException(status_code=401, detail="刷新令牌无效或已过期") from exc
    if payload.get("typ") != "refresh" or not payload.get("sub"):
        raise HTTPException(status_code=401, detail="刷新令牌无效")
    user_id = str(payload["sub"])
    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="用户不存在")
    if user.disabled_at is not None:
        raise HTTPException(status_code=403, detail="账号已被停用")
    # SECURITY (M-2): refresh tokens are invalid once token_version was bumped
    # (password reset / change / ban). Old stolen refresh tokens die instantly.
    claimed = payload.get("tv")
    if isinstance(claimed, int) and claimed != (user.token_version or 0):
        raise HTTPException(status_code=401, detail="刷新令牌已失效，请重新登录")
    tokens = _tokens(user, settings)
    _set_refresh_cookie(
        response,
        create_refresh_token(user.id, settings, token_version=(user.token_version or 0)),
        settings,
    )
    return tokens


@router.post("/logout", response_model=OkMessageOut)
async def logout(response: Response):
    """Clear the HttpOnly refresh cookie (client discards the access token)."""
    _clear_refresh_cookie(response)
    return OkMessageOut(ok=True, message="已退出登录")


@router.get("/me", response_model=UserOut)
async def me(
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
):
    from app.services.admin_access import ensure_admin_access

    is_admin = await ensure_admin_access(user, settings, db)
    return _user_out(user, is_admin=is_admin)
