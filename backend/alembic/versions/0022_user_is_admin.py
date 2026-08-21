"""users.is_admin — DB-backed admin flag (ADMIN_USERNAMES is bootstrap only)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0022_user_is_admin"
down_revision = "0021_user_disabled"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            ALTER TABLE users
              ADD COLUMN IF NOT EXISTS is_admin BOOLEAN NOT NULL DEFAULT false
            """
        )
    )


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS is_admin")
