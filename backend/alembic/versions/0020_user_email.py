"""user email fields + auth email tokens (verify / password reset)."""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0020_user_email"
down_revision = "0019_error_reports"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            ALTER TABLE users
              ADD COLUMN IF NOT EXISTS email VARCHAR(255)
            """
        )
    )
    conn.execute(
        sa.text(
            """
            ALTER TABLE users
              ADD COLUMN IF NOT EXISTS email_verified_at TIMESTAMPTZ
            """
        )
    )
    conn.execute(
        sa.text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ix_users_email
              ON users (email)
              WHERE email IS NOT NULL
            """
        )
    )
    conn.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS auth_email_tokens (
              id VARCHAR(36) PRIMARY KEY,
              user_id VARCHAR(36) NOT NULL REFERENCES users(id) ON DELETE CASCADE,
              token VARCHAR(128) NOT NULL,
              purpose VARCHAR(16) NOT NULL,
              expires_at TIMESTAMPTZ NOT NULL,
              used_at TIMESTAMPTZ,
              created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(
        sa.text(
            """
            CREATE UNIQUE INDEX IF NOT EXISTS ix_auth_email_tokens_token
              ON auth_email_tokens (token)
            """
        )
    )
    conn.execute(
        sa.text(
            """
            CREATE INDEX IF NOT EXISTS ix_auth_email_tokens_user_id
              ON auth_email_tokens (user_id)
            """
        )
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS auth_email_tokens")
    op.execute("DROP INDEX IF EXISTS ix_users_email")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS email_verified_at")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS email")
