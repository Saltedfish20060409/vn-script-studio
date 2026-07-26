from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models import UserSettings
from app.schemas import SettingsOut, SettingsPutIn

DEFAULT_BG = {
    "bgImage": "",
    "bgScale": 1.0,
    "bgOpacity": 0.35,
    "bgPanX": 0.0,
    "bgPanY": 0.0,
}


async def get_or_create_settings(db: AsyncSession, user_id: str) -> UserSettings:
    result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == user_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        row = UserSettings(user_id=user_id, bg=dict(DEFAULT_BG))
        db.add(row)
        await db.commit()
        await db.refresh(row)
    return row


def settings_to_out(row: UserSettings) -> SettingsOut:
    bg = dict(DEFAULT_BG)
    bg.update(row.bg or {})
    return SettingsOut(
        theme=row.theme,
        font_scale=row.font_scale,
        bg_image=bg.get("bgImage") or "",
        bg_scale=float(bg.get("bgScale") or 1),
        bg_opacity=float(
            bg.get("bgOpacity") if bg.get("bgOpacity") is not None else 0.35
        ),
        bg_pan_x=float(bg.get("bgPanX") or 0),
        bg_pan_y=float(bg.get("bgPanY") or 0),
    )


async def update_settings(
    db: AsyncSession,
    row: UserSettings,
    body: SettingsPutIn,
) -> UserSettings:
    if body.theme is not None:
        row.theme = body.theme
    if body.font_scale is not None:
        row.font_scale = body.font_scale

    bg = dict(row.bg or DEFAULT_BG)
    if body.bg_image is not None:
        bg["bgImage"] = body.bg_image
    if body.bg_scale is not None:
        bg["bgScale"] = body.bg_scale
    if body.bg_opacity is not None:
        bg["bgOpacity"] = body.bg_opacity
    if body.bg_pan_x is not None:
        bg["bgPanX"] = body.bg_pan_x
    if body.bg_pan_y is not None:
        bg["bgPanY"] = body.bg_pan_y
    row.bg = bg

    await db.commit()
    await db.refresh(row)
    return row
