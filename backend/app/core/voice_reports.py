"""Persist / stale-mark voice-check reports on the project blob."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from app.core.chapter_digest import chapter_content_hash
from app.domain.types import VnProject

_MAX_PER_CHAPTER = 3


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _chapter_fp(project: VnProject, chapter_id: Optional[str]) -> str:
    if not chapter_id:
        # Whole-project fingerprint: join per-chapter hashes
        parts = [chapter_content_hash(ch) for ch in project.chapters]
        return "all:" + "|".join(parts)
    ch = next((c for c in project.chapters if c.id == chapter_id), None)
    if not ch:
        return f"missing:{chapter_id}"
    return chapter_content_hash(ch)


def mark_voice_reports_stale(project: VnProject) -> VnProject:
    """Flip stale=True when chapter fingerprint no longer matches."""
    reports = list(project.voiceReports or [])
    if not reports:
        return project
    changed = False
    out: List[Dict[str, Any]] = []
    for r in reports:
        if not isinstance(r, dict):
            continue
        cid = r.get("chapterId")
        cid_s = str(cid) if cid else None
        fp = _chapter_fp(project, cid_s)
        row = dict(r)
        if row.get("fingerprint") and row.get("fingerprint") != fp:
            if not row.get("stale"):
                changed = True
            row["stale"] = True
        out.append(row)
    if not changed and len(out) == len(reports):
        return project
    return project.model_copy(update={"voiceReports": out})


def persist_voice_report(
    project: VnProject,
    *,
    chapter_id: Optional[str],
    summary: str,
    issues: List[Dict[str, Any]],
    model: str,
) -> VnProject:
    """Append a fresh report; keep last N per chapter key."""
    fp = _chapter_fp(project, chapter_id)
    entry = {
        "chapterId": chapter_id,
        "fingerprint": fp,
        "summary": summary,
        "issues": issues,
        "model": model,
        "createdAt": _now_iso(),
        "stale": False,
    }
    key = chapter_id or "__all__"
    kept: List[Dict[str, Any]] = []
    same: List[Dict[str, Any]] = []
    for r in project.voiceReports or []:
        if not isinstance(r, dict):
            continue
        rk = r.get("chapterId") or "__all__"
        if rk == key:
            same.append(dict(r))
        else:
            kept.append(dict(r))
    same.append(entry)
    same = same[-_MAX_PER_CHAPTER:]
    return project.model_copy(update={"voiceReports": kept + same})
