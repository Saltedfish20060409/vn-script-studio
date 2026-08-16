"""agent_jobs_cascade — ON DELETE CASCADE for agent_jobs.project_id.

Migration 0012 covered every project child FK except agent_jobs (omitted from
its table list). Fresh installs run 0012 with the corrected list, but existing
databases already stamped 0012 need this follow-up to fix the one FK.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0013_agent_jobs_cascade"
down_revision = "0012_project_cascade"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "agent_jobs" not in insp.get_table_names():
        return
    cols = insp.get_foreign_keys("agent_jobs")
    for fk in cols:
        if fk.get("referred_table") != "projects":
            continue
        op.drop_constraint(fk["name"], "agent_jobs", type_="foreignkey")
        op.create_foreign_key(
            fk["name"],
            "agent_jobs",
            "projects",
            local_cols=list(fk["constrained_columns"]),
            remote_cols=list(fk["referred_columns"]),
            ondelete="CASCADE",
        )
        break


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "agent_jobs" not in insp.get_table_names():
        return
    cols = insp.get_foreign_keys("agent_jobs")
    for fk in cols:
        if fk.get("referred_table") != "projects":
            continue
        op.drop_constraint(fk["name"], "agent_jobs", type_="foreignkey")
        op.create_foreign_key(
            fk["name"],
            "agent_jobs",
            "projects",
            local_cols=list(fk["constrained_columns"]),
            remote_cols=list(fk["referred_columns"]),
        )
        break
