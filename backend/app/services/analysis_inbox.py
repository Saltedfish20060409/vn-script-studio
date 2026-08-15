"""Persistence helpers for analysis_inbox_items sidecar."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Sequence, Set

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.fact_extract import FactCandidate, candidate_to_dict
from app.models.tables import AnalysisInboxItem


def _now() -> datetime:
    return datetime.now(timezone.utc)


async def list_inbox(
    db: AsyncSession,
    project_id: str,
    *,
    status: str = "pending",
    kinds: Optional[Sequence[str]] = None,
) -> List[AnalysisInboxItem]:
    q = select(AnalysisInboxItem).where(
        AnalysisInboxItem.project_id == project_id,
        AnalysisInboxItem.status == status,
    )
    if kinds:
        q = q.where(AnalysisInboxItem.kind.in_(list(kinds)))
    q = q.order_by(AnalysisInboxItem.created_at.desc())
    res = await db.execute(q)
    return list(res.scalars().all())


async def pending_dedupe_keys(db: AsyncSession, project_id: str) -> Set[str]:
    rows = await list_inbox(db, project_id, status="pending")
    return {r.dedupe_key for r in rows if r.dedupe_key}


async def blocked_dedupe_keys(db: AsyncSession, project_id: str) -> Set[str]:
    """Pending + rejected keys — rejected stays blocked until fingerprint-level rework."""
    keys: Set[str] = set()
    for status in ("pending", "rejected"):
        rows = await list_inbox(db, project_id, status=status)
        keys |= {r.dedupe_key for r in rows if r.dedupe_key}
    return keys


async def insert_candidates(
    db: AsyncSession,
    project_id: str,
    candidates: Sequence[FactCandidate],
) -> List[AnalysisInboxItem]:
    blocked = await blocked_dedupe_keys(db, project_id)
    created: List[AnalysisInboxItem] = []
    for c in candidates:
        if c.kind == "source_snippet":
            continue
        if c.dedupe_key in blocked:
            continue
        row = AnalysisInboxItem(
            project_id=project_id,
            kind=c.kind,
            payload=dict(c.payload),
            evidence=list(c.evidence),
            status="pending",
            dedupe_key=c.dedupe_key,
        )
        db.add(row)
        created.append(row)
        blocked.add(c.dedupe_key)
    if created:
        await db.flush()
    return created


async def insert_source_snippet(
    db: AsyncSession, project_id: str, text: str, *, source: str = "paste"
) -> AnalysisInboxItem:
    import hashlib

    digest = hashlib.sha256((text or "").encode("utf-8")).hexdigest()[:16]
    row = AnalysisInboxItem(
        project_id=project_id,
        kind="source_snippet",
        payload={"text": text, "source": source},
        evidence=[{"source": source, "quote": (text or "")[:200]}],
        status="pending",
        dedupe_key=f"snippet:{source}:{digest}",
    )
    db.add(row)
    await db.flush()
    return row


async def get_inbox_items(
    db: AsyncSession, project_id: str, ids: Sequence[str]
) -> List[AnalysisInboxItem]:
    if not ids:
        return []
    res = await db.execute(
        select(AnalysisInboxItem).where(
            AnalysisInboxItem.project_id == project_id,
            AnalysisInboxItem.id.in_(list(ids)),
        )
    )
    return list(res.scalars().all())


async def set_status(
    db: AsyncSession, rows: Sequence[AnalysisInboxItem], status: str
) -> None:
    for r in rows:
        r.status = status
        r.updated_at = _now()
    await db.flush()


def inbox_row_to_dict(row: AnalysisInboxItem) -> Dict[str, Any]:
    return {
        "id": row.id,
        "kind": row.kind,
        "payload": row.payload or {},
        "evidence": row.evidence or [],
        "status": row.status,
        "dedupeKey": row.dedupe_key,
        "createdAt": row.created_at.isoformat() if row.created_at else None,
    }


def proposals_from_agent(raw: Sequence[Dict[str, Any]]) -> List[FactCandidate]:
    """Normalize agent propose_* side effects into FactCandidate list."""
    out: List[FactCandidate] = []
    for item in raw:
        kind = item.get("kind")
        payload = item.get("payload") or {}
        evidence = item.get("evidence") or []
        dedupe = item.get("dedupe_key") or item.get("dedupeKey") or ""
        if not kind or not dedupe:
            continue
        out.append(
            FactCandidate(
                kind=kind,
                payload=payload,
                evidence=list(evidence),
                dedupe_key=dedupe,
            )
        )
    return out


def summarize_candidates(cands: Sequence[FactCandidate]) -> Dict[str, Any]:
    return {
        "added": len(cands),
        "characterLinks": sum(1 for c in cands if c.kind == "character_link"),
        "timelineEvents": sum(1 for c in cands if c.kind == "timeline_event"),
        "items": [candidate_to_dict(c) for c in cands],
    }
