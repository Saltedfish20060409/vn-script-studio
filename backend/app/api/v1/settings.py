from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession

from app.db import get_db
from app.models import User
from app.schemas import SettingsOut, SettingsPutIn
from app.security import get_current_user
from app.services.settings import get_or_create_settings, settings_to_out, update_settings

router = APIRouter(prefix="/settings", tags=["settings"])


@router.get("", response_model=SettingsOut)
async def get_settings_api(
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await get_or_create_settings(db, user.id)
    return settings_to_out(row)


@router.put("", response_model=SettingsOut)
async def put_settings_api(
    body: SettingsPutIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await get_or_create_settings(db, user.id)
    row = await update_settings(db, row, body)
    return settings_to_out(row)
