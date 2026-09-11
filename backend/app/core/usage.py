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


# ---- 批量写入（写放大优化）----
# 每次 LLM 完成不再单独 INSERT + 开新 session；改为追加到内存队列，
# 由单个后台 flush 循环每 5 秒批量插入。quota 检查仍读 DB（准确优先）。
_usage_queue: list[dict] = []
_usage_flush_task: "asyncio.Task | None" = None
_FLUSH_INTERVAL = 5.0
_FLUSH_BATCH = 200


def _ensure_flush_loop() -> None:
    global _usage_flush_task
    if _usage_flush_task is None or _usage_flush_task.done():
        try:
            _usage_flush_task = asyncio.get_running_loop().create_task(_flush_loop())
        except RuntimeError:
            # no running loop yet (e.g. sync startup) — queue stays until first loop
            return


async def _flush_loop() -> None:
    while True:
        try:
            await asyncio.sleep(_FLUSH_INTERVAL)
            await _flush_queue()
        except asyncio.CancelledError:
            raise
        except Exception:  # noqa: BLE001 - flushing must never kill the loop
            logger.warning("usage flush failed (ignored)", exc_info=True)


async def _flush_queue() -> int:
    """Batch-insert everything queued. Returns rows written."""
    global _usage_queue
    if not _usage_queue:
        return 0
    batch = _usage_queue[:_FLUSH_BATCH]
    rest = _usage_queue[_FLUSH_BATCH:]
    try:
        from uuid import uuid4

        from app.db import AsyncSessionLocal
        from app.models.tables import LlmUsage

        async with AsyncSessionLocal() as session:
            for u in batch:
                session.add(
                    LlmUsage(
                        id=str(uuid4()),
                        user_id=u["user_id"],
                        project_id=u.get("project_id"),
                        kind=u.get("kind") or "llm",
                        model=u.get("model") or "",
                        prompt_tokens=max(0, int(u.get("prompt_tokens") or 0)),
                        completion_tokens=max(0, int(u.get("completion_tokens") or 0)),
                        total_tokens=max(0, int(u.get("total_tokens") or 0)),
                        created_at=datetime.now(timezone.utc),
                    )
                )
            await session.commit()
        # only drop what actually committed
        _usage_queue = rest
        return len(batch)
    except Exception:  # noqa: BLE001 - accounting is best-effort
        logger.warning("usage batch write failed (kept in queue)", exc_info=True)
        return 0


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
    """Queue a usage write (batched flush). No per-call session/INSERT."""
    if not user_id or not usage:
        return
    total = int(usage.get("total") or 0)
    if total <= 0:
        return
    _usage_queue.append(
        {
            "user_id": user_id,
            "kind": kind,
            "model": model or "",
            "prompt_tokens": int(usage.get("prompt") or 0),
            "completion_tokens": int(usage.get("completion") or 0),
            "total_tokens": total,
            "project_id": project_id,
        }
    )
    _ensure_flush_loop()


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
    from datetime import datetime as _dt
    from datetime import time as _time

    start = _dt.combine(_dt.now(timezone.utc).date(), _time.min, tzinfo=timezone.utc)
    return await user_usage_totals(db, user_id, since=start)


def effective_daily_cap(settings, creds: Optional[Dict[str, Any]] = None) -> int:
    """Token cap for this request.

    BYOK (client/user key): ``llm_daily_token_cap`` (default 0 = unlimited).
    Shared server key: ``llm_shared_key_daily_cap`` (default 200k) so a
    public instance cannot be drained if an operator later sets DEEPSEEK_API_KEY.
    """
    user_cap = int(getattr(settings, "llm_daily_token_cap", 0) or 0)
    source = str((creds or {}).get("source") or "")
    if source == "server":
        shared = int(getattr(settings, "llm_shared_key_daily_cap", 0) or 0)
        if shared > 0:
            return shared if user_cap <= 0 else min(user_cap, shared)
    return user_cap


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


async def quota_exceeded_for(
    db,
    user_id: str,
    settings,
    creds: Optional[Dict[str, Any]] = None,
) -> bool:
    return await quota_exceeded(db, user_id, effective_daily_cap(settings, creds))


async def ensure_under_quota(
    db,
    user_id: str,
    settings,
    creds: Optional[Dict[str, Any]] = None,
) -> None:
    """Raise 429 when this request's effective daily cap is already spent.

    提示要能让用户知道"接下来能做什么"：走站内免费额度时说明额度用完了、
    以及填自己的 Key 可以立刻继续（roadmap 方向 G）。
    """
    if await quota_exceeded_for(db, user_id, settings, creds):
        from fastapi import HTTPException

        source = str((creds or {}).get("source") or "")
        if source == "server":
            detail = (
                "站内免费体验额度今天的份用完了（每天有上限，高峰期还可能限流）。"
                "想现在继续写：在「设置 → 模型」填入你自己的 API Key（DeepSeek / 智谱 / "
                "通义 等都能用，用量走你自己的账户）；或者明天再来。"
            )
        else:
            detail = (
                "今天的用量已达上限（这是你自己账户的每日上限）。"
                "可在配置里调高或明天继续。"
            )
        raise HTTPException(status_code=429, detail=detail)
