"""ACG lore package — Moegirl-inspired craft cards for VN/LN."""
from app.core.lore.craft_distill import (
    ATTRIBUTION,
    SEED_CARDS,
    checklist_inspire,
    distill_from_extract,
    format_cards_for_agent,
    match_cards_in_text,
    match_seeds_in_text,
    seed_by_term,
)
from app.core.lore.moegirl_client import MoegirlPage, fetch_extract, search_titles

__all__ = [
    "ATTRIBUTION",
    "SEED_CARDS",
    "MoegirlPage",
    "checklist_inspire",
    "distill_from_extract",
    "format_cards_for_agent",
    "match_cards_in_text",
    "match_seeds_in_text",
    "seed_by_term",
    "fetch_extract",
    "search_titles",
]
