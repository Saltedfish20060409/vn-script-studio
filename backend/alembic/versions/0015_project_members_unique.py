"""project_members_unique — one membership per (project_id, user_id).

Concurrent add_member / invite accepts could previously insert duplicate
memberships (check-then-insert without a DB constraint). The unique
constraint + IntegrityError handling in the service closes the race.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0015_project_members_unique"
down_revision = "0014_chapter_locks_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "project_members" not in insp.get_table_names():
        return
    existing = {c["name"] for c in insp.get_unique_constraints("project_members")}
    if "uq_project_members_project_user" in existing:
        return
    # Remove duplicate memberships (keep one row per project+user) so the
    # unique index can be created.
    bind.execute(
        sa.text(
            """
            DELETE FROM project_members a USING project_members b
            WHERE a.project_id = b.project_id
              AND a.user_id = b.user_id
              AND a.id < b.id
            """
        )
    )
    op.create_unique_constraint(
        "uq_project_members_project_user",
        "project_members",
        ["project_id", "user_id"],
    )


def downgrade() -> None:
    op.drop_constraint(
        "uq_project_members_project_user", "project_members", type_="unique"
    )
