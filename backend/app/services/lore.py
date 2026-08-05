"""Lore craft cards — Moegirl-inspired, project-scoped storage."""
from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from uuid import uuid4

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import Settings
from app.core.lore import (
    ATTRIBUTION,
    checklist_inspire,
    distill_from_extract,
    fetch_extract,
    format_cards_for_agent,
    match_seeds_in_text,
    search_titles,
    seed_by_term,
)
from app.domain.types import VnProject
from app.models.tables import LoreCraftCard


def card_to_dict(row: LoreCraftCard) -> Dict[str, Any]:
    return {
        "id": row.id,
        "projectId": row.project_id,
        "term": row.term,
        "aliases": row.aliases or [],
        "kind": row.kind,
        "definition_short": row.definition_short or "",
        "do": row.do_list or [],
        "dont": row.dont_list or [],
        "vn_beats": row.vn_beats or [],
        "source_title": row.source_title or "",
        "source_url": row.source_url or "",
        "raw_extract": row.raw_extract or "",
        "attribution": row.attribution or ATTRIBUTION,
    }


def dict_to_row_fields(card: Dict[str, Any]) -> Dict[str, Any]:
    return {
        "term": (card.get("term") or "").strip()[:128],
        "aliases": list(card.get("aliases") or []),
        "kind": (card.get("kind") or "term")[:32],
        "definition_short": (card.get("definition_short") or "")[:2000],
        "do_list": list(card.get("do") or []),
        "dont_list": list(card.get("dont") or []),
        "vn_beats": list(card.get("vn_beats") or []),
        "source_title": (card.get("source_title") or "")[:255],
        "source_url": (card.get("source_url") or "")[:512],
        "raw_extract": (card.get("raw_extract") or "")[:2000],
        "attribution": (card.get("attribution") or ATTRIBUTION)[:2000],
    }


async def list_project_cards(
    db: AsyncSession, project_id: str
) -> List[Dict[str, Any]]:
    res = await db.execute(
        select(LoreCraftCard)
        .where(LoreCraftCard.project_id == project_id)
        .order_by(LoreCraftCard.updated_at.desc())
    )
    return [card_to_dict(r) for r in res.scalars().all()]


async def save_craft_card(
    db: AsyncSession,
    project_id: str,
    card: Dict[str, Any],
    *,
    card_id: Optional[str] = None,
) -> Dict[str, Any]:
    fields = dict_to_row_fields(card)
    if not fields["term"]:
        raise ValueError("term 不能为空")

    row: Optional[LoreCraftCard] = None
    if card_id:
        res = await db.execute(
            select(LoreCraftCard).where(
                LoreCraftCard.id == card_id,
                LoreCraftCard.project_id == project_id,
            )
        )
        row = res.scalar_one_or_none()

    if row is None:
        # Upsert by term within project
        res = await db.execute(
            select(LoreCraftCard).where(
                LoreCraftCard.project_id == project_id,
                LoreCraftCard.term == fields["term"],
            )
        )
        row = res.scalar_one_or_none()

    now = datetime.now(timezone.utc)
    if row is None:
        row = LoreCraftCard(
            id=str(uuid4()),
            project_id=project_id,
            created_at=now,
            **fields,
        )
        db.add(row)
    else:
        for k, v in fields.items():
            setattr(row, k, v)
        row.updated_at = now

    await db.commit()
    await db.refresh(row)
    return card_to_dict(row)


async def delete_craft_card(
    db: AsyncSession, project_id: str, card_id: str
) -> bool:
    res = await db.execute(
        select(LoreCraftCard).where(
            LoreCraftCard.id == card_id,
            LoreCraftCard.project_id == project_id,
        )
    )
    row = res.scalar_one_or_none()
    if not row:
        return False
    await db.delete(row)
    await db.commit()
    return True


async def lookup_term(
    settings: Settings,
    term: str,
    *,
    prefer_live: bool = True,
) -> Dict[str, Any]:
    """Resolve a craft card: seed first, then optional Moegirl distill."""
    t = (term or "").strip()
    if not t:
        raise ValueError("请输入术语")

    seed = seed_by_term(t)
    if seed and not prefer_live:
        return {"card": seed, "source": "seed", "hits": []}

    hits: List[Dict[str, Any]] = []
    if settings.moegirl_enabled and prefer_live:
        try:
            hits = await search_titles(
                t,
                api_base=settings.moegirl_api_base,
                user_agent=settings.moegirl_user_agent,
                limit=6,
            )
        except Exception:
            hits = []

        title = hits[0]["title"] if hits else t
        try:
            page = await fetch_extract(
                title,
                api_base=settings.moegirl_api_base,
                user_agent=settings.moegirl_user_agent,
            )
            if not page.missing and page.extract:
                card = distill_from_extract(
                    t,
                    page.extract,
                    source_title=page.title,
                    source_url=page.url,
                )
                # Prefer curated seed do/dont when term matches
                if seed:
                    card["do"] = seed.get("do") or card["do"]
                    card["dont"] = seed.get("dont") or card["dont"]
                    card["vn_beats"] = seed.get("vn_beats") or card["vn_beats"]
                    card["kind"] = seed.get("kind") or card["kind"]
                    if seed.get("definition_short"):
                        card["definition_short"] = seed["definition_short"]
                return {"card": card, "source": "moegirl+seed" if seed else "moegirl", "hits": hits}
        except Exception:
            pass

    if seed:
        return {"card": seed, "source": "seed", "hits": hits}
    raise LookupError(f"未找到「{t}」：萌百不可用且无离线种子卡")


def project_inspire_text(project: VnProject, extra: str = "") -> str:
    bible = project.bible
    parts = [
        project.genre or "",
        project.logline or "",
        (bible.world if bible else "") or "",
        (bible.background if bible else "") or "",
        (bible.outline if bible else "") or "",
        project.lore or "",
        extra or "",
    ]
    for c in project.characters or []:
        parts.extend(
            [
                c.displayName or "",
                c.voice or "",
                c.bio or "",
            ]
        )
    return "\n".join(p for p in parts if p)


async def resolve_lore_block(
    db: AsyncSession,
    project_id: str,
    project: VnProject,
    *,
    user_message: str = "",
    limit: int = 4,
) -> Dict[str, Any]:
    """Assemble agent injection block from seeds + saved project cards."""
    hay = project_inspire_text(project, user_message)
    matched = match_seeds_in_text(hay, limit=limit)
    saved = await list_project_cards(db, project_id)

    by_term: Dict[str, Dict[str, Any]] = {}
    for c in matched:
        by_term[(c.get("term") or "").lower()] = c
    for c in saved[:8]:
        key = (c.get("term") or "").lower()
        if key and key not in by_term:
            by_term[key] = c
        elif key in by_term:
            # Prefer saved (user-curated) when same term
            by_term[key] = c

    cards = list(by_term.values())[:limit]
    block = format_cards_for_agent(cards, max_chars=2400)
    return {
        "cards": cards,
        "agentBlock": block,
        "attribution": ATTRIBUTION,
    }


def checklist(kinds: Optional[List[str]] = None) -> List[Dict[str, Any]]:
    return checklist_inspire(kinds)
