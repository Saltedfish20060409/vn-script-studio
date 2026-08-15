"""P0: in-process async jobs."""
from __future__ import annotations

import asyncio

from app.core.jobs import Job, get_job_store


def test_job_store_runs_and_finishes():
    store = get_job_store()

    async def _runner(job: Job):
        job.touch(stage="work", progress=0.5, message="halfway")
        await asyncio.sleep(0.05)
        job.result = {"ok": True}
        job.touch(stage="done", progress=0.9, message="almost")

    async def _run():
        job = await store.create(
            kind="test",
            project_id="p1",
            user_id="u1",
            runner=_runner,
        )
        for _ in range(40):
            cur = await store.get(job.id)
            assert cur is not None
            if cur.status in ("done", "error"):
                return cur
            await asyncio.sleep(0.05)
        raise AssertionError("job did not finish")

    done = asyncio.run(_run())
    assert done.status == "done"
    assert done.result == {"ok": True}
    assert done.to_dict()["id"] == done.id


def test_job_store_captures_error():
    store = get_job_store()

    async def _boom(_job: Job):
        raise RuntimeError("boom")

    async def _run():
        job = await store.create(
            kind="test",
            project_id="p1",
            user_id="u1",
            runner=_boom,
        )
        for _ in range(40):
            cur = await store.get(job.id)
            assert cur is not None
            if cur.status in ("done", "error"):
                return cur
            await asyncio.sleep(0.05)
        raise AssertionError("job did not finish")

    done = asyncio.run(_run())
    assert done.status == "error"
    assert "boom" in (done.error or "")
