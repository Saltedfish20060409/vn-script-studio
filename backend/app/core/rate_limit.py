"""Rate limiting for auth and write-heavy endpoints.

Per-key sliding-window counters. Uses Redis when ``REDIS_URL`` is set so
limits hold across uvicorn workers; otherwise in-process (single worker).
"""

from __future__ import annotations

import logging
import time
from collections import defaultdict, deque
from typing import Any, Deque, Dict, Optional

logger = logging.getLogger(__name__)

_hits: Dict[str, Deque[float]] = defaultdict(deque)
_WINDOW = 60.0
_redis: Any = None
_redis_failed = False


def _key(ip: Optional[str], kind: str) -> str:
    return f"{kind}:{ip or 'unknown'}"


def _redis_client() -> Any:
    """Lazy sync Redis client, or None when not configured/usable."""
    global _redis, _redis_failed
    if _redis is not None or _redis_failed:
        return _redis
    try:
        from app.config import get_settings

        url = (get_settings().redis_url or "").strip()
        if not url:
            _redis_failed = True
            return None
        import redis

        _redis = redis.Redis.from_url(url, decode_responses=True, socket_timeout=0.4)
        _redis.ping()
    except Exception as exc:  # noqa: BLE001
        logger.warning("rate-limit redis disabled: %s", exc)
        _redis_failed = True
        _redis = None
    return _redis


def check_rate(
    ip: Optional[str],
    kind: str,
    limit: int,
    *,
    enabled: bool = True,
    window: float = _WINDOW,
) -> bool:
    """Return True when the request is allowed (under the limit)."""
    if not enabled:
        return True
    if limit <= 0:
        return True
    key = _key(ip, kind)
    ttl = max(1, int(window))
    client = _redis_client()
    if client is not None:
        try:
            rkey = f"vnss:rl:{key}"
            n = int(client.incr(rkey))
            if n == 1:
                client.expire(rkey, ttl)
            return n <= limit
        except Exception as exc:  # noqa: BLE001
            logger.debug("rate-limit redis fallback: %s", exc)

    now = time.monotonic()
    q = _hits[key]
    while q and q[0] < now - window:
        q.popleft()
    if len(q) >= limit:
        return False
    q.append(now)
    if len(_hits) > 10_000:
        for k in [k for k, v in _hits.items() if not v or v[-1] < now - window * 2]:
            _hits.pop(k, None)
    return True


def require_rate(
    key: Optional[str],
    kind: str,
    limit: int,
    *,
    enabled: bool = True,
    window: float = _WINDOW,
    detail: str = "操作过于频繁，请稍后再试",
) -> None:
    """Raise HTTP 429 when ``check_rate`` is exhausted."""
    if check_rate(key, kind, limit, enabled=enabled, window=window):
        return
    from fastapi import HTTPException

    raise HTTPException(status_code=429, detail=detail)
