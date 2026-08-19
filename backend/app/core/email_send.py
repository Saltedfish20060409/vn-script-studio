"""Resend HTTP client for transactional mail."""
from __future__ import annotations

import httpx

from app.config import Settings


async def send_resend_email(
    settings: Settings,
    *,
    to: str,
    subject: str,
    html: str,
) -> None:
    api_key = (settings.resend_api_key or "").strip()
    from_addr = (settings.resend_from_email or "").strip()
    if not api_key:
        raise RuntimeError("未配置 RESEND_API_KEY，无法发送邮件")
    if not from_addr:
        raise RuntimeError("未配置 RESEND_FROM_EMAIL")
    headers = {
        "Authorization": f"Bearer {api_key}",
        "Content-Type": "application/json",
    }
    body = {
        "from": f"VN Script Studio <{from_addr}>",
        "to": [to],
        "subject": subject,
        "html": html,
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        res = await client.post("https://api.resend.com/emails", headers=headers, json=body)
    if res.status_code >= 400:
        raise RuntimeError(f"Resend {res.status_code}: {res.text[:300]}")
