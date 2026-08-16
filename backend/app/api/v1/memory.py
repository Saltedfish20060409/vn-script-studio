"""Chapter long-memory APIs (NovelMaster-style, PostgreSQL sliced storage)."""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.novel_memory import DEFAULT_SPAN
from app.db import get_db
from app.models import User
from app.security import get_current_user
from app.services.novel_memory import (
    archive_project_memory,
    get_archive_detail,
    get_latest_continuity,
    list_memory_archives,
)
from app.services.projects import get_owned_project, row_to_vn

router = APIRouter(prefix="/projects", tags=["memory"])


class MemoryArchiveIn(BaseModel):
    span: int = Field(default=DEFAULT_SPAN, ge=1, le=50)
    include_incomplete: bool = False


@router.post("/{project_id}/memory/archive")
async def memory_archive(
    project_id: str,
    body: MemoryArchiveIn = MemoryArchiveIn(),
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await get_owned_project(db, user, project_id)
    vn = row_to_vn(row)
    result = await archive_project_memory(
        db,
        project_id,
        vn,
        span=body.span,
        include_incomplete=body.include_incomplete,
    )
    return result


@router.get("/{project_id}/memory/archives")
async def memory_list(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_owned_project(db, user, project_id)
    return {"archives": await list_memory_archives(db, project_id)}


@router.get("/{project_id}/memory/latest")
async def memory_latest(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_owned_project(db, user, project_id)
    latest = await get_latest_continuity(db, project_id)
    if not latest:
        return {"latest": None}
    return {"latest": latest}


@router.get("/{project_id}/memory/archives/{archive_id}")
async def memory_detail(
    project_id: str,
    archive_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_owned_project(db, user, project_id)
    detail = await get_archive_detail(db, project_id, archive_id)
    if not detail:
        raise HTTPException(status_code=404, detail="记忆归档不存在")
    return detail
