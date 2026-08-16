"""project_comments — inline annotations (collaboration stage C)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0009_project_comments"
down_revision = "0008_project_invites"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return name in insp.get_table_names()


def upgrade() -> None:
    if _has_table("project_comments"):
        return
    op.create_table(
        "project_comments",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column(
            "project_id", sa.String(length=64), sa.ForeignKey("projects.id"), nullable=False
        ),
        sa.Column("chapter_id", sa.String(length=64), nullable=False),
        sa.Column("anchor", sa.String(length=255), nullable=False, server_default=""),
        sa.Column("user_id", sa.String(length=36), nullable=False),
        sa.Column("text", sa.Text(), nullable=False, server_default=""),
        sa.Column("resolved", sa.Boolean(), nullable=False, server_default=sa.false()),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_project_comments_project_id", "project_comments", ["project_id"])
    op.create_index("ix_project_comments_chapter_id", "project_comments", ["chapter_id"])
    op.create_index("ix_project_comments_anchor", "project_comments", ["anchor"])
    op.create_index("ix_project_comments_user_id", "project_comments", ["user_id"])


def downgrade() -> None:
    op.drop_index("ix_project_comments_user_id", table_name="project_comments")
    op.drop_index("ix_project_comments_anchor", table_name="project_comments")
    op.drop_index("ix_project_comments_chapter_id", table_name="project_comments")
    op.drop_index("ix_project_comments_project_id", table_name="project_comments")
    op.drop_table("project_comments")
