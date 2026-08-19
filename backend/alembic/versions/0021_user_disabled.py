"""users.disabled_at — operator ban flag."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0021_user_disabled"
down_revision = "0020_user_email"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            ALTER TABLE users
              ADD COLUMN IF NOT EXISTS disabled_at TIMESTAMPTZ
            """
        )
    )


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS disabled_at")
