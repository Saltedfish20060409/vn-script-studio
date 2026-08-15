"""Baseline schema — idempotent create for fresh or half-migrated DBs."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op
from sqlalchemy.dialects import postgresql

revision = "0001_initial"
down_revision = None
branch_labels = None
depends_on = None


def _has_table(name: str) -> bool:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    return name in insp.get_table_names()


def upgrade() -> None:
    if not _has_table("users"):
        op.create_table(
            "users",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("username", sa.String(length=64), nullable=False),
            sa.Column("password_hash", sa.String(length=255), nullable=False),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_users_username", "users", ["username"], unique=True)

    if not _has_table("projects"):
        op.create_table(
            "projects",
            sa.Column("id", sa.String(length=64), primary_key=True),
            sa.Column("owner_id", sa.String(length=36), sa.ForeignKey("users.id"), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=False, server_default="未命名剧本"),
            sa.Column("genre", sa.String(length=128), nullable=True),
            sa.Column("logline", sa.Text(), nullable=True),
            sa.Column(
                "data",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_projects_owner_id", "projects", ["owner_id"])

    if not _has_table("shares"):
        op.create_table(
            "shares",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("project_id", sa.String(length=64), sa.ForeignKey("projects.id"), nullable=False),
            sa.Column("token", sa.String(length=64), nullable=False),
            sa.Column("title_snapshot", sa.String(length=255), nullable=False, server_default=""),
            sa.Column(
                "data_snapshot",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("expires_at", sa.DateTime(timezone=True), nullable=True),
        )
        op.create_index("ix_shares_project_id", "shares", ["project_id"])
        op.create_index("ix_shares_token", "shares", ["token"], unique=True)

    if not _has_table("agent_sessions"):
        op.create_table(
            "agent_sessions",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("project_id", sa.String(length=64), sa.ForeignKey("projects.id"), nullable=False),
            sa.Column("title", sa.String(length=255), nullable=False, server_default="新对话"),
            sa.Column(
                "messages",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
            sa.Column("chat_memory", sa.Text(), nullable=False, server_default=""),
            sa.Column(
                "undo_stack",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_agent_sessions_project_id", "agent_sessions", ["project_id"])

    if not _has_table("user_settings"):
        op.create_table(
            "user_settings",
            sa.Column("user_id", sa.String(length=36), sa.ForeignKey("users.id"), primary_key=True),
            sa.Column("theme", sa.String(length=16), nullable=False, server_default="day"),
            sa.Column("font_scale", sa.Float(), nullable=False, server_default="1.0"),
            sa.Column("craft_mode", sa.String(length=16), nullable=False, server_default="auto"),
            sa.Column("self_review", sa.String(length=16), nullable=False, server_default="auto"),
            sa.Column("api_key_enc", sa.Text(), nullable=False, server_default=""),
            sa.Column(
                "api_base_url",
                sa.String(length=255),
                nullable=False,
                server_default="https://api.deepseek.com",
            ),
            sa.Column("api_model", sa.String(length=128), nullable=False, server_default="deepseek-chat"),
            sa.Column("critic_api_key_enc", sa.Text(), nullable=False, server_default=""),
            sa.Column("critic_api_base_url", sa.String(length=255), nullable=False, server_default=""),
            sa.Column("critic_api_model", sa.String(length=128), nullable=False, server_default=""),
            sa.Column(
                "bg",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
        )

    if not _has_table("chapter_memory_archives"):
        op.create_table(
            "chapter_memory_archives",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("project_id", sa.String(length=64), sa.ForeignKey("projects.id"), nullable=False),
            sa.Column("label", sa.String(length=64), nullable=False),
            sa.Column("span", sa.Integer(), nullable=False, server_default="10"),
            sa.Column("range_from", sa.Integer(), nullable=False),
            sa.Column("range_to", sa.Integer(), nullable=False),
            sa.Column("word_count", sa.Integer(), nullable=False, server_default="0"),
            sa.Column(
                "chapter_ids",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
            sa.Column(
                "spine",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
            sa.Column(
                "summaries",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
            sa.Column(
                "deltas",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'{}'::jsonb"),
            ),
            sa.Column("is_latest", sa.Boolean(), nullable=False, server_default=sa.text("false")),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index(
            "ix_chapter_memory_archives_project_id",
            "chapter_memory_archives",
            ["project_id"],
        )

    if not _has_table("chapter_memory_slices"):
        op.create_table(
            "chapter_memory_slices",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column(
                "archive_id",
                sa.String(length=36),
                sa.ForeignKey("chapter_memory_archives.id"),
                nullable=False,
            ),
            sa.Column("kind", sa.String(length=32), nullable=False, server_default="continuity"),
            sa.Column("slice_index", sa.Integer(), nullable=False, server_default="0"),
            sa.Column("content", sa.Text(), nullable=False, server_default=""),
            sa.Column("char_count", sa.Integer(), nullable=False, server_default="0"),
        )
        op.create_index(
            "ix_chapter_memory_slices_archive_id",
            "chapter_memory_slices",
            ["archive_id"],
        )

    if not _has_table("lore_craft_cards"):
        op.create_table(
            "lore_craft_cards",
            sa.Column("id", sa.String(length=36), primary_key=True),
            sa.Column("project_id", sa.String(length=64), sa.ForeignKey("projects.id"), nullable=True),
            sa.Column("term", sa.String(length=128), nullable=False),
            sa.Column(
                "aliases",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
            sa.Column("kind", sa.String(length=32), nullable=False, server_default="term"),
            sa.Column("definition_short", sa.Text(), nullable=False, server_default=""),
            sa.Column(
                "do_list",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
            sa.Column(
                "dont_list",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
            sa.Column(
                "vn_beats",
                postgresql.JSONB(astext_type=sa.Text()),
                nullable=False,
                server_default=sa.text("'[]'::jsonb"),
            ),
            sa.Column("source_title", sa.String(length=255), nullable=False, server_default=""),
            sa.Column("source_url", sa.String(length=512), nullable=False, server_default=""),
            sa.Column("raw_extract", sa.Text(), nullable=False, server_default=""),
            sa.Column("attribution", sa.Text(), nullable=False, server_default=""),
            sa.Column("created_at", sa.DateTime(timezone=True), nullable=False),
            sa.Column("updated_at", sa.DateTime(timezone=True), nullable=False),
        )
        op.create_index("ix_lore_craft_cards_project_id", "lore_craft_cards", ["project_id"])
        op.create_index("ix_lore_craft_cards_term", "lore_craft_cards", ["term"])
        op.create_index("ix_lore_craft_cards_kind", "lore_craft_cards", ["kind"])


def downgrade() -> None:
    for t in (
        "lore_craft_cards",
        "chapter_memory_slices",
        "chapter_memory_archives",
        "user_settings",
        "agent_sessions",
        "shares",
        "projects",
        "users",
    ):
        if _has_table(t):
            op.drop_table(t)
