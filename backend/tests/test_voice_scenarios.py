"""Scenario pool expansion + custom coverage keys."""

from __future__ import annotations

from app.core.character_voice.corpus import (
    make_sample,
    normalize_scenario_key,
    scenario_coverage,
)
from app.core.character_voice.generate import list_scenarios
from app.domain.types import Character, VoiceCorpusLine, VoiceCorpusSample


def test_list_scenarios_expanded_with_long_flags():
    rows = list_scenarios()
    presets = [r for r in rows if r["id"] != "custom"]
    assert len(presets) >= 14
    assert any(r.get("longSuitable") for r in presets)
    assert any(not r.get("longSuitable") for r in presets)
    assert any(r["id"] == "farewell" for r in presets)
    assert any(r["id"] == "apology" for r in presets)


def test_normalize_custom_keys_distinct():
    a = normalize_scenario_key("custom", "雨夜车站")
    b = normalize_scenario_key("custom:教室对峙", "教室对峙")
    c = normalize_scenario_key("custom", "自定义", prompt="对方突然提分手，你还想留住关系")
    assert a == "custom:雨夜车站"
    assert b == "custom:教室对峙"
    assert a != b
    assert c.startswith("custom:")
    assert c != "custom:自定义"


def test_scenario_coverage_counts_custom_separately():
    char = Character.model_validate(
        {
            "id": "c1",
            "defineName": "a",
            "displayName": "A",
            "voiceCorpus": [
                VoiceCorpusSample(
                    id="1",
                    scenario="custom",
                    scenarioLabel="雨夜",
                    lines=[VoiceCorpusLine(text="……")],
                ),
                VoiceCorpusSample(
                    id="2",
                    scenario="custom:教室",
                    scenarioLabel="教室",
                    lines=[VoiceCorpusLine(text="嗯。")],
                ),
                VoiceCorpusSample(
                    id="3",
                    scenario="misunderstood",
                    scenarioLabel="被误解时",
                    lines=[VoiceCorpusLine(text="不是。")],
                ),
            ],
        }
    )
    assert scenario_coverage(char) == 3


def test_make_sample_rewrites_bare_custom():
    s = make_sample(
        scenario="custom",
        scenario_label="自定义",
        axis="温柔劝说",
        hypothesis=None,
        lines=[{"speaker": "self", "text": "先听我说。"}],
        scenario_prompt="雨夜里两人不说话，只剩伞的声音",
    )
    assert s.scenario.startswith("custom:")
    assert s.scenario != "custom"
    assert "雨夜" in s.scenario or "伞" in s.scenario
