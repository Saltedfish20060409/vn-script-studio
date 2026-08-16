"""Per-user LLM usage accounting + soft daily quota.

A request-scoped ContextVar carries the current user id; llm_http records each
successful completion fire-and-forget. Background tasks (pipeline / revise)
inherit the context via asyncio.create_task, so their LLM calls are counted too.
"""

from __future__ import annotations

import asyncio
import logging
from contextvars import ContextVar
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from sqlalchemy import func, select

logger = logging.getLogger(__name__)

_usage_user: ContextVar[Optional[str]] = ContextVar("usage_user", default=None)


def set_usage_user(user_id: Optional[str]) -> None:
    _usage_user.set(user_id)


def current_usage_user() -> Optional[str]:
    return _usage_user.get()


async def record_usage(
    *,
    user_id: str,
    kind: str = "llm",
    model: str = "",
    prompt_tokens: int = 0,
    completion_tokens: int = 0,
    total_tokens: int = 0,
    project_id: Optional[str] = None,
) -> None:
    """Append one usage row. Never raises — accounting must not break requests."""
    try:
        from uuid import uuid4

        from app.db import AsyncSessionLocal
        from app.models.tables import LlmUsage

        async with AsyncSessionLocal() as session:
            session.add(
                LlmUsage(
                    id=str(uuid4()),
                    user_id=user_id,
                    project_id=project_id,
                    kind=kind,
                    model=model or "",
                    prompt_tokens=max(0, int(prompt_tokens)),
                    completion_tokens=max(0, int(completion_tokens)),
                    total_tokens=max(0, int(total_tokens)),
                    created_at=datetime.now(timezone.utc),
                )
            )
            await session.commit()
    except Exception:  # noqa: BLE001 - accounting is best-effort
        logger.warning("usage record failed (ignored)", exc_info=True)


def record_usage_later(
    *,
    user_id: str,
    kind: str = "llm",
    model: str = "",
    usage: Optional[Dict[str, int]],
    project_id: Optional[str] = None,
) -> None:
    """Fire-and-forget usage write from a sync call site."""
    if not user_id or not usage:
        return
    total = int(usage.get("total") or 0)
    if total <= 0:
        return
    from app.core.jobs import spawn_background_task

    spawn_background_task(
        record_usage(
            user_id=user_id,
            kind=kind,
            model=model,
            prompt_tokens=int(usage.get("prompt") or 0),
            completion_tokens=int(usage.get("completion") or 0),
            total_tokens=total,
            project_id=project_id,
        ),
        name="usage-record",
    )


async def user_usage_totals(
    db,
    user_id: str,
    *,
    since: Optional[datetime] = None,
) -> Dict[str, Any]:
    """Aggregate prompt/completion/total tokens for one user (optional time window)."""
    from app.models.tables import LlmUsage

    q = select(
        func.coalesce(func.sum(LlmUsage.prompt_tokens), 0),
        func.coalesce(func.sum(LlmUsage.completion_tokens), 0),
        func.coalesce(func.sum(LlmUsage.total_tokens), 0),
        func.count(LlmUsage.id),
    ).where(LlmUsage.user_id == user_id)
    if since is not None:
        q = q.where(LlmUsage.created_at >= since)
    row = (await db.execute(q)).one()
    return {
        "promptTokens": int(row[0] or 0),
        "completionTokens": int(row[1] or 0),
        "totalTokens": int(row[2] or 0),
        "calls": int(row[3] or 0),
    }


async def today_usage(db, user_id: str) -> Dict[str, Any]:
    from datetime import datetime as _dt, time as _time

    start = _dt.combine(_dt.now(timezone.utc).date(), _time.min, tzinfo=timezone.utc)
    return await user_usage_totals(db, user_id, since=start)


async def quota_exceeded(
    db,
    user_id: str,
    daily_cap: int,
) -> bool:
    """True when the user already consumed >= daily token cap today."""
    if not daily_cap or daily_cap <= 0:
        return False
    used = await today_usage(db, user_id)
    return int(used["totalTokens"]) >= int(daily_cap)
