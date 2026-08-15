"""Idempotent repair for DBs that stamped empty 0001/0002 stubs.

- Multi-conversation agent_sessions (drop unique project_id, ensure title/created_at)
- CREATE TABLE IF NOT EXISTS for any missing baseline tables
"""

from __future__ import annotations

from alembic import op
from sqlalchemy import text

revision = "0003_schema_repair"
down_revision = "0002_analysis_inbox"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    # Agent sessions: allow many conversations per project
    conn.execute(
        text(
            """
            DO $$
            BEGIN
              IF EXISTS (
                SELECT 1 FROM pg_constraint
                WHERE conname = 'agent_sessions_project_id_key'
              ) THEN
                ALTER TABLE agent_sessions
                  DROP CONSTRAINT agent_sessions_project_id_key;
              END IF;
            END $$;
            """
        )
    )
    conn.execute(text("DROP INDEX IF EXISTS agent_sessions_project_id_key"))
    conn.execute(text("DROP INDEX IF EXISTS ix_agent_sessions_project_id"))
    conn.execute(
        text(
            """
            ALTER TABLE IF EXISTS agent_sessions
              ADD COLUMN IF NOT EXISTS title VARCHAR(255) DEFAULT '新对话'
            """
        )
    )
    conn.execute(
        text(
            """
            ALTER TABLE IF EXISTS agent_sessions
              ADD COLUMN IF NOT EXISTS created_at TIMESTAMPTZ DEFAULT NOW()
            """
        )
    )
    conn.execute(
        text(
            """
            CREATE INDEX IF NOT EXISTS ix_agent_sessions_project_id
              ON agent_sessions (project_id)
            """
        )
    )
    # analysis inbox — in case 0002 was a no-op stamp
    conn.execute(
        text(
            """
            CREATE TABLE IF NOT EXISTS analysis_inbox_items (
              id VARCHAR(36) PRIMARY KEY,
              project_id VARCHAR(64) NOT NULL REFERENCES projects(id),
              kind VARCHAR(32) NOT NULL,
              payload JSONB NOT NULL DEFAULT '{}'::jsonb,
              evidence JSONB NOT NULL DEFAULT '[]'::jsonb,
              status VARCHAR(16) NOT NULL DEFAULT 'pending',
              dedupe_key VARCHAR(255) NOT NULL DEFAULT '',
              created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
              updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
            )
            """
        )
    )
    conn.execute(
        text(
            "CREATE INDEX IF NOT EXISTS ix_analysis_inbox_items_project_id ON analysis_inbox_items (project_id)"
        )
    )


def downgrade() -> None:
    # Non-destructive repair — no automatic reverse of DROP CONSTRAINT
    pass
