"""Job model + runner lifecycle (unit level, no DB)."""
from __future__ import annotations

import asyncio

from app.core.jobs import Job, _run


def _noop_job() -> Job:
    return Job(id="job_unit1", kind="test", project_id="p1", user_id="u1")


def test_job_touch_updates_fields():
    async def main():
        job = _noop_job()
        await job.touch(stage="work", progress=0.5, message="halfway")
        assert job.status == "queued"
        assert job.stage == "work"
        assert job.progress == 0.5
        assert job.message == "halfway"
        await job.touch(status="running")
        assert job.status == "running"
        return job

    job = asyncio.run(main())
    d = job.to_dict()
    assert d["id"] == job.id
    assert d["stage"] == "work"
    assert d["progress"] == 0.5


def test_job_set_result_and_to_dict():
    async def main():
        job = _noop_job()
        await job.set_result({"ok": True})
        return job

    job = asyncio.run(main())
    assert job.to_dict(include_result=True)["result"] == {"ok": True}
    assert "result" not in job.to_dict(include_result=False)


def test_runner_finishes_done():
    async def _runner(job: Job):
        await job.touch(stage="work", progress=0.5, message="halfway")
        await asyncio.sleep(0.01)
        await job.set_result({"ok": True})
        await job.touch(stage="done", progress=0.9, message="almost")

    async def main():
        job = _noop_job()
        await _run(job, _runner)
        return job

    done = asyncio.run(main())
    assert done.status == "done"
    assert done.progress == 1.0
    assert done._result == {"ok": True}


def test_runner_captures_error():
    async def _boom(_job: Job):
        raise RuntimeError("boom")

    async def main():
        job = _noop_job()
        await _run(job, _boom)
        return job

    done = asyncio.run(main())
    assert done.status == "error"
    assert "boom" in (done.error or "")
