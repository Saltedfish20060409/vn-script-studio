from fastapi import APIRouter, Depends, HTTPException, Request, status
from jose import JWTError
from pydantic import EmailStr, TypeAdapter
from sqlalchemy import or_, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.rate_limit import check_rate
from app.db import get_db
from app.models import User, UserSettings
from app.schemas import (
    EmailTokenIn,
    ForgotPasswordIn,
    LoginIn,
    OkMessageOut,
    RefreshIn,
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
from datetime import datetime, timezone

router = APIRouter(prefix="/auth", tags=["auth"])

_email_adapter = TypeAdapter(EmailStr)


def _client_ip(request: Request) -> str:
    fwd = request.headers.get("x-forwarded-for")
    if fwd:
        return fwd.split(",")[0].strip()
    return request.client.host if request.client else ""


def _tokens(user_id: str, settings: Settings) -> TokenOut:
    return TokenOut(
        access_token=create_access_token(user_id, settings),
        refresh_token=create_refresh_token(user_id, settings),
        token_type="bearer",
        expires_in=settings.access_token_expire_minutes * 60,
    )


def _user_out(user: User) -> UserOut:
    return UserOut(
        id=user.id,
        username=user.username,
        email=user.email,
        email_verified=is_email_verified(user),
        created_at=user.created_at,
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
    db.add(user)
    await db.flush()
    db.add(UserSettings(user_id=user.id, bg=dict(DEFAULT_BG)))
    if settings.auth_auto_verify:
        await db.commit()
        return RegisterOut(
            ok=True,
            message="注册成功，请登录",
            email=email,
        )
    token = await issue_email_token(db, user, "verify")
    try:
        await send_verify_email(settings, user, token)
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise HTTPException(
            status_code=502, detail=f"验证邮件发送失败：{exc}"
        ) from exc

    return RegisterOut(
        ok=True,
        message="注册成功，请查收邮箱并点击验证链接后再登录",
        email=email,
    )


@router.post("/login", response_model=TokenOut)
async def login(
    body: LoginIn,
    request: Request,
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
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )
    if user.disabled_at is not None:
        raise HTTPException(status_code=403, detail="账号已被停用")
    if user.email and not is_email_verified(user):
        raise HTTPException(
            status_code=403,
            detail="邮箱尚未验证，请先查收验证邮件（可在注册页重新发送）",
        )
    return _tokens(user.id, settings)


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
    # Don't leak whether the email exists.
    if user is None or is_email_verified(user):
        return OkMessageOut(ok=True, message="若该邮箱未验证，我们已尝试重新发送")
    if not (settings.resend_api_key or "").strip():
        raise HTTPException(status_code=503, detail="邮件服务未配置")
    token = await issue_email_token(db, user, "verify")
    try:
        await send_verify_email(settings, user, token)
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=502, detail=f"发送失败：{exc}") from exc
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
        raise HTTPException(status_code=503, detail="邮件服务未配置")
    token = await issue_email_token(db, user, "reset")
    try:
        await send_reset_email(settings, user, token)
        await db.commit()
    except Exception as exc:
        await db.rollback()
        raise HTTPException(status_code=502, detail=f"发送失败：{exc}") from exc
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
    # Resetting via email also counts as proving ownership.
    if user.email and user.email_verified_at is None:
        user.email_verified_at = datetime.now(timezone.utc)
    await db.commit()
    return OkMessageOut(ok=True, message="密码已更新，请使用新密码登录")


@router.post("/refresh", response_model=TokenOut)
async def refresh(
    body: RefreshIn,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Exchange a valid refresh token for a fresh access token (+ rotated refresh)."""
    try:
        payload = decode_token(body.refresh_token.strip(), settings)
    except JWTError as exc:
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
    return _tokens(user.id, settings)


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return _user_out(user)
