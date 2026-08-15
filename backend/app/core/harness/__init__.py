"""VN Script Studio Harness — NovelMaster multi-role pipeline adapted for LN/VN."""
from app.core.harness.ai_flavor import (
    HarnessIssue,
    issues_to_dict,
    lint_ai_flavor,
    lint_vn_harness,
    summarize_issues,
)
from app.core.harness.audit_full import full_audit_draft
from app.core.harness.pipeline import (
    audit_draft,
    build_writer_user_prompt,
    harness_editor_pass,
    run_harness_llm,
)
from app.core.harness.roles import (
    OTAKU_SKILLS,
    ROLE_PROMPTS,
    build_role_system,
    otaku_skill_bodies,
)

__all__ = [
    "HarnessIssue",
    "lint_ai_flavor",
    "lint_vn_harness",
    "full_audit_draft",
    "issues_to_dict",
    "summarize_issues",
    "audit_draft",
    "run_harness_llm",
    "harness_editor_pass",
    "build_writer_user_prompt",
    "OTAKU_SKILLS",
    "ROLE_PROMPTS",
    "build_role_system",
    "otaku_skill_bodies",
]
