"""Engineering writing pipeline: style skill → memory ledger → plan/write/check/revise → gate.

Import from submodules directly to avoid circular imports, e.g.::

    from app.core.pipeline.style_skill import load_style_skill
    from app.core.pipeline.orchestrator import run_pipeline
"""

from app.core.pipeline.ledger import (
    digest_chapter_into_ledger,
    format_ledger_for_agent,
    get_ledger,
    set_ledger,
)

__all__ = [
    "load_style_skill",
    "style_skill_meta",
    "get_ledger",
    "set_ledger",
    "digest_chapter_into_ledger",
    "format_ledger_for_agent",
]


def __getattr__(name: str):
    if name in {"load_style_skill", "style_skill_meta"}:
        from app.core.pipeline import style_skill as _ss

        return getattr(_ss, name)
    if name in {"run_pipeline", "stage_check", "stage_check_async"}:
        from app.core.pipeline import orchestrator as _orch

        return getattr(_orch, name)
    if name in {
        "run_quality_gate",
        "run_quality_gate_async",
        "finalize_chapter",
        "finalize_chapter_async",
    }:
        from app.core.pipeline import gate as _gate

        return getattr(_gate, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")
