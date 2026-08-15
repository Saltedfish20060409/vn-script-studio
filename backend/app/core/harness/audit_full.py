"""Unified Harness audit — narrative + AI-flavor + style skill (one path)."""
from __future__ import annotations

from typing import Any, Dict

from app.core.harness.pipeline import audit_draft
from app.core.pipeline.style_skill import merge_audit_with_style


def full_audit_draft(draft: str) -> Dict[str, Any]:
    """
    Canonical deterministic check used by HTTP lint, pipeline check/gate,
    editor pass, and Agent lint_draft tool.
    """
    return merge_audit_with_style(audit_draft(draft or ""), draft or "")
