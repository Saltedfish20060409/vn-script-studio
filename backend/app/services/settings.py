from __future__ import annotations

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.models import UserSettings
from app.schemas import SettingsOut, SettingsPutIn

DEFAULT_BG = {
    "bgImage": "",
    "bgScale": 1.0,
    "bgOpacity": 0.35,
    "bgPanX": 0.0,
    "bgPanY": 0.0,
    "panelGlass": "auto",
    "bgScrim": 0.42,
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
    glass = bg.get("panelGlass") or "auto"
    if glass not in ("auto", "mist", "ink"):
        glass = "auto"
    scrim = bg.get("bgScrim")
    try:
        scrim_f = float(0.42 if scrim is None else scrim)
    except (TypeError, ValueError):
        scrim_f = 0.42
    scrim_f = max(0.0, min(0.85, scrim_f))
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
        panel_glass=str(glass),
        bg_scrim=scrim_f,
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

    # Fresh dict + flag_modified so JSONB nested key updates actually persist
    bg = {**DEFAULT_BG, **(row.bg or {})}
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
    if body.panel_glass is not None:
        g = body.panel_glass.strip().lower()
        bg["panelGlass"] = g if g in ("auto", "mist", "ink") else "auto"
    if body.bg_scrim is not None:
        bg["bgScrim"] = max(0.0, min(0.85, float(body.bg_scrim)))
    row.bg = bg
    flag_modified(row, "bg")

    await db.commit()
    await db.refresh(row)
    return row
