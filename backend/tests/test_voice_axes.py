"""Dynamic preference axes: tags, cold-start fallback, convergence brief."""

from __future__ import annotations

from app.core.character_voice.corpus import confirmed_axes, format_corpus_for_prompt
from app.core.character_voice.generate import (
    _build_axes_brief,
    _parse_preference_variants,
    axes_from_tag_ids,
    list_axis_tags,
)
from app.domain.types import Character, VoiceCorpusLine, VoiceCorpusSample


def _char(**kwargs) -> Character:
    base = {"id": "c1", "defineName": "senpai", "displayName": "学姐"}
    base.update(kwargs)
    return Character.model_validate(base)


def test_list_axis_tags_pool_size():
    tags = list_axis_tags()
    assert 15 <= len(tags) <= 30
    ids = {t["id"] for t in tags}
    assert "gentle_persuade" in ids
    assert "cold_short" in ids


def test_axes_from_tag_ids_caps_at_three():
    got = axes_from_tag_ids(
        ["gentle_persuade", "formal_duty", "childlike", "leader"]
    )
    assert len(got) == 3
    assert got[0]["label"] == "温柔劝说"


def test_build_brief_uses_pinned_and_invents_rest():
    char = _char(voice="温柔克制", bio="温柔学姐")
    pinned = axes_from_tag_ids(["gentle_persuade"])
    seed, rule = _build_axes_brief(char, pinned=pinned, confirmed=["温柔劝说"])
    assert len(seed) == 1
    assert "自拟" in rule or "补" in rule or "凑满" in rule


def test_cold_start_fallback_without_card():
    char = _char()
    seed, rule = _build_axes_brief(char, pinned=[], confirmed=[])
    assert len(seed) == 3
    assert "冷启动" in rule or "兜底" in rule


def test_confirmed_axes_and_prompt():
    char = _char(
        voiceCorpus=[
            VoiceCorpusSample(
                id="s1",
                scenario="misunderstood",
                scenarioLabel="被误解时",
                axis="温柔劝说",
                lines=[VoiceCorpusLine(speaker="self", text="先坐下，慢慢说。")],
                source="preference",
            )
        ]
    )
    assert confirmed_axes(char) == ["温柔劝说"]
    bit = format_corpus_for_prompt(char)
    assert "已确认方向" in bit
    assert "温柔劝说" in bit


def test_parse_variants_keeps_dynamic_labels():
    parsed = {
        "axes": [
            {"id": "soft", "label": "温柔劝说", "hint": "软"},
            {"id": "quiet", "label": "沉默关心", "hint": "少话"},
            {"id": "nudge", "label": "轻嗔带刺", "hint": "轻刺"},
        ],
        "variants": [
            {
                "axisId": "soft",
                "axisLabel": "温柔劝说",
                "hypothesis": "先安抚",
                "lines": [{"speaker": "self", "text": "别急。"}],
            },
            {
                "axisId": "quiet",
                "axisLabel": "沉默关心",
                "hypothesis": "少说多陪",
                "lines": [{"speaker": "self", "text": "……我在。"}],
            },
            {
                "axisId": "nudge",
                "axisLabel": "轻嗔带刺",
                "hypothesis": "轻刺提醒",
                "lines": [{"speaker": "self", "text": "又乱想了吧。"}],
            },
        ],
    }
    variants, axes = _parse_preference_variants(parsed, seed_axes=[])
    assert [v["axisLabel"] for v in variants] == ["温柔劝说", "沉默关心", "轻嗔带刺"]
    assert axes[1]["label"] == "沉默关心"
