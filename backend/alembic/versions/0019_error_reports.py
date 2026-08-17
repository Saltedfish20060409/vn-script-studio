"""error_reports — client-side error reports for diagnosis."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0019_error_reports"
down_revision = "0018_comment_parent"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return name in insp.get_table_names()


def upgrade() -> None:
    if _has_table("error_reports"):
        return
    op.create_table(
        "error_reports",
        sa.Column("id", sa.String(length=36), primary_key=True),
        sa.Column("level", sa.String(length=16), nullable=False, server_default="error"),
        sa.Column("message", sa.Text(), nullable=False, server_default=""),
        sa.Column("stack", sa.Text(), nullable=False, server_default=""),
        sa.Column("url", sa.String(length=1024), nullable=False, server_default=""),
        sa.Column("component", sa.String(length=64), nullable=False, server_default=""),
        sa.Column("user_agent", sa.String(length=512), nullable=False, server_default=""),
        sa.Column(
            "user_id",
            sa.String(length=36),
            sa.ForeignKey("users.id", ondelete="SET NULL"),
            nullable=True,
        ),
        sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
    )
    op.create_index("ix_error_reports_user_id", "error_reports", ["user_id"])
    op.create_index("ix_error_reports_created_at", "error_reports", ["created_at"])


def downgrade() -> None:
    if not _has_table("error_reports"):
        return
    op.drop_index("ix_error_reports_created_at", table_name="error_reports")
    op.drop_index("ix_error_reports_user_id", table_name="error_reports")
    op.drop_table("error_reports")
