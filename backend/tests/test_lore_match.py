"""测试设定卡检索：角色设定/大纲里提到术语时，对应卡自动命中。"""
from __future__ import annotations

from app.core.lore.craft_distill import match_cards_in_text, match_seeds_in_text


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


def test_keyword_semantic_match():
    """近义表达（keywords）触发对应卡：占有欲→病娇。"""
    hits = match_seeds_in_text("她占有欲很强，还会跟踪我。")
    assert any(c["term"] == "病娇" for c in hits)


def test_keyword_semantic_tsundere():
    """嘴硬心软→傲娇。"""
    hits = match_seeds_in_text("她嘴硬心软，明明在意却否认。")
    assert any(c["term"] == "傲娇" for c in hits)


def test_seed_pool_expanded():
    """种子池已扩充到 40+ 条常用二次元设定。"""
    from app.core.lore import SEED_CARDS

    assert len(SEED_CARDS) >= 40
    # 常见题材/套路都在
    terms = {c["term"] for c in SEED_CARDS}
    for expected in ("修罗场", "时间循环", "末世", "转生反派", "学园", "病娇", "傲娇"):
        assert expected in terms, f"缺少种子卡: {expected}"
