"""User LLM usage overview (read-only)."""

from __future__ import annotations

from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.usage import today_usage, user_usage_totals
from app.db import get_db
from app.models import User
from app.security import get_current_user

router = APIRouter(tags=["usage"])


@router.get("/usage")
async def usage_overview(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    total = await user_usage_totals(db, user.id)
    today = await today_usage(db, user.id)
    return {"today": today, "total": total}
