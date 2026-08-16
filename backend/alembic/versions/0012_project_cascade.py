"""project_cascade — add ON DELETE CASCADE to all project child FKs.

Deleting a project previously 500'd (IntegrityError) whenever any child row
existed (chapter rows, members, comments, locks, snapshots, invites, inbox
items, memory archives, agent jobs, usage, lore cards, shares, agent sessions).
This migration rewrites every FK referencing projects.id with CASCADE so
`DELETE FROM projects` cleans up children automatically.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0012_project_cascade"
down_revision = "0011_project_chapter_rows"
branch_labels = None
depends_on = None

# (child_table, fk_column) — every FK that points at projects.id
_CHILD_FKS = [
    ("shares", "project_id"),
    ("agent_sessions", "project_id"),
    ("chapter_memory_archives", "project_id"),
    ("analysis_inbox_items", "project_id"),
    ("project_snapshots", "project_id"),
    ("agent_jobs", "project_id"),
    ("llm_usage", "project_id"),
    ("project_members", "project_id"),
    ("project_invites", "project_id"),
    ("chapter_locks", "project_id"),
    ("lore_craft_cards", "project_id"),
    ("project_comments", "project_id"),
    ("project_chapter_rows", "project_id"),
]


def _fk_names(bind, table: str) -> list[str]:
    res = bind.execute(
        sa.text(
            "SELECT conname FROM pg_constraint "
            "WHERE conrelid = :t::regclass AND contype = 'f'"
        ),
        {"t": table},
    )
    return [r[0] for r in res.fetchall()]


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    for table, col in _CHILD_FKS:
        if table not in insp.get_table_names():
            continue
        # Find the FK constraint that references projects(id) on this column.
        cols = insp.get_foreign_keys(table)
        target = None
        for fk in cols:
            if fk.get("referred_table") == "projects" and col in (fk.get("constrained_columns") or []):
                target = fk
                break
        if target is None:
            continue
        name = target["name"]
        op.drop_constraint(name, table, type_="foreignkey")
        op.create_foreign_key(
            name,
            table,
            "projects",
            local_cols=[c for c in target["constrained_columns"]],
            remote_cols=[c for c in target["referred_columns"]],
            ondelete="CASCADE",
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    for table, col in _CHILD_FKS:
        if table not in insp.get_table_names():
            continue
        cols = insp.get_foreign_keys(table)
        target = None
        for fk in cols:
            if fk.get("referred_table") == "projects" and col in (fk.get("constrained_columns") or []):
                target = fk
                break
        if target is None:
            continue
        name = target["name"]
        op.drop_constraint(name, table, type_="foreignkey")
        op.create_foreign_key(
            name,
            table,
            "projects",
            local_cols=[c for c in target["constrained_columns"]],
            remote_cols=[c for c in target["referred_columns"]],
        )
