"""测试设定卡检索：角色设定/大纲里提到术语时，对应卡自动命中。"""
from __future__ import annotations

from app.core.lore.craft_distill import match_cards_in_text


def _card(term: str, aliases: list[str] | None = None, kind: str = "trope") -> dict:
    return {"term": term, "aliases": aliases or [], "kind": kind}


CARDS = [_card("病娇", ["ヤンデレ"]), _card("傲娇"), _card("修罗场")]


def test_match_in_character_bio():
    """角色 bio 提到病娇 → 病娇卡命中（用户消息里没有也没关系）。"""
    bio = "林夏是个病娇少女，对主角有强烈的占有欲。"
    hits = match_cards_in_text(CARDS, bio)
    assert [c["term"] for c in hits] == ["病娇"]


def test_match_in_story_outline():
    """故事大纲提到病娇 → 病娇卡命中。"""
    outline = "第三章：修罗场，病娇学姐登场。"
    hits = match_cards_in_text(CARDS, outline)
    terms = [c["term"] for c in hits]
    assert "病娇" in terms
    assert "修罗场" in terms


def test_match_by_alias():
    """别名（如ヤンデレ）命中对应卡。"""
    hits = match_cards_in_text(CARDS, "她是个ヤンデレ。")
    assert [c["term"] for c in hits] == ["病娇"]


def test_no_match_when_term_absent():
    """文本里没有术语 → 不命中。"""
    hits = match_cards_in_text(CARDS, "普通对话，没有任何术语。")
    assert hits == []


def test_seed_cards_match_in_bio():
    """种子卡也能在角色设定里被命中（用到真实 SEED_CARDS）。"""
    from app.core.lore import SEED_CARDS

    # 找一个种子卡 term，构造包含它的 bio
    some = next((c["term"] for c in SEED_CARDS if c.get("term")), None)
    if some:
        hits = match_cards_in_text(SEED_CARDS, f"角色设定提到 {some}")
        assert any(c["term"] == some for c in hits)
