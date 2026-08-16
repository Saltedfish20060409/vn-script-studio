"""chapter_locks_unique — one lock row per (project_id, chapter_id).

Concurrent editors could previously double-lock a chapter (check-then-insert
without a DB constraint), making the lock advisory only and breaking
assert_chapters_unlocked. The unique constraint + atomic upsert in
acquire_lock closes the race.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0014_chapter_locks_unique"
down_revision = "0013_agent_jobs_cascade"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "chapter_locks" not in insp.get_table_names():
        return
    # Drop duplicate rows first (keep the most recent per chapter) so the
    # unique index can be created.
    bind.execute(
        sa.text(
            """
            DELETE FROM chapter_locks a USING chapter_locks b
            WHERE a.project_id = b.project_id
              AND a.chapter_id = b.chapter_id
              AND (a.updated_at < b.updated_at
                   OR (a.updated_at = b.updated_at AND a.id < b.id))
            """
        )
    )
    try:
        bind.commit()
    except Exception:  # noqa: BLE001
        pass
    op.create_unique_constraint(
        "uq_chapter_locks_project_chapter",
        "chapter_locks",
        ["project_id", "chapter_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_chapter_locks_project_chapter", "chapter_locks", type_="unique"
    )
