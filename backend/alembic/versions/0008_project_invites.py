"""project_invites — shareable member invite links."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0008_project_invites"
down_revision = "0007_collaboration"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return name in insp.get_table_names()


def upgrade() -> None:
    if _has_table("project_invites"):
        return
    op.create_table(
        "project_invites",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "project_id", sa.String(length=64), sa.ForeignKey("projects.id"), nullable=False
        ),
        sa.Column("token", sa.String(length=64), nullable=False),
        sa.Column("role", sa.String(length=16), nullable=False, server_default="editor"),
        sa.Column("created_by", sa.String(length=36), nullable=False, server_default=""),
        sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_project_invites_project_id", "project_invites", ["project_id"])
    op.create_index("ix_project_invites_token", "project_invites", ["token"], unique=True)


def downgrade() -> None:
    op.drop_index("ix_project_invites_token", table_name="project_invites")
    op.drop_index("ix_project_invites_project_id", table_name="project_invites")
    op.drop_table("project_invites")
