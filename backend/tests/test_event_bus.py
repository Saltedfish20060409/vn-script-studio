"""Unit tests: collab event bus (in-process fallback path, no Redis needed)."""

from __future__ import annotations

import asyncio

import pytest

from app.services import event_bus


def _run(coro):
    return asyncio.run(coro)


def test_event_bus_local_delivery():
    async def _scenario():
        # No REDIS_URL configured in tests → pure in-process path.
        q = event_bus.subscribe("proj-x")
        try:
            event_bus.member_event("proj-x", "added", {"userId": "u1", "role": "editor"})
            evt = await asyncio.wait_for(q.get(), timeout=1)
            assert evt["type"] == "member"
            assert evt["kind"] == "added"
            assert evt["userId"] == "u1"

            event_bus.lock_event("proj-x", "acquired", {"chapterId": "ch1", "userId": "u1"})
            evt = await asyncio.wait_for(q.get(), timeout=1)
            assert evt["type"] == "lock"
            assert evt["chapterId"] == "ch1"

            event_bus.comment_event("proj-x", "added", {"id": "c1", "text": "hi"})
            evt = await asyncio.wait_for(q.get(), timeout=1)
            assert evt["type"] == "comment"
            assert evt["id"] == "c1"
        finally:
            event_bus.unsubscribe("proj-x", q)

    _run(_scenario())


def test_event_bus_isolates_projects():
    async def _scenario():
        qa = event_bus.subscribe("proj-a")
        qb = event_bus.subscribe("proj-b")
        try:
            event_bus.member_event("proj-a", "added", {"userId": "u1"})
            # proj-b subscriber must NOT receive proj-a events.
            with pytest.raises(asyncio.TimeoutError):
                await asyncio.wait_for(qb.get(), timeout=0.15)
            evt = await asyncio.wait_for(qa.get(), timeout=1)
            assert evt["type"] == "member"
        finally:
            event_bus.unsubscribe("proj-a", qa)
            event_bus.unsubscribe("proj-b", qb)

    _run(_scenario())
