from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.project import uid
from app.core.rate_limit import check_rate
from app.db import get_db
from app.models import ErrorReport, User
from app.security import get_current_user

router = APIRouter(prefix="/errors", tags=["errors"])


class ErrorReportIn(BaseModel):
    message: str = Field(min_length=1, max_length=2000)
    stack: str = Field(default="", max_length=8000)
    url: str = Field(default="", max_length=1024)
    level: str = Field(default="error", pattern="^(error|warn)$")
    component: str = Field(default="", max_length=64)


@router.post("")
async def report_error(
    body: ErrorReportIn,
    request: Request,
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """Public, unauthenticated error-report sink (rate-limited per IP).

    Fire-and-forget from the client; stores for later diagnosis and never
    echoes anything back that could leak.
    """
    ip = request.client.host if request.client else None
    if not check_rate(ip, "error_report", limit=20, enabled=True):
        raise HTTPException(status_code=429, detail="错误上报过于频繁")

    user_id: Optional[str] = None
    auth = request.headers.get("Authorization")
    if auth and auth.startswith("Bearer "):
        from app.security import decode_token

        try:
            payload = decode_token(auth[7:], settings)
            if payload and payload.get("sub"):
                user_id = str(payload["sub"])
        except Exception:  # noqa: BLE001 — optional attribution only
            pass

    row = ErrorReport(
        id=uid("err"),
        level=body.level or "error",
        message=body.message.strip()[:2000],
        stack=body.stack.strip()[:8000],
        url=body.url.strip()[:1024],
        component=body.component.strip()[:64],
        user_agent=(request.headers.get("user-agent") or "")[:512],
        user_id=user_id,
    )
    db.add(row)
    await db.commit()
    return {"ok": True}


@router.get("")
async def list_errors(
    limit: int = 100,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Recent error reports (own + anonymous) for local diagnosis."""
    res = await db.execute(
        select(ErrorReport)
        .where(
            (ErrorReport.user_id == user.id) | (ErrorReport.user_id.is_(None))
        )
        .order_by(ErrorReport.created_at.desc())
        .limit(min(max(limit, 1), 500))
    )
    rows = res.scalars().all()
    return {
        "reports": [
            {
                "id": r.id,
                "level": r.level,
                "message": r.message,
                "stack": r.stack[:500],
                "url": r.url,
                "component": r.component,
                "createdAt": r.created_at.isoformat() if r.created_at else None,
            }
            for r in rows
        ]
    }
