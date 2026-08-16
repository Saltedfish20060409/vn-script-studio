from fastapi import APIRouter, Depends, HTTPException, status
from jose import JWTError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_db
from app.models import User, UserSettings
from app.schemas import LoginIn, RefreshIn, RegisterIn, TokenOut, UserOut
from app.security import (
    create_access_token,
    create_refresh_token,
    decode_token,
    get_current_user,
    hash_password,
    verify_password,
)
from app.services.settings import DEFAULT_BG

router = APIRouter(prefix="/auth", tags=["auth"])


def _tokens(user_id: str, settings: Settings) -> TokenOut:
    return TokenOut(
        access_token=create_access_token(user_id, settings),
        refresh_token=create_refresh_token(user_id, settings),
        token_type="bearer",
        expires_in=settings.access_token_expire_minutes * 60,
    )


@router.post("/register", response_model=TokenOut)
async def register(
    body: RegisterIn,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    username = body.username.strip()
    if not username:
        raise HTTPException(status_code=400, detail="用户名不能为空")
    existing = await db.execute(select(User).where(User.username == username))
    if existing.scalar_one_or_none():
        raise HTTPException(status_code=400, detail="用户名已存在")

    user = User(username=username, password_hash=hash_password(body.password))
    db.add(user)
    await db.flush()
    db.add(UserSettings(user_id=user.id, bg=dict(DEFAULT_BG)))
    await db.commit()
    await db.refresh(user)
    return _tokens(user.id, settings)


@router.post("/login", response_model=TokenOut)
async def login(
    body: LoginIn,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    result = await db.execute(select(User).where(User.username == body.username.strip()))
    user = result.scalar_one_or_none()
    if user is None or not verify_password(body.password, user.password_hash):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="用户名或密码错误",
        )
    return _tokens(user.id, settings)


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
    if result.scalar_one_or_none() is None:
        raise HTTPException(status_code=401, detail="用户不存在")
    return _tokens(user_id, settings)


@router.get("/me", response_model=UserOut)
async def me(user: User = Depends(get_current_user)):
    return UserOut(id=user.id, username=user.username, created_at=user.created_at)
