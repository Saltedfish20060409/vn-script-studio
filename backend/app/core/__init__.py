"""Re-exports mirroring packages/core/src/index.ts"""
from app.domain.types import (
    LOCATION_RELATION_LABELS,
    MAP_LINE_STYLE_LABELS,
)

from .agent import ApplyAgentResult, apply_agent_actions, run_agent
from .agent_context import (
    AGENT_TASKS,
    AgentContextOptions,
    AgentContextResult,
    build_agent_context,
    infer_agent_task,
    is_agent_task,
    task_hint,
)
from .ai import DeepSeekConfig, run_ai
from .branch_tree import BranchNode, build_branch_tree
from .chapter_digest import (
    ChapterDigest,
    digest_all_chapters,
    format_chapter_digest_index,
    make_chapter_digest,
    refresh_chapter_index,
)
from .demo import create_demo_project, empty_project
from .fact_extract import (
    accept_character_link,
    accept_timeline_event,
    build_scan_candidates,
    compute_fingerprints,
    reconcile_stale,
)
from .import_text import project_from_plain_text
from .longform_memory import (
    ChatMemoryBundle,
    compress_chat_history,
    parse_outline_beats,
    select_outline_beats,
    summarize_chat_memory,
)
from .map_catalog import (
    DEFAULT_MAP_STYLE,
    MAP_ELEMENT_PRESETS,
    MAP_STYLES,
    MapElementPreset,
    normalize_map_style,
    preset_by_kind,
)
from .map_extract_smart import (
    accept_map_extract_proposal,
    build_map_extract_corpus,
    build_map_extract_proposal,
    extract_map_smart,
    lexicon_suggest_places,
    merge_suggested_places,
)
from .narrative_lint import NarrativeLintIssue, lint_has_blockers, lint_narrative_draft
from .narrative_review import (
    NarrativeReviewResult,
    SelfReviewPreference,
    apply_reviewed_script,
    chapter_tail_plain,
    extract_script_from_actions,
    run_narrative_self_review,
    should_self_review,
)
from .novel_memory import (
    DEFAULT_SPAN as MEMORY_ARCHIVE_SPAN,
)
from .novel_memory import (
    build_all_archive_drafts,
    format_memory_for_agent,
    slice_text,
)
from .project import (
    extract_locations_from_script,
    extract_map_from_script,
    new_location_link,
    normalize_project,
    touch_project,
    uid,
)
from .renpy import export_character_defines, export_to_renpy, project_to_context
from .voice_check import VoiceIssue, VoiceReport, run_voice_check
from .writing_craft import (
    ALL_WRITING_SKILL_IDS,
    CraftDecision,
    CraftMode,
    CraftModePreference,
    WritingSkill,
    WritingSkillId,
    build_writing_craft_prompt,
    get_writing_skill,
    list_writing_skills,
    select_craft_mode,
    skills_for_task,
    writing_skill_titles,
)

__all__ = [
    "LOCATION_RELATION_LABELS",
    "MAP_LINE_STYLE_LABELS",
    "DEFAULT_MAP_STYLE",
    "MAP_STYLES",
    "MAP_ELEMENT_PRESETS",
    "MapElementPreset",
    "preset_by_kind",
    "normalize_map_style",
    "export_to_renpy",
    "export_character_defines",
    "project_to_context",
    "run_ai",
    "DeepSeekConfig",
    "run_agent",
    "apply_agent_actions",
    "ApplyAgentResult",
    "build_agent_context",
    "infer_agent_task",
    "is_agent_task",
    "task_hint",
    "AGENT_TASKS",
    "AgentContextOptions",
    "AgentContextResult",
    "build_writing_craft_prompt",
    "skills_for_task",
    "writing_skill_titles",
    "list_writing_skills",
    "get_writing_skill",
    "select_craft_mode",
    "ALL_WRITING_SKILL_IDS",
    "WritingSkill",
    "WritingSkillId",
    "CraftMode",
    "CraftModePreference",
    "CraftDecision",
    "lint_narrative_draft",
    "lint_has_blockers",
    "NarrativeLintIssue",
    "run_narrative_self_review",
    "should_self_review",
    "extract_script_from_actions",
    "apply_reviewed_script",
    "chapter_tail_plain",
    "SelfReviewPreference",
    "NarrativeReviewResult",
    "build_branch_tree",
    "BranchNode",
    "run_voice_check",
    "VoiceIssue",
    "VoiceReport",
    "accept_character_link",
    "accept_timeline_event",
    "build_scan_candidates",
    "compute_fingerprints",
    "reconcile_stale",
    "create_demo_project",
    "empty_project",
    "normalize_project",
    "touch_project",
    "extract_locations_from_script",
    "extract_map_from_script",
    "extract_map_smart",
    "build_map_extract_corpus",
    "build_map_extract_proposal",
    "accept_map_extract_proposal",
    "lexicon_suggest_places",
    "merge_suggested_places",
    "uid",
    "new_location_link",
    "project_from_plain_text",
    "digest_all_chapters",
    "make_chapter_digest",
    "format_chapter_digest_index",
    "refresh_chapter_index",
    "ChapterDigest",
    "compress_chat_history",
    "summarize_chat_memory",
    "parse_outline_beats",
    "select_outline_beats",
    "ChatMemoryBundle",
    "MEMORY_ARCHIVE_SPAN",
    "build_all_archive_drafts",
    "format_memory_for_agent",
    "slice_text",
]
