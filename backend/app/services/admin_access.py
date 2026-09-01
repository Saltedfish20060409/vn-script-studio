"""Admin privilege: users.is_admin in DB; env / empty-admin bootstrap when none exist."""

from __future__ import annotations

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.models import User


async def count_db_admins(db: AsyncSession) -> int:
    return int(
        (
            await db.execute(
                select(func.count()).select_from(User).where(User.is_admin.is_(True))
            )
        ).scalar_one()
        or 0
    )


async def ensure_admin_access(
    user: User,
    settings: Settings,
    db: AsyncSession,
    *,
    persist_seed: bool = True,
) -> bool:
    """Return True if the user may use admin APIs.

    1. ``user.is_admin`` in DB.
    2. Bootstrap when DB has zero admins:
       - username listed in ``ADMIN_USERNAMES``, OR
       - ``ADMIN_USERNAMES`` is empty AND ``admin_bootstrap_empty`` is
         explicitly enabled (local/dev break-glass: first login wins).
       → optionally persist ``is_admin=True``.
    """
    if bool(getattr(user, "is_admin", False)):
        return True
    if await count_db_admins(db) > 0:
        return False
    seed_names = settings.admin_username_set
    if seed_names:
        allowed = user.username in seed_names
    else:
        # SECURITY: empty ADMIN_USERNAMES no longer auto-promotes the first
        # login unless explicitly enabled (prevents public-instance hijack).
        allowed = bool(settings.admin_bootstrap_empty)
    if not allowed:
        return False
    if persist_seed:
        user.is_admin = True
        await db.commit()
        await db.refresh(user)
    return True
