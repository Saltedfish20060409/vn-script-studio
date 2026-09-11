"""产品埋点上报入口 — 前端只上报"客户端才知道"的动作（试玩、下载导出等）。

安全与隐私：
- 需要登录（事件必须能归因到用户；匿名事件对漏斗没用）；
- 按用户限流，避免被刷；
- 事件名走 app/core/analytics.py 的白名单，props 也只留白名单键，
  因此前端的 bug 不会把正文/密钥之类内容写进埋点表。
"""

from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.analytics import EVENT_NAMES, sanitize_props
from app.core.rate_limit import check_rate
from app.db import get_db
from app.models import ProductEvent, User
from app.security import get_current_user

router = APIRouter(prefix="/events", tags=["events"])

_MAX_BATCH = 20


class EventIn(BaseModel):
    name: str = Field(min_length=1, max_length=48)
    props: Optional[dict] = None


class EventsIn(BaseModel):
    events: List[EventIn] = Field(default_factory=list, max_length=_MAX_BATCH)


@router.post("")
async def ingest_events(
    body: EventsIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """批量写入前端事件；未知事件名静默跳过（不报错，避免前端重试风暴）。"""
    if not check_rate(
        user.id,
        "product_events",
        limit=120,
        enabled=settings.rate_limit_enabled,
        window=3600,
    ):
        raise HTTPException(status_code=429, detail="上报过于频繁")

    accepted = 0
    for evt in body.events[:_MAX_BATCH]:
        name = (evt.name or "").strip()
        if name not in EVENT_NAMES:
            continue
        db.add(
            ProductEvent(
                user_id=user.id,
                name=name,
                props=sanitize_props(evt.props),
            )
        )
        accepted += 1
    if accepted:
        await db.commit()
    return {"ok": True, "accepted": accepted}
