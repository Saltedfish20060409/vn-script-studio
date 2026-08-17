"""project_comments.parent_id — reply threads (2 levels)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0018_comment_parent"
down_revision = "0017_writing_activity"
branch_labels = None
depends_on = None


def _has_column(table: str, column: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    cols = {c["name"] for c in insp.get_columns(table)}
    return column in cols


def upgrade() -> None:
    if _has_column("project_comments", "parent_id"):
        return
    op.add_column(
        "project_comments",
        sa.Column("parent_id", sa.String(length=36), nullable=True),
    )
    op.create_foreign_key(
        "fk_project_comments_parent_id",
        "project_comments",
        "project_comments",
        ["parent_id"],
        ["id"],
        ondelete="CASCADE",
    )
    op.create_index(
        "ix_project_comments_parent_id", "project_comments", ["parent_id"]
    )


def downgrade() -> None:
    if not _has_column("project_comments", "parent_id"):
        return
    op.drop_index("ix_project_comments_parent_id", table_name="project_comments")
    op.drop_constraint(
        "fk_project_comments_parent_id", "project_comments", type_="foreignkey"
    )
    op.drop_column("project_comments", "parent_id")
