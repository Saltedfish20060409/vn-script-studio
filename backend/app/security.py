from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import bcrypt
import jwt
from cryptography.fernet import Fernet, InvalidToken
from fastapi import Depends, HTTPException, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.db import get_db
from app.models import User

# PyJWT raises jwt.InvalidTokenError (subclass hierarchy compatible with the
# old python-jose JWTError usages).
JWTError = jwt.InvalidTokenError
bearer_scheme = HTTPBearer(auto_error=False)


def hash_password(password: str) -> str:
    # bcrypt truncates at 72 bytes — schemas already cap length at 72.
    return bcrypt.hashpw(password.encode("utf-8"), bcrypt.gensalt()).decode("ascii")


def verify_password(plain: str, hashed: str) -> bool:
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("ascii"))
    except (ValueError, TypeError):
        # Malformed stored hash → treat as invalid, never crash the login.
        return False


def create_access_token(
    subject: str,
    settings: Settings,
    expires_delta: Optional[timedelta] = None,
    token_version: int = 0,
) -> str:
    expire = datetime.now(timezone.utc) + (
        expires_delta
        or timedelta(minutes=settings.access_token_expire_minutes)
    )
    return jwt.encode(
        {
            "sub": subject,
            "typ": "access",
            "tv": token_version,
            "exp": expire,
        },
        settings.secret_key,
        algorithm=settings.algorithm,
    )


def create_refresh_token(
    subject: str,
    settings: Settings,
    expires_delta: Optional[timedelta] = None,
    token_version: int = 0,
) -> str:
    expire = datetime.now(timezone.utc) + (
        expires_delta or timedelta(days=settings.refresh_token_expire_days)
    )
    return jwt.encode(
        {
            "sub": subject,
            "typ": "refresh",
            "tv": token_version,
            "exp": expire,
        },
        settings.secret_key,
        algorithm=settings.algorithm,
    )


def decode_token(token: str, settings: Settings) -> dict[str, Any]:
    """Decode a JWT, raising JWTError on invalid/expired."""
    return jwt.decode(token, settings.secret_key, algorithms=[settings.algorithm])


def _fernet(settings: Settings) -> Optional[Fernet]:
    key = (settings.settings_fernet_key or "").strip()
    if not key:
        # Derive a stable key from secret_key for local/dev when not configured
        import base64
        import hashlib

        digest = hashlib.sha256(settings.secret_key.encode()).digest()
        key = base64.urlsafe_b64encode(digest).decode()
    try:
        return Fernet(key.encode() if isinstance(key, str) else key)
    except Exception:
        import base64
        import hashlib

        digest = hashlib.sha256(settings.secret_key.encode()).digest()
        return Fernet(base64.urlsafe_b64encode(digest))


def encrypt_secret(value: str, settings: Settings) -> str:
    if not value:
        return ""
    return _fernet(settings).encrypt(value.encode()).decode()


def decrypt_secret(token: str, settings: Settings) -> str:
    if not token:
        return ""
    try:
        return _fernet(settings).decrypt(token.encode()).decode()
    except InvalidToken:
        return ""


def mask_api_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "***"
    return f"{key[:3]}***{key[-4:]}"


async def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(bearer_scheme),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
) -> User:
    if credentials is None or not credentials.credentials:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="未登录",
            headers={"WWW-Authenticate": "Bearer"},
        )
    try:
        payload: dict[str, Any] = jwt.decode(
            credentials.credentials,
            settings.secret_key,
            algorithms=[settings.algorithm],
        )
        user_id = payload.get("sub")
        if not user_id or payload.get("typ") == "refresh":
            raise HTTPException(status_code=401, detail="无效令牌")
    except JWTError as exc:
        raise HTTPException(status_code=401, detail="无效令牌") from exc

    result = await db.execute(select(User).where(User.id == user_id))
    user = result.scalar_one_or_none()
    if user is None:
        raise HTTPException(status_code=401, detail="用户不存在")
    if user.disabled_at is not None:
        raise HTTPException(status_code=403, detail="账号已被停用")
    # SECURITY (M-2): tokens carry the user's token_version at issuance; if the
    # version has since been bumped (password reset / change / ban), reject.
    claimed = payload.get("tv")
    if isinstance(claimed, int) and claimed != (user.token_version or 0):
        raise HTTPException(status_code=401, detail="令牌已失效，请重新登录")
    return user


async def get_admin_user(
    user: User = Depends(get_current_user),
    settings: Settings = Depends(get_settings),
    db: AsyncSession = Depends(get_db),
) -> User:
    """Require a DB admin (or bootstrap seed when no admins exist yet)."""
    from app.services.admin_access import ensure_admin_access

    if not await ensure_admin_access(user, settings, db):
        raise HTTPException(status_code=403, detail="需要管理员权限")
    return user
