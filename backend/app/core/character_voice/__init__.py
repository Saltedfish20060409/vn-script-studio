"""Character voice corpus: preference calibration, mind pack, extract, export, workshop chat."""

from __future__ import annotations

from .corpus import (
    corpus_stats,
    find_character,
    format_corpus_for_prompt,
    format_mind_for_prompt,
    patch_character,
    sample_count,
    scenario_coverage,
)
from .export_pack import build_nuwa_export_markdown, parse_mind_import
from .extract import extract_dialogue_candidates
from .generate import (
    SCENARIO_TEMPLATES,
    generate_interview_round,
    generate_long_scene,
    generate_voice_variants,
    list_scenarios,
)
from .synthesize import synthesize_voice_mind
from .workshop_chat import workshop_chat

__all__ = [
    "SCENARIO_TEMPLATES",
    "build_nuwa_export_markdown",
    "corpus_stats",
    "extract_dialogue_candidates",
    "find_character",
    "format_corpus_for_prompt",
    "format_mind_for_prompt",
    "generate_interview_round",
    "generate_long_scene",
    "generate_voice_variants",
    "list_scenarios",
    "parse_mind_import",
    "patch_character",
    "sample_count",
    "scenario_coverage",
    "synthesize_voice_mind",
    "workshop_chat",
]
