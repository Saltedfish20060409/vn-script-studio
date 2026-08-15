"""analysis_inbox_items - idempotent."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0002_analysis_inbox"
down_revision = "0001_initial"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return name in insp.get_table_names()


def upgrade() -> None:
    if _has_table("analysis_inbox_items"):
        return
    op.create_table(
        "analysis_inbox_items",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("project_id", sa.String(length=64), sa.ForeignKey("projects.id"), nullable=False),
        sa.Column("kind", sa.String(length=32), nullable=False),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column(
            "evidence",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'[]'::jsonb"),
        ),
        sa.Column("status", sa.String(length=16), nullable=False, server_default="pending"),
        sa.Column("dedupe_key", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_analysis_inbox_items_project_id", "analysis_inbox_items", ["project_id"])
    op.create_index("ix_analysis_inbox_items_kind", "analysis_inbox_items", ["kind"])
    op.create_index("ix_analysis_inbox_items_status", "analysis_inbox_items", ["status"])
    op.create_index("ix_analysis_inbox_items_dedupe_key", "analysis_inbox_items", ["dedupe_key"])


def downgrade() -> None:
    if _has_table("analysis_inbox_items"):
        op.drop_table("analysis_inbox_items")
