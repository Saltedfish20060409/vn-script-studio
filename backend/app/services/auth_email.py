"""Email verification + password-reset token helpers."""
from __future__ import annotations

import html as html_lib
import secrets
from datetime import datetime, timedelta, timezone
from typing import Literal, Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.email_send import send_resend_email
from app.models import AuthEmailToken, User

Purpose = Literal["verify", "reset"]

_TTL = {
    "verify": timedelta(hours=48),
    "reset": timedelta(hours=2),
}


def normalize_email(raw: str) -> str:
    return raw.strip().lower()


def is_email_verified(user: User) -> bool:
    """Legacy users (no email) are treated as verified for login."""
    if not user.email:
        return True
    return user.email_verified_at is not None


async def issue_email_token(
    db: AsyncSession,
    user: User,
    purpose: Purpose,
) -> str:
    token = secrets.token_urlsafe(32)
    row = AuthEmailToken(
        user_id=user.id,
        token=token,
        purpose=purpose,
        expires_at=datetime.now(timezone.utc) + _TTL[purpose],
    )
    db.add(row)
    await db.flush()
    return token


async def consume_email_token(
    db: AsyncSession,
    token: str,
    purpose: Purpose,
) -> Optional[User]:
    result = await db.execute(
        select(AuthEmailToken).where(AuthEmailToken.token == token.strip())
    )
    row = result.scalar_one_or_none()
    if row is None or row.purpose != purpose or row.used_at is not None:
        return None
    now = datetime.now(timezone.utc)
    exp = row.expires_at
    if exp.tzinfo is None:
        exp = exp.replace(tzinfo=timezone.utc)
    if exp < now:
        return None
    user = await db.get(User, row.user_id)
    if user is None:
        return None
    row.used_at = now
    return user


def _app_base(settings: Settings) -> str:
    return (settings.public_app_url or "").rstrip("/")


def _sticker(settings: Settings, filename: str, alt: str) -> str:
    src = f"{_app_base(settings)}/email/{filename}"
    return (
        f'<p style="margin:20px 0;text-align:center;background:#ffffff">'
        f'<img src="{html_lib.escape(src)}" alt="{html_lib.escape(alt)}" '
        f'width="220" style="max-width:220px;height:auto;border:0;display:inline-block;'
        f'background:#ffffff" />'
        f"</p>"
    )


def _btn(href: str, label: str) -> str:
    safe_href = html_lib.escape(href, quote=True)
    safe_label = html_lib.escape(label)
    return (
        f'<p style="margin:24px 0;text-align:center">'
        f'<a href="{safe_href}" '
        f'style="display:inline-block;padding:12px 22px;background:#002fa7;color:#ffffff;'
        f"text-decoration:none;font-weight:700;border-radius:8px;font-family:sans-serif;"
        f'font-size:15px">{safe_label}</a></p>'
        f'<p style="margin:0;font-size:12px;line-height:1.5;color:#666;word-break:break-all">'
        f'若按钮无法点击，请复制此链接到浏览器：<br />'
        f'<a href="{safe_href}" style="color:#002fa7">{safe_href}</a></p>'
    )


def _shell(*blocks: str) -> str:
    inner = "".join(blocks)
    return (
        '<div style="max-width:560px;margin:0 auto;padding:24px 20px;'
        'font-family:-apple-system,BlinkMacSystemFont,Segoe UI,Helvetica,Arial,'
        f'sans-serif;font-size:15px;line-height:1.65;color:#1a1a1a">{inner}</div>'
    )


async def send_verify_email(settings: Settings, user: User, token: str) -> None:
    base = _app_base(settings)
    link = f"{base}/verify-email?token={token}"
    name = html_lib.escape(user.username)
    html = _shell(
        f"<p>你好，{name}：</p>",
        "<p>欢迎来到 VN Script Studio。<br />"
        "角色、章节、地图和审稿，都可以在这里慢慢搭起来，"
        "用来辅助你的视觉小说/轻小说写作。</p>",
        _sticker(settings, "welcome-typing.gif", "看板娘贴纸：打字"),
        "<p>先点下面的按钮验证邮箱（48 小时内有效），验证后就能登录开工：</p>",
        _btn(link, "验证邮箱"),
        "<p>如果这不是你本人注册的，忽略这封邮件即可。</p>",
        "<p>—— VN Script Studio</p>",
    )
    await send_resend_email(
        settings,
        to=user.email or "",
        subject="欢迎加入 VN Script Studio —— 请验证邮箱",
        html=html,
    )


async def send_reset_email(settings: Settings, user: User, token: str) -> None:
    base = _app_base(settings)
    link = f"{base}/reset-password?token={token}"
    name = html_lib.escape(user.username)
    html = _shell(
        f"<p>你好，{name}：</p>",
        "<p>收到你的密码重置请求了。</p>",
        _sticker(settings, "reset-notes.gif", "看板娘贴纸：记录"),
        "<p>点下面按钮设置新密码（2 小时内有效）：</p>",
        _btn(link, "重置密码"),
        "<p>如果不是你本人操作，请忽略；密码不会被改动。</p>",
        "<p>—— VN Script Studio</p>",
    )
    await send_resend_email(
        settings,
        to=user.email or "",
        subject="重置你的 Script Studio 密码",
        html=html,
    )
