"""Persistence helpers for project snapshots (stored outside the project blob)."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.project import uid
from app.core.snapshots import (
    content_hash_for_payload,
    snapshot_payload_dict,
)
from app.domain.types import VnProject
from app.models.tables import ProjectSnapshotRow

_MAX_PER_PROJECT = 20


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def list_snapshots(db: AsyncSession, project_id: str) -> List[Dict[str, Any]]:
    res = await db.execute(
        select(ProjectSnapshotRow)
        .where(ProjectSnapshotRow.project_id == project_id)
        .order_by(ProjectSnapshotRow.created_at.desc())
    )
    rows = list(res.scalars().all())
    return [
        {"id": r.id, "label": r.label, "createdAt": r.created_at.isoformat() if r.created_at else None}
        for r in rows
    ]


async def latest_content_hash_for(db: AsyncSession, project_id: str) -> Optional[str]:
    res = await db.execute(
        select(ProjectSnapshotRow.content_hash)
        .where(ProjectSnapshotRow.project_id == project_id)
        .order_by(ProjectSnapshotRow.created_at.desc())
        .limit(1)
    )
    return res.scalar_one_or_none()


async def create_snapshot(
    db: AsyncSession,
    project_id: str,
    vn: VnProject,
    *,
    label: str,
) -> Dict[str, Any]:
    payload = snapshot_payload_dict(vn)
    content_hash = content_hash_for_payload(payload)
    prev_hash = await latest_content_hash_for(db, project_id)
    if prev_hash and prev_hash == content_hash:
        res = await db.execute(
            select(ProjectSnapshotRow)
            .where(
                ProjectSnapshotRow.project_id == project_id,
                ProjectSnapshotRow.content_hash == content_hash,
            )
            .order_by(ProjectSnapshotRow.created_at.desc())
            .limit(1)
        )
        last = res.scalar_one_or_none()
        if last is not None:
            return {
                "id": last.id,
                "label": last.label,
                "createdAt": last.created_at.isoformat() if last.created_at else None,
                "contentHash": content_hash,
                "deduped": True,
            }
    row = ProjectSnapshotRow(
        id=uid("snap"),
        project_id=project_id,
        label=label or "",
        content_hash=content_hash,
        payload=payload,
        created_at=_now(),
    )
    db.add(row)
    await db.flush()

    # Keep only the most recent N per project.
    res = await db.execute(
        select(ProjectSnapshotRow.id)
        .where(ProjectSnapshotRow.project_id == project_id)
        .order_by(ProjectSnapshotRow.created_at.desc())
        .offset(_MAX_PER_PROJECT)
    )
    stale_ids = [r for r in res.scalars().all()]
    if stale_ids:
        await db.execute(
            delete(ProjectSnapshotRow).where(ProjectSnapshotRow.id.in_(stale_ids))
        )
    return {
        "id": row.id,
        "label": row.label,
        "createdAt": row.created_at.isoformat() if row.created_at else None,
        "contentHash": content_hash,
        "deduped": False,
    }


async def get_snapshot_payload(
    db: AsyncSession, project_id: str, snap_id: str
) -> Optional[Dict[str, Any]]:
    res = await db.execute(
        select(ProjectSnapshotRow).where(
            ProjectSnapshotRow.project_id == project_id,
            ProjectSnapshotRow.id == snap_id,
        )
    )
    row = res.scalar_one_or_none()
    if row is None:
        return None
    payload = row.payload
    return dict(payload) if isinstance(payload, dict) else payload


async def delete_snapshot(
    db: AsyncSession, project_id: str, snap_id: str
) -> bool:
    res = await db.execute(
        delete(ProjectSnapshotRow).where(
            ProjectSnapshotRow.project_id == project_id,
            ProjectSnapshotRow.id == snap_id,
        )
    )
    return (res.rowcount or 0) > 0
