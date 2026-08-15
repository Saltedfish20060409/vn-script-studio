"""In-process async job store for long LLM runs (pipeline / chapter revise)."""
from __future__ import annotations

import asyncio
import uuid
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Dict, List, Optional

JobRunner = Callable[["Job"], Awaitable[None]]


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
    result: Optional[Dict[str, Any]] = None
    error: Optional[str] = None
    created_at: str = field(default_factory=_now)
    updated_at: str = field(default_factory=_now)

    def touch(
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
        if include_result and self.result is not None:
            out["result"] = self.result
        return out


class JobStore:
    """Process-local job registry. Survives within one API worker process."""

    def __init__(self, *, max_jobs: int = 200) -> None:
        self._jobs: Dict[str, Job] = {}
        self._lock = asyncio.Lock()
        self._max = max_jobs

    async def create(
        self,
        *,
        kind: str,
        project_id: str,
        user_id: str,
        runner: JobRunner,
    ) -> Job:
        job = Job(
            id=f"job_{uuid.uuid4().hex[:16]}",
            kind=kind,
            project_id=project_id,
            user_id=user_id,
        )
        async with self._lock:
            self._jobs[job.id] = job
            self._trim_locked()
        asyncio.create_task(self._run(job, runner))
        return job

    async def get(self, job_id: str) -> Optional[Job]:
        return self._jobs.get(job_id)

    def _trim_locked(self) -> None:
        if len(self._jobs) <= self._max:
            return
        # Drop oldest finished jobs first
        finished = sorted(
            (
                j
                for j in self._jobs.values()
                if j.status in ("done", "error")
            ),
            key=lambda j: j.updated_at,
        )
        for j in finished:
            if len(self._jobs) <= self._max:
                break
            self._jobs.pop(j.id, None)

    async def _run(self, job: Job, runner: JobRunner) -> None:
        job.touch(status="running", stage="start", progress=0.05, message="开始执行")
        try:
            await runner(job)
            if job.status != "error":
                job.touch(status="done", progress=1.0, message=job.message or "完成")
        except Exception as exc:  # noqa: BLE001
            job.error = str(exc)[:800]
            job.touch(status="error", message="失败", progress=job.progress)


_STORE: Optional[JobStore] = None


def get_job_store() -> JobStore:
    global _STORE
    if _STORE is None:
        _STORE = JobStore()
    return _STORE
