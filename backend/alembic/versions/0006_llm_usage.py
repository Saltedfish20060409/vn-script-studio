"""llm_usage — per-user LLM token accounting."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0006_llm_usage"
down_revision = "0005_agent_jobs"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return name in insp.get_table_names()


def upgrade() -> None:
    if _has_table("llm_usage"):
        return
    op.create_table(
        "llm_usage",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column(
            "project_id", sa.String(length=64), sa.ForeignKey("projects.id"), nullable=True
        ),
        sa.Column("kind", sa.String(length=32), nullable=False, server_default="llm"),
        sa.Column("model", sa.String(length=128), nullable=False, server_default=""),
        sa.Column("prompt_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("completion_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("total_tokens", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_llm_usage_user_id", "llm_usage", ["user_id"])
    op.create_index("ix_llm_usage_project_id", "llm_usage", ["project_id"])
    op.create_index("ix_llm_usage_total_tokens", "llm_usage", ["total_tokens"])


def downgrade() -> None:
    for idx in ("ix_llm_usage_total_tokens", "ix_llm_usage_project_id", "ix_llm_usage_user_id"):
        op.drop_index(idx, table_name="llm_usage")
    op.drop_table("llm_usage")
