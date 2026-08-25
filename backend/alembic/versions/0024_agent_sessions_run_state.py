"""agent_sessions.run_state — durable execution checkpoint for agent runs.

Stores the in-flight agent loop state (step / internal messages / applied
actions / trace / working project) so a disconnected or failed run can be
resumed from the checkpoint instead of re-burning tokens from scratch.
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0024_agent_sessions_run_state"
down_revision = "0023_projects_row_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            ALTER TABLE agent_sessions
              ADD COLUMN IF NOT EXISTS run_state JSONB
            """
        )
    )


def downgrade() -> None:
    op.execute("ALTER TABLE agent_sessions DROP COLUMN IF EXISTS run_state")
