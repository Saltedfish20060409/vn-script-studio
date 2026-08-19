from __future__ import annotations

from typing import Optional

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy.orm.attributes import flag_modified

from app.config import Settings, get_settings
from app.llm_models import DEFAULT_LLM_MODEL
from app.models import UserSettings
from app.schemas import SettingsOut, SettingsPutIn
from app.security import decrypt_secret, encrypt_secret, mask_api_key

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
    settings = get_settings()
    api_key = decrypt_secret(row.api_key_enc or "", settings)
    critic_key = decrypt_secret(row.critic_api_key_enc or "", settings)
    active_base_url = (
        row.api_base_url
        or settings.deepseek_base_url
        or "https://api.deepseek.com"
    )
    active_model = row.api_model or settings.deepseek_model or DEFAULT_LLM_MODEL
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
        has_api_key=bool(api_key),
        api_key_masked=mask_api_key(api_key),
        api_base_url=row.api_base_url or "",
        api_model=row.api_model or "",
        has_critic_api_key=bool(critic_key),
        critic_api_key_masked=mask_api_key(critic_key),
        critic_api_base_url=row.critic_api_base_url or "",
        critic_api_model=row.critic_api_model or "",
        active_model=active_model,
        active_base_url=active_base_url,
        credential_source="user" if api_key else "server",
    )


async def update_settings(
    db: AsyncSession,
    row: UserSettings,
    body: SettingsPutIn,
) -> UserSettings:
    settings = get_settings()
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

    # User-level LLM credentials: api_key="" clears, None keeps, value encrypts.
    if body.api_key is not None:
        row.api_key_enc = encrypt_secret(body.api_key.strip(), settings)
    if body.api_base_url is not None:
        row.api_base_url = body.api_base_url.strip()
    if body.api_model is not None:
        row.api_model = body.api_model.strip()
    if body.critic_api_key is not None:
        row.critic_api_key_enc = encrypt_secret(body.critic_api_key.strip(), settings)
    if body.critic_api_base_url is not None:
        row.critic_api_base_url = body.critic_api_base_url.strip()
    if body.critic_api_model is not None:
        row.critic_api_model = body.critic_api_model.strip()

    await db.commit()
    await db.refresh(row)
    return row


async def user_llm_credentials(
    db: AsyncSession,
    user_id: str,
    settings: Settings,
) -> Optional[dict]:
    """User-level LLM credentials (decrypted) or None when not configured."""
    result = await db.execute(
        select(UserSettings).where(UserSettings.user_id == user_id)
    )
    row = result.scalar_one_or_none()
    if row is None:
        return None
    api_key = decrypt_secret(row.api_key_enc or "", settings)
    if not api_key:
        return None
    critic_key = decrypt_secret(row.critic_api_key_enc or "", settings)
    return {
        "api_key": api_key,
        "base_url": row.api_base_url
        or settings.deepseek_base_url
        or "https://api.deepseek.com",
        "model": row.api_model or settings.deepseek_model or DEFAULT_LLM_MODEL,
        "provider": settings.llm_provider or "openai",
        "source": "user",
        "critic_api_key": critic_key,
        "critic_base_url": row.critic_api_base_url or "",
        "critic_model": row.critic_api_model or "",
    }
