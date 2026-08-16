"""ACG lore / Moegirl craft-card APIs for VN/LN writing."""
from __future__ import annotations

from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings, get_settings
from app.core.lore import ATTRIBUTION, search_titles
from app.db import get_db
from app.models import User
from app.security import get_current_user
from app.services import lore as lore_svc
from app.services.projects import get_owned_project, get_project_readable, row_to_vn

router = APIRouter(prefix="/projects", tags=["lore"])


class LoreLookupIn(BaseModel):
    term: str = Field(min_length=1, max_length=128)
    prefer_live: bool = True


class LoreSaveIn(BaseModel):
    term: str = Field(min_length=1, max_length=128)
    aliases: List[str] = Field(default_factory=list)
    kind: str = "term"
    definition_short: str = ""
    do: List[str] = Field(default_factory=list)
    dont: List[str] = Field(default_factory=list)
    vn_beats: List[str] = Field(default_factory=list)
    source_title: str = ""
    source_url: str = ""
    raw_extract: str = ""
    attribution: str = ""
    card_id: Optional[str] = None


class LoreInspireIn(BaseModel):
    text: str = ""
    kinds: Optional[List[str]] = None
    limit: int = Field(default=6, ge=1, le=12)


@router.get("/{project_id}/lore/meta")
async def lore_meta(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    await get_project_readable(db, user, project_id)
    return {
        "attribution": ATTRIBUTION,
        "licenseNote": "CC BY-NC-SA 3.0（以萌娘百科页面标注为准）；自用精炼，勿商业整页复用。",
        "moegirlEnabled": settings.moegirl_enabled,
        "checklistKinds": ["moe_attribute", "genre", "trope"],
    }


@router.get("/{project_id}/lore/checklist")
async def lore_checklist(
    project_id: str,
    kinds: Optional[str] = None,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_project_readable(db, user, project_id)
    kind_list = [k.strip() for k in (kinds or "").split(",") if k.strip()] or None
    return {"cards": lore_svc.checklist(kind_list), "attribution": ATTRIBUTION}


@router.get("/{project_id}/lore/cards")
async def lore_list_cards(
    project_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_project_readable(db, user, project_id)
    return {"cards": await lore_svc.list_project_cards(db, project_id)}


@router.post("/{project_id}/lore/search")
async def lore_search(
    project_id: str,
    body: LoreLookupIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    await get_owned_project(db, user, project_id)
    if not settings.moegirl_enabled:
        return {"hits": [], "moegirlEnabled": False}
    try:
        hits = await search_titles(
            body.term,
            api_base=settings.moegirl_api_base,
            user_agent=settings.moegirl_user_agent,
            limit=8,
        )
    except Exception as exc:
        raise HTTPException(status_code=502, detail=f"萌百搜索失败: {exc}") from exc
    return {"hits": hits, "moegirlEnabled": True, "attribution": ATTRIBUTION}


@router.post("/{project_id}/lore/lookup")
async def lore_lookup(
    project_id: str,
    body: LoreLookupIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
    settings: Settings = Depends(get_settings),
):
    await get_owned_project(db, user, project_id)
    try:
        result = await lore_svc.lookup_term(
            settings, body.term, prefer_live=body.prefer_live
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    except LookupError as exc:
        raise HTTPException(status_code=404, detail=str(exc)) from exc
    return {**result, "attribution": ATTRIBUTION}


@router.post("/{project_id}/lore/inspire")
async def lore_inspire(
    project_id: str,
    body: LoreInspireIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    row = await get_owned_project(db, user, project_id)
    vn = row_to_vn(row)
    resolved = await lore_svc.resolve_lore_block(
        db,
        project_id,
        vn,
        user_message=body.text,
        limit=body.limit,
    )
    # Also surface checklist if text empty
    if not resolved["cards"] and not body.text.strip():
        resolved["cards"] = lore_svc.checklist(body.kinds)[: body.limit]
        from app.core.lore import format_cards_for_agent

        resolved["agentBlock"] = format_cards_for_agent(resolved["cards"])
    return resolved


@router.post("/{project_id}/lore/cards")
async def lore_save_card(
    project_id: str,
    body: LoreSaveIn,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_owned_project(db, user, project_id)
    payload = body.model_dump()
    card_id = payload.pop("card_id", None)
    try:
        saved = await lore_svc.save_craft_card(
            db, project_id, payload, card_id=card_id
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc
    return {"card": saved}


@router.delete("/{project_id}/lore/cards/{card_id}")
async def lore_delete_card(
    project_id: str,
    card_id: str,
    user: User = Depends(get_current_user),
    db: AsyncSession = Depends(get_db),
):
    await get_owned_project(db, user, project_id)
    ok = await lore_svc.delete_craft_card(db, project_id, card_id)
    if not ok:
        raise HTTPException(status_code=404, detail="工艺卡不存在")
    return {"ok": True}
