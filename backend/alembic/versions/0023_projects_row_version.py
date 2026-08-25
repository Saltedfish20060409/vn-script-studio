"""projects.row_version — optimistic-lock foundation for concurrent saves.

Every write path bumps the counter (sync_row_from_vn); put/patch hold a
FOR UPDATE row lock inside the save transaction so lock-check-save is a
critical section instead of assert-then-race.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0023_projects_row_version"
down_revision = "0022_user_is_admin"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            ALTER TABLE projects
              ADD COLUMN IF NOT EXISTS row_version INTEGER NOT NULL DEFAULT 1
            """
        )
    )


def downgrade() -> None:
    op.execute("ALTER TABLE projects DROP COLUMN IF EXISTS row_version")
