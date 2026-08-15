"""project_snapshots — move version snapshots out of the project JSONB blob."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0004_project_snapshots"
down_revision = "0003_schema_repair"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return name in insp.get_table_names()


def upgrade() -> None:
    if _has_table("project_snapshots"):
        return
    op.create_table(
        "project_snapshots",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "project_id", sa.String(length=64), sa.ForeignKey("projects.id"), nullable=False
        ),
        sa.Column("label", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("content_hash", sa.String(length=64), nullable=False, server_default=""),
        sa.Column(
            "payload",
            postgresql.JSONB(astext_type=sa.Text()),
            nullable=False,
            server_default=sa.text("'{}'::jsonb"),
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index(
        "ix_project_snapshots_project_id", "project_snapshots", ["project_id"]
    )
    op.create_index(
        "ix_project_snapshots_content_hash", "project_snapshots", ["content_hash"]
    )


def downgrade() -> None:
    op.drop_index("ix_project_snapshots_content_hash", table_name="project_snapshots")
    op.drop_index("ix_project_snapshots_project_id", table_name="project_snapshots")
    op.drop_table("project_snapshots")
