"""Corpus ranking, prefer notes, and script anchors."""

from __future__ import annotations

from app.core.character_voice.corpus import (
    append_prefer_note,
    format_corpus_for_prompt,
    rank_corpus_samples,
    select_corpus_for_prompt,
)
from app.core.character_voice.extract import format_script_anchors_for_prompt
from app.domain.types import Character, VnProject, VoiceCorpusLine, VoiceCorpusSample


def _sample(
    *,
    sid: str,
    scenario: str,
    source: str,
    text: str,
    label: str | None = None,
) -> VoiceCorpusSample:
    return VoiceCorpusSample(
        id=sid,
        scenario=scenario,
        scenarioLabel=label or scenario,
        lines=[VoiceCorpusLine(speaker="self", text=text)],
        source=source,  # type: ignore[arg-type]
    )


def test_rank_prefers_manual_and_same_scenario():
    char = Character.model_validate(
        {
            "id": "c1",
            "defineName": "senpai",
            "displayName": "学姐",
            "voiceCorpus": [
                _sample(
                    sid="1",
                    scenario="idle_chat",
                    source="preference",
                    text="随便聊聊天气吧。",
                ),
                _sample(
                    sid="2",
                    scenario="misunderstood",
                    source="preference",
                    text="你想多了。",
                ),
                _sample(
                    sid="3",
                    scenario="misunderstood",
                    source="manual",
                    text="先坐下，听我说完。",
                ),
            ],
        }
    )
    ranked = rank_corpus_samples(
        char, scenario_id="misunderstood", scenario_label="被误解时"
    )
    assert ranked[0].id == "3"
    assert ranked[0].source == "manual"


def test_select_prompt_includes_prefer_and_source_tag():
    char = Character.model_validate(
        {
            "id": "c1",
            "defineName": "a",
            "displayName": "A",
            "voicePreferNotes": ["更克制", "用词更像"],
            "voiceCorpus": [
                _sample(
                    sid="m1",
                    scenario="farewell",
                    source="manual",
                    text="……路上小心。",
                    label="分别前夜",
                )
            ],
        }
    )
    bit = select_corpus_for_prompt(
        char, scenario_id="farewell", scenario_label="分别前夜"
    )
    assert "【偏好】" in bit
    assert "更克制" in bit
    assert "金句" in bit


def test_append_prefer_note_dedupes():
    char = Character.model_validate(
        {
            "id": "c1",
            "defineName": "a",
            "displayName": "A",
            "voicePreferNotes": ["节奏对"],
        }
    )
    notes = append_prefer_note(char, "节奏对")
    assert notes.count("节奏对") == 1
    notes2 = append_prefer_note(
        Character.model_validate({**char.model_dump(), "voicePreferNotes": notes}),
        "情绪对",
    )
    assert notes2[-1] == "情绪对"


def test_script_anchors_empty_without_dialogue():
    project = VnProject.model_validate(
        {
            "id": "p1",
            "title": "t",
            "updatedAt": "2026-01-01T00:00:00Z",
            "characters": [
                {"id": "c1", "defineName": "a", "displayName": "A"},
            ],
            "chapters": [{"id": "ch1", "title": "一", "blocks": []}],
        }
    )
    assert format_script_anchors_for_prompt(project, "c1") == ""


def test_script_anchors_from_chapter_dialogue():
    project = VnProject.model_validate(
        {
            "id": "p1",
            "title": "t",
            "updatedAt": "2026-01-01T00:00:00Z",
            "characters": [
                {"id": "c1", "defineName": "lin", "displayName": "霖夏"},
            ],
            "chapters": [
                {
                    "id": "ch1",
                    "title": "雨夜",
                    "blocks": [
                        {
                            "type": "dialogue",
                            "characterId": "c1",
                            "text": "伞借你。别淋着。",
                        }
                    ],
                }
            ],
        }
    )
    bit = format_script_anchors_for_prompt(project, "c1")
    assert "【剧本锚点】" in bit
    assert "伞借你" in bit


def test_format_corpus_wrapper_ranks():
    char = Character.model_validate(
        {
            "id": "c1",
            "defineName": "a",
            "displayName": "A",
            "voiceCorpus": [
                _sample(sid="old", scenario="authority", source="preference", text="是。"),
                _sample(
                    sid="gold",
                    scenario="authority",
                    source="script_extract",
                    text="按规定办。",
                ),
            ],
        }
    )
    bit = format_corpus_for_prompt(
        char, scenario_id="authority", scenario_label="面对权威", max_samples=1
    )
    assert "按规定办" in bit
    assert "剧本" in bit
