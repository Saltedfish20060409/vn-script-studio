"""Author lens API — list / select / import / match."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.ai import DeepSeekConfig
from app.core.lenses import (
    get_builtin_lens,
    list_builtin_lens_meta,
    match_lens_ids_from_text,
    parse_lens_markdown,
    resolve_project_lenses,
)
from app.core.lenses.brainstorm import format_brainstorm_markdown, run_brainstorm
from app.core.project import touch_project
from app.db import get_db
from app.models import User
from app.security import get_current_user
from app.services.projects import (
    get_owned_project,
    resolve_llm_credentials,
    row_to_vn,
    sync_chapter_rows_from_vn,
)

router = APIRouter(tags=["lenses"])


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _lens_state(vn) -> Dict[str, Any]:
    raw = vn.authorLenses if isinstance(getattr(vn, "authorLenses", None), dict) else {}
    active = raw.get("activeIds")
    if not isinstance(active, list):
        active = []
    out: List[str] = []
    for x in active:
        s = str(x).strip()
        if s and s not in out:
            out.append(s)
    custom = raw.get("customPacks")
    if not isinstance(custom, list):
        custom = []
    return {
        "activeIds": out[:3],
        "customPacks": [c for c in custom if isinstance(c, dict)],
    }


class LensesPutIn(BaseModel):
    activeIds: List[str] = Field(default_factory=list)
    customPacks: Optional[List[Dict[str, Any]]] = None


class LensImportIn(BaseModel):
    markdown: str
    name: Optional[str] = None
    id: Optional[str] = None
    activate: bool = True


class LensMatchIn(BaseModel):
    text: str = ""


class BrainstormIn(BaseModel):
    question: str = ""
    lens_ids: Optional[List[str]] = None
    chapter_id: Optional[str] = None
    selection: str = ""
    draft: str = ""


@router.get("/lenses")
async def list_lenses():
    packs = list_builtin_lens_meta()
    for p in packs:
        p["family"] = "author"
        p["persona"] = "author"
    return {
        "packs": packs,
        "families": {"author": "作家思维"},
        "note": "切换的是作家 skill 视角；LN/VN 底盘由通用文学编辑自动提供。可用女娲蒸馏后导入。",
        "maxActive": 3,
    }


@router.get("/lenses/{pack_id}")
async def get_lens(pack_id: str):
    pack = get_builtin_lens(pack_id)
    if not pack:
        raise HTTPException(status_code=404, detail=f"未找到作家思维包：{pack_id}")
    return {"meta": pack.meta(), "markdown": pack.raw}


@router.get("/projects/{project_id}/lenses")
async def get_project_lenses(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await get_owned_project(db, user, project_id)
    vn = row_to_vn(row)
    state = _lens_state(vn)
    active = resolve_project_lenses(vn)
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
        "builtin": list_builtin_lens_meta(),
    }


@router.put("/projects/{project_id}/lenses")
async def put_project_lenses(
    project_id: str,
    body: LensesPutIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await get_owned_project(db, user, project_id)
    vn = row_to_vn(row)
    state = _lens_state(vn)
    from app.core.lenses import normalize_lens_id

    ids: List[str] = []
    for x in body.activeIds or []:
        nid = normalize_lens_id(str(x).strip())
        if nid and nid not in ids:
            ids.append(nid)
    ids = ids[:3]
    known = {p["id"] for p in list_builtin_lens_meta()}
    known |= {str(c.get("id")) for c in state["customPacks"] if c.get("id")}
    if body.customPacks is not None:
        known |= {
            str(c.get("id"))
            for c in body.customPacks
            if isinstance(c, dict) and c.get("id")
        }
    unknown = [i for i in ids if i not in known]
    if unknown:
        raise HTTPException(status_code=400, detail=f"未知作家思维包：{', '.join(unknown)}")
    vn.authorLenses = {
        "activeIds": ids,
        "customPacks": body.customPacks if body.customPacks is not None else state["customPacks"],
    }
    vn = touch_project(vn)
    await sync_chapter_rows_from_vn(db, row, vn)
    await db.commit()
    await db.refresh(row)
    active = resolve_project_lenses(vn)
    return {
        "activeIds": ids,
        "active": [p.meta() for p in active],
        "project": vn.model_dump(mode="json", by_alias=True),
    }


@router.post("/projects/{project_id}/lenses/import")
async def import_project_lens(
    project_id: str,
    body: LensImportIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    md = (body.markdown or "").strip()
    if not md:
        raise HTTPException(status_code=400, detail="markdown 不能为空")
    row = await get_owned_project(db, user, project_id)
    vn = row_to_vn(row)
    state = _lens_state(vn)
    fallback = (body.id or "custom-lens").strip() or "custom-lens"
    pack = parse_lens_markdown(md, fallback_id=fallback, source="custom")
    if body.name:
        pack.name = body.name.strip()
    if body.id:
        pack.id = body.id.strip()
    if get_builtin_lens(pack.id):
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
        active_ids = [pack.id] + [i for i in active_ids if i != pack.id]
        active_ids = active_ids[:3]
    vn.authorLenses = {"activeIds": active_ids, "customPacks": customs}
    vn = touch_project(vn)
    await sync_chapter_rows_from_vn(db, row, vn)
    await db.commit()
    await db.refresh(row)
    return {
        "imported": {"id": pack.id, "name": pack.name},
        "activeIds": active_ids,
        "project": vn.model_dump(mode="json", by_alias=True),
    }


@router.post("/projects/{project_id}/lenses/match")
async def match_lenses_text(
    project_id: str,
    body: LensMatchIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_owned_project(db, user, project_id)
    text = (body.text or "").strip()
    return {"ids": match_lens_ids_from_text(text), "text": text}


@router.post("/projects/{project_id}/brainstorm")
async def project_brainstorm(
    project_id: str,
    body: BrainstormIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    """强头脑风暴：每位作家独立调用，再责编综合。"""
    row = await get_owned_project(db, user, project_id)
    vn = row_to_vn(row)
    creds = await resolve_llm_credentials(db, user.id, settings)
    if not creds["api_key"]:
        raise HTTPException(status_code=400, detail="服务端未配置 DEEPSEEK_API_KEY")
    cfg = DeepSeekConfig(
        apiKey=creds["api_key"],
        baseUrl=creds["base_url"],
        model=creds["model"],
    )
    try:
        result = await run_brainstorm(
            cfg,
            vn,
            question=body.question,
            lens_ids=body.lens_ids,
            chapter_id=body.chapter_id,
            selection=body.selection or "",
            draft=body.draft or "",
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except Exception as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {
        **result,
        "markdown": format_brainstorm_markdown(result),
    }
