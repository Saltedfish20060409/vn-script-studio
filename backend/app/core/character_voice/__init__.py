"""Character voice corpus: preference calibration, mind pack, extract, export, workshop chat."""

from __future__ import annotations

from .corpus import (
    confirmed_axes,
    corpus_stats,
    find_character,
    format_corpus_for_prompt,
    format_mind_for_prompt,
    normalize_scenario_key,
    patch_character,
    sample_count,
    scenario_coverage,
    select_corpus_for_prompt,
)
from .export_pack import build_nuwa_export_markdown, parse_mind_import
from .extract import extract_dialogue_candidates, format_script_anchors_for_prompt
from .generate import (
    SCENARIO_TEMPLATES,
    VOICE_AXIS_TAGS,
    generate_interview_round,
    generate_long_scene,
    generate_voice_variants,
    list_axis_tags,
    list_scenarios,
)
from .synthesize import synthesize_voice_mind
from .workshop_chat import workshop_chat

__all__ = [
    "SCENARIO_TEMPLATES",
    "VOICE_AXIS_TAGS",
    "build_nuwa_export_markdown",
    "confirmed_axes",
    "corpus_stats",
    "extract_dialogue_candidates",
    "find_character",
    "format_corpus_for_prompt",
    "format_mind_for_prompt",
    "format_script_anchors_for_prompt",
    "generate_interview_round",
    "generate_long_scene",
    "generate_voice_variants",
    "list_axis_tags",
    "list_scenarios",
    "normalize_scenario_key",
    "parse_mind_import",
    "patch_character",
    "sample_count",
    "scenario_coverage",
    "select_corpus_for_prompt",
    "synthesize_voice_mind",
    "workshop_chat",
]
