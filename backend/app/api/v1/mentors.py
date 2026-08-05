"""Writing mentor packs API — list / select / import."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.core.mentors import (
    default_active_ids,
    get_builtin,
    list_builtin_meta,
    match_mentor_ids_from_text,
    parse_mentor_markdown,
    resolve_project_mentors,
)
from app.core.project import touch_project
from app.db import get_db
from app.models import User
from app.security import get_current_user
from app.services.projects import get_owned_project, row_to_vn, sync_row_from_vn

router = APIRouter(tags=["mentors"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _mentor_state(vn) -> Dict[str, Any]:
    raw = vn.writingMentors if isinstance(getattr(vn, "writingMentors", None), dict) else {}
    active = raw.get("activeIds")
    if not isinstance(active, list) or not active:
        active = default_active_ids()
    # migrate legacy dual-pack choices → unified editor
    legacy = {"ln-vn-stagecraft", "ln-hook-and-heat"}
    active = [
        "ln-vn-editor" if str(x) in legacy else str(x)
        for x in active
        if str(x).strip()
    ]
    # de-dupe, keep one
    seen = set()
    uniq: List[str] = []
    for a in active:
        if a not in seen:
            seen.add(a)
            uniq.append(a)
    active = uniq[:1] or default_active_ids()
    custom = raw.get("customPacks")
    if not isinstance(custom, list):
        custom = []
    return {
        "activeIds": active,
        "customPacks": [c for c in custom if isinstance(c, dict)],
    }


class MentorsPutIn(BaseModel):
    activeIds: List[str] = Field(default_factory=list)
    customPacks: Optional[List[Dict[str, Any]]] = None


class MentorImportIn(BaseModel):
    markdown: str
    name: Optional[str] = None
    id: Optional[str] = None
    activate: bool = True


@router.get("/mentors")
async def list_mentors():
    return {
        "packs": list_builtin_meta(),
        "defaultActiveIds": default_active_ids(),
        "note": "内置一个完整 LN/VN 写作导师，无需切换角色；可另导入自定义包替换。",
    }


@router.get("/mentors/{pack_id}")
async def get_mentor(pack_id: str):
    pack = get_builtin(pack_id)
    if not pack:
        raise HTTPException(status_code=404, detail=f"未找到内置导师包：{pack_id}")
    return {"meta": pack.meta(), "markdown": pack.raw}


@router.get("/projects/{project_id}/mentors")
async def get_project_mentors(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await get_owned_project(db, user, project_id)
    vn = row_to_vn(row)
    state = _mentor_state(vn)
    active = resolve_project_mentors(vn)
    return {
        "activeIds": state["activeIds"],
        "customPacks": [
            {
                "id": c.get("id"),
                "name": c.get("name"),
                "updatedAt": c.get("updatedAt"),
                "hasMarkdown": bool((c.get("markdown") or "").strip()),
            }
            for c in state["customPacks"]
        ],
        "active": [p.meta() for p in active],
        "builtin": list_builtin_meta(),
        "defaultActiveIds": default_active_ids(),
    }


@router.put("/projects/{project_id}/mentors")
async def put_project_mentors(
    project_id: str,
    body: MentorsPutIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await get_owned_project(db, user, project_id)
    vn = row_to_vn(row)
    state = _mentor_state(vn)
    ids = [x.strip() for x in (body.activeIds or []) if x and str(x).strip()]
    # migrate + cap to 1
    legacy = {"ln-vn-stagecraft", "ln-hook-and-heat"}
    ids = ["ln-vn-editor" if i in legacy else i for i in ids]
    dedup: List[str] = []
    for i in ids:
        if i not in dedup:
            dedup.append(i)
    ids = dedup[:1]
    if not ids:
        ids = default_active_ids()
    # validate known ids
    known = {p["id"] for p in list_builtin_meta()}
    known |= {str(c.get("id")) for c in state["customPacks"] if c.get("id")}
    if body.customPacks is not None:
        known |= {str(c.get("id")) for c in body.customPacks if isinstance(c, dict) and c.get("id")}
    unknown = [i for i in ids if i not in known]
    if unknown:
        raise HTTPException(status_code=400, detail=f"未知导师包：{', '.join(unknown)}")
    next_state: Dict[str, Any] = {
        "activeIds": ids,
        "customPacks": body.customPacks if body.customPacks is not None else state["customPacks"],
    }
    vn.writingMentors = next_state
    vn = touch_project(vn)
    sync_row_from_vn(row, vn)
    await db.commit()
    await db.refresh(row)
    active = resolve_project_mentors(vn)
    return {
        "activeIds": ids,
        "active": [p.meta() for p in active],
        "project": vn.model_dump(mode="json", by_alias=True),
    }


@router.post("/projects/{project_id}/mentors/import")
async def import_project_mentor(
    project_id: str,
    body: MentorImportIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    md = (body.markdown or "").strip()
    if not md:
        raise HTTPException(status_code=400, detail="markdown 不能为空")
    row = await get_owned_project(db, user, project_id)
    vn = row_to_vn(row)
    state = _mentor_state(vn)
    fallback = (body.id or "custom").strip() or "custom"
    pack = parse_mentor_markdown(md, fallback_id=fallback, source="custom")
    if body.name:
        pack.name = body.name.strip()
    if body.id:
        pack.id = body.id.strip()
    # avoid colliding with builtin ids unless intentional overwrite of custom only
    if get_builtin(pack.id):
        pack.id = f"custom-{pack.id}"
    entry = {
        "id": pack.id,
        "name": pack.name,
        "markdown": md,
        "updatedAt": _now(),
    }
    customs = [c for c in state["customPacks"] if str(c.get("id")) != pack.id]
    customs.append(entry)
    active_ids = list(state["activeIds"])
    if body.activate:
        active_ids = [pack.id]
    vn.writingMentors = {"activeIds": active_ids[:1] or default_active_ids(), "customPacks": customs}
    vn = touch_project(vn)
    sync_row_from_vn(row, vn)
    await db.commit()
    await db.refresh(row)
    return {
        "imported": {"id": pack.id, "name": pack.name},
        "activeIds": active_ids,
        "project": vn.model_dump(mode="json", by_alias=True),
    }


class MentorMatchIn(BaseModel):
    text: str = ""


@router.post("/projects/{project_id}/mentors/match")
async def match_mentors_text(
    project_id: str,
    body: MentorMatchIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    """Resolve mentor ids from natural language (e.g. 切换导师：钩子)."""
    await get_owned_project(db, user, project_id)
    text = (body.text or "").strip()
    ids = match_mentor_ids_from_text(text)
    return {"ids": ids, "text": text}
