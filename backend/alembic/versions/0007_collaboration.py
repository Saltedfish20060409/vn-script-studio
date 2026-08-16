"""project_members + chapter_locks — collaborative editing (stage A)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0007_collaboration"
down_revision = "0006_llm_usage"
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return name in insp.get_table_names()


def upgrade() -> None:
    if not _has_table("project_members"):
        op.create_table(
            "project_members",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "project_id", sa.String(length=64), sa.ForeignKey("projects.id"), nullable=False
            ),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("role", sa.String(length=16), nullable=False, server_default="editor"),
            sa.Column("joined_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_project_members_project_id", "project_members", ["project_id"])
        op.create_index("ix_project_members_user_id", "project_members", ["user_id"])
    if not _has_table("chapter_locks"):
        op.create_table(
            "chapter_locks",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "project_id", sa.String(length=64), sa.ForeignKey("projects.id"), nullable=False
            ),
            sa.Column("chapter_id", sa.String(length=64), nullable=False),
            sa.Column("user_id", sa.String(length=36), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_chapter_locks_project_id", "chapter_locks", ["project_id"])
        op.create_index("ix_chapter_locks_chapter_id", "chapter_locks", ["chapter_id"])
        op.create_index("ix_chapter_locks_user_id", "chapter_locks", ["user_id"])


def downgrade() -> None:
    for idx, table in (
        ("ix_chapter_locks_user_id", "chapter_locks"),
        ("ix_chapter_locks_chapter_id", "chapter_locks"),
        ("ix_chapter_locks_project_id", "chapter_locks"),
        ("ix_project_members_user_id", "project_members"),
        ("ix_project_members_project_id", "project_members"),
    ):
        op.drop_index(idx, table_name=table)
    op.drop_table("chapter_locks")
    op.drop_table("project_members")
