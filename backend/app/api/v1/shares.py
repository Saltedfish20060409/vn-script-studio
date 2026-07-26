from datetime import datetime, timezone

from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import Share
from app.schemas import ShareOut

router = APIRouter(prefix="/shares", tags=["shares"])


@router.get("/{token}", response_model=ShareOut)
async def get_share(token: str, db: AsyncSession = Depends(get_db)):
    result = await db.execute(select(Share).where(Share.token == token))
    share = result.scalar_one_or_none()
    if share is None:
        raise HTTPException(status_code=404, detail="分享不存在或已失效")
    if share.expires_at is not None:
        exp = share.expires_at
        if exp.tzinfo is None:
            exp = exp.replace(tzinfo=timezone.utc)
        if exp < datetime.now(timezone.utc):
            raise HTTPException(status_code=410, detail="分享已过期")
    return ShareOut(
        token=share.token,
        title=share.title_snapshot,
        project=share.data_snapshot or {},
        created_at=share.created_at,
    )
