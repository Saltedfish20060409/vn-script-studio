"""Persistent async job store for long LLM runs (pipeline / chapter revise).

Jobs live in PostgreSQL (agent_jobs) so they survive restarts and are visible
across workers. The runner itself still executes in the current process; each
status update commits a fresh row write.
"""

from __future__ import annotations

import asyncio
import logging
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, Optional

from sqlalchemy.ext.asyncio import AsyncSession

JobRunner = Callable[["Job"], Awaitable[None]]

# (job) -> None — injected persistence hook; None = no-op (unit tests)
PersistFn = Callable[["Job"], Awaitable[None]]


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


@dataclass
class Job:
    id: str
    kind: str
    project_id: str
    user_id: str
    status: str = "queued"  # queued | running | done | error
    stage: str = ""
    progress: float = 0.0
    message: str = ""
    error: str = ""
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)
    _result: Optional[Dict[str, Any]] = field(default=None, repr=False)
    _persist: Optional[PersistFn] = field(default=None, repr=False)

    async def touch(
        self,
        *,
        status: Optional[str] = None,
        stage: Optional[str] = None,
        progress: Optional[float] = None,
        message: Optional[str] = None,
    ) -> None:
        if status is not None:
            self.status = status
        if stage is not None:
            self.stage = stage
        if progress is not None:
            self.progress = float(progress)
        if message is not None:
            self.message = message
        self.updated_at = _now()
        if self._persist is not None:
            await self._persist(self)

    async def set_result(self, value: Optional[Dict[str, Any]]) -> None:
        self._result = value
        self.updated_at = _now()
        if self._persist is not None:
            await self._persist(self)

    def to_dict(self, *, include_result: bool = True) -> Dict[str, Any]:
        out: Dict[str, Any] = {
            "id": self.id,
            "kind": self.kind,
            "projectId": self.project_id,
            "status": self.status,
            "stage": self.stage,
            "progress": self.progress,
            "message": self.message,
            "error": self.error,
            "createdAt": self.created_at,
            "updatedAt": self.updated_at,
        }
        if include_result and self._result is not None:
            out["result"] = self._result
        return out


def _job_from_row(row) -> Job:
    return Job(
        id=row.id,
        kind=row.kind or "",
        project_id=row.project_id,
        user_id=row.user_id,
        status=row.status or "queued",
        stage=row.stage or "",
        progress=float(row.progress or 0.0),
        message=row.message or "",
        error=row.error or "",
        created_at=row.created_at.isoformat() if row.created_at else _now(),
        updated_at=row.updated_at.isoformat() if row.updated_at else _now(),
        _result=dict(row.result) if isinstance(row.result, dict) else row.result,
    )


async def _persist_job(job: Job) -> None:
    """Write the current job state to PostgreSQL (fresh session per write)."""
    from app.db import AsyncSessionLocal
    from app.models.tables import AgentJob as AgentJobRow

    async with AsyncSessionLocal() as session:
        row = await session.get(AgentJobRow, job.id)
        if row is None:
            return
        row.status = job.status
        row.stage = job.stage
        row.progress = job.progress
        row.message = job.message
        row.error = job.error
        row.result = job._result
        row.updated_at = datetime.now(timezone.utc)
        await session.commit()


# Process-wide registry of background tasks so they are never GC'd mid-run and
# their exceptions are observed (avoids "Task was destroyed but it is pending!").
_background_tasks: "set[asyncio.Task]" = set()


def _spawn(coro, *, name: str) -> None:
    task = asyncio.create_task(coro, name=name)
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    task.add_done_callback(_log_task_exception)


def spawn_background_task(coro, *, name: str) -> None:
    """Schedule a fire-and-forget coroutine with a strong reference and
    exception logging. Safe to call from sync code (uses the running loop)."""
    _spawn(coro, name=name)


def _log_task_exception(task: asyncio.Task) -> None:
    if task.cancelled():
        return
    exc = task.exception()
    if exc is not None:
        logging.getLogger(__name__).error(
            "background task %s failed: %s", task.get_name(), exc
        )


async def create_job(
    db: AsyncSession,
    *,
    kind: str,
    project_id: str,
    user_id: str,
    runner: JobRunner,
) -> Job:
    """Insert a queued job row and start the runner in a background task."""
    from app.models.tables import AgentJob as AgentJobRow

    job_id = f"job_{uuid.uuid4().hex[:16]}"
    now = datetime.now(timezone.utc)
    db.add(
        AgentJobRow(
            id=job_id,
            kind=kind,
            project_id=project_id,
            user_id=user_id,
            status="queued",
            created_at=now,
            updated_at=now,
        )
    )
    await db.commit()

    job = Job(
        id=job_id,
        kind=kind,
        project_id=project_id,
        user_id=user_id,
        created_at=now.isoformat(),
        updated_at=now.isoformat(),
        _persist=_persist_job,
    )
    _spawn(_run(job, runner), name=f"job-{kind}-{job_id}")
    return job


async def get_job(db: AsyncSession, job_id: str) -> Optional[Job]:
    from app.models.tables import AgentJob as AgentJobRow

    row = await db.get(AgentJobRow, job_id)
    if row is None:
        return None
    job = _job_from_row(row)
    job._persist = _persist_job
    return job


async def _run(job: Job, runner: JobRunner) -> None:
    await job.touch(status="running", stage="start", progress=0.05, message="开始执行")
    try:
        await runner(job)
        if job.status != "error":
            await job.touch(status="done", progress=1.0, message=job.message or "完成")
    except Exception as exc:  # noqa: BLE001
        job.error = str(exc)[:800]
        await job.touch(status="error", message="失败", progress=job.progress)


async def reap_stale_jobs(db: AsyncSession, *, stale_seconds: int = 3600) -> int:
    """Mark 'running' jobs whose last update is older than `stale_seconds` as
    error('interrupted'). Runs at startup: jobs left in-flight by a process
    crash would otherwise stay 'running' forever."""
    from datetime import timedelta

    from sqlalchemy import update

    from app.models.tables import AgentJob as AgentJobRow

    cutoff = datetime.now(timezone.utc) - timedelta(seconds=stale_seconds)
    res = await db.execute(
        update(AgentJobRow)
        .where(
            AgentJobRow.status == "running",
            AgentJobRow.updated_at < cutoff,
        )
        .values(
            status="error",
            error="interrupted (process restarted)",
            updated_at=datetime.now(timezone.utc),
        )
    )
    await db.commit()
    return res.rowcount or 0
