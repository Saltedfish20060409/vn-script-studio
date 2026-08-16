"""agent_jobs — persistent async job rows (pipeline / chapter revise)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0005_agent_jobs"
down_revision = "0004_project_snapshots"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return name in insp.get_table_names()


def upgrade() -> None:
    if _has_table("agent_jobs"):
        return
    op.create_table(
        "agent_jobs",
        sa.Column("id", sa.String(length=48), primary_key=True),
        sa.Column("kind", sa.String(length=32), nullable=False, server_default=""),
        sa.Column(
            "project_id", sa.String(length=64), sa.ForeignKey("projects.id"), nullable=False
        ),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="queued"),
        sa.Column("stage", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("progress", sa.Float(), nullable=False, server_default="0"),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column(
            "result",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=True,
        ),
        sa.Column("error", sa.Text(), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_agent_jobs_project_id", "agent_jobs", ["project_id"])
    op.create_index("ix_agent_jobs_user_id", "agent_jobs", ["user_id"])
    op.create_index("ix_agent_jobs_status", "agent_jobs", ["status"])
    op.create_index("ix_agent_jobs_kind", "agent_jobs", ["kind"])


def downgrade() -> None:
    for idx in (
        "ix_agent_jobs_kind",
        "ix_agent_jobs_status",
        "ix_agent_jobs_user_id",
        "ix_agent_jobs_project_id",
    ):
        op.drop_index(idx, table_name="agent_jobs")
    op.drop_table("agent_jobs")
