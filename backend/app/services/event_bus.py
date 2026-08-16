"""Cross-worker collaboration event bus.

Single worker: in-process subscriber queues (zero dependencies, current default).

Multi worker: when ``REDIS_URL`` is configured and reachable, every
``broadcast`` is also published to a Redis channel (``vnss:collab:{project}``)
and a background task subscribes to all such channels, re-broadcasting remote
events into the local queues. This gives live lock / member / comment events
across uvicorn workers.

The Redis layer degrades gracefully: if the URL is missing, connection fails,
or pub/sub is unavailable, the in-process bus keeps working (the app just
falls back to single-worker semantics). Never raises into callers.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any, Dict, Optional, Set

logger = logging.getLogger(__name__)

_subscribers: Dict[str, Set[asyncio.Queue]] = {}

_redis_pub: Any = None  # lazily-created async Redis client
_redis_sub: Any = None
_redis_task: Optional[asyncio.Task] = None
_redis_failed = False


def _channel(project_id: str) -> str:
    return f"vnss:collab:{project_id}"


def _maybe_init_redis() -> Any:
    """Return the async Redis pub client, or None when not configured/usable."""
    global _redis_pub, _redis_failed
    if _redis_pub is not None or _redis_failed:
        return _redis_pub
    from app.config import get_settings

    url = (get_settings().redis_url or "").strip()
    if not url:
        _redis_failed = True
        return None
    try:
        from redis.asyncio import Redis

        _redis_pub = Redis.from_url(url, decode_responses=True)
    except Exception as exc:  # noqa: BLE001
        logger.warning("redis disabled (import/connect failed): %s", exc)
        _redis_failed = True
        _redis_pub = None
    return _redis_pub


def _start_redis_listener() -> None:
    """Background task: forward remote pub/sub events into local queues."""
    global _redis_task, _redis_sub
    client = _maybe_init_redis()
    if client is None or _redis_task is not None:
        return
    try:
        from redis.asyncio import Redis

        _redis_sub = Redis.from_url(
            (__import__("app.config", fromlist=["get_settings"]).get_settings().redis_url),
            decode_responses=True,
        )
    except Exception as exc:  # noqa: BLE001
        logger.warning("redis listener disabled: %s", exc)
        _redis_failed = True
        return

    async def _listen() -> None:
        try:
            async with _redis_sub.pubsub() as ps:
                await ps.psubscribe("vnss:collab:*")
                async for message in ps.listen():
                    if message.get("type") != "pmessage":
                        continue
                    data = message.get("data")
                    if not isinstance(data, str):
                        continue
                    import json

                    try:
                        payload = json.loads(data)
                    except json.JSONDecodeError:
                        continue
                    project_id = str(payload.get("projectId") or "")
                    if project_id:
                        broadcast_local(project_id, payload.get("event") or {})
        except asyncio.CancelledError:
            pass
        except Exception as exc:  # noqa: BLE001
            logger.warning("redis listener stopped: %s", exc)

    _redis_task = asyncio.create_task(_listen(), name="collab-redis-listener")


async def start_redis_bridge() -> None:
    """Call from app lifespan to enable cross-worker broadcasts."""
    if _maybe_init_redis() is not None:
        _start_redis_listener()


async def stop_redis_bridge() -> None:
    global _redis_task, _redis_pub, _redis_sub
    if _redis_task is not None:
        _redis_task.cancel()
        try:
            await _redis_task
        except (asyncio.CancelledError, Exception):  # noqa: BLE001
            pass
        _redis_task = None
    for client in (_redis_pub, _redis_sub):
        if client is not None:
            try:
                await client.aclose()
            except Exception:  # noqa: BLE001
                pass
    _redis_pub = None
    _redis_sub = None


def subscribe(project_id: str) -> asyncio.Queue:
    q: asyncio.Queue = asyncio.Queue(maxsize=200)
    _subscribers.setdefault(project_id, set()).add(q)
    return q


def unsubscribe(project_id: str, q: asyncio.Queue) -> None:
    subs = _subscribers.get(project_id)
    if subs:
        subs.discard(q)
        if not subs:
            _subscribers.pop(project_id, None)


def broadcast_local(project_id: str, event: Dict[str, Any]) -> None:
    subs = _subscribers.get(project_id)
    if not subs:
        return
    for q in list(subs):
        try:
            q.put_nowait(event)
        except asyncio.QueueFull:
            pass  # slow subscriber — drop event


def broadcast(project_id: str, event: Dict[str, Any]) -> None:
    """Deliver to local queues, and to other workers via Redis when enabled."""
    broadcast_local(project_id, event)
    client = _maybe_init_redis()
    if client is None:
        return
    import json

    from app.core.jobs import spawn_background_task

    try:
        spawn_background_task(
            client.publish(_channel(project_id), json.dumps({
                "projectId": project_id,
                "event": event,
            })),
            name="collab-redis-publish",
        )
    except Exception as exc:  # noqa: BLE001
        logger.debug("redis publish skipped: %s", exc)


def member_event(project_id: str, kind: str, payload: Dict[str, Any]) -> None:
    broadcast(project_id, {"type": "member", "kind": kind, **payload})


def lock_event(project_id: str, kind: str, payload: Dict[str, Any]) -> None:
    broadcast(project_id, {"type": "lock", "kind": kind, **payload})


def comment_event(project_id: str, kind: str, payload: Dict[str, Any]) -> None:
    broadcast(project_id, {"type": "comment", "kind": kind, **payload})
