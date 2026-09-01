"""users.token_version — session invalidation on password reset / change / ban.

Bumped whenever credentials or trust change; access & refresh JWTs embed the
version at issuance and are rejected once it no longer matches the DB row.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0025_users_token_version"
down_revision = "0024_agent_sessions_run_state"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            ALTER TABLE users
              ADD COLUMN IF NOT EXISTS token_version INTEGER NOT NULL DEFAULT 0
            """
        )
    )


def downgrade() -> None:
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS token_version")
