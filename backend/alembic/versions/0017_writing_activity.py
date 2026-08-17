"""writing_activity — per-day word-count deltas for the writing stats dashboard."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0017_writing_activity"
down_revision = "0016_llm_usage_indexes"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return name in insp.get_table_names()


def upgrade() -> None:
    if _has_table("writing_activity"):
        return
    op.create_table(
        "writing_activity",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "project_id",
            sa.String(length=64),
            sa.ForeignKey("projects.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("activity_date", sa.String(length=10), nullable=False),
        sa.Column("words_added", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("words_removed", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("edits", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_writing_activity_project_id", "writing_activity", ["project_id"]
    )
    # Unique per (project, date) — required for ON CONFLICT upsert in
    # record_activity; also serves the heatmap query.
    op.create_unique_constraint(
        "uq_writing_activity_project_date",
        "writing_activity",
        ["project_id", "activity_date"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_writing_activity_project_date", "writing_activity", type_="unique"
    )
    op.drop_index("ix_writing_activity_project_id", table_name="writing_activity")
    op.drop_table("writing_activity")
