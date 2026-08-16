"""llm_usage_indexes — optimize usage aggregation indexes.

- ix_llm_usage_total_tokens is a dead index: total_tokens only ever appears in
  SUM(), never in a WHERE clause.
- The hot query is `WHERE user_id = ? [AND created_at >= ?]` (usage.py totals),
  which needs a (user_id, created_at) composite index.
"""

from __future__ import annotations

import sqlalchemy as sa
from alembic import op

revision = "0016_llm_usage_indexes"
down_revision = "0015_project_members_unique"
branch_labels = None
depends_on = None


def upgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "llm_usage" not in insp.get_table_names():
        return
    indexes = {ix["name"] for ix in insp.get_indexes("llm_usage")}
    if "ix_llm_usage_total_tokens" in indexes:
        op.drop_index("ix_llm_usage_total_tokens", table_name="llm_usage")
    if "ix_llm_usage_user_created" not in indexes:
        op.create_index(
            "ix_llm_usage_user_created",
            "llm_usage",
            ["user_id", "created_at"],
        )


def downgrade() -> None:
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if "llm_usage" not in insp.get_table_names():
        return
    indexes = {ix["name"] for ix in insp.get_indexes("llm_usage")}
    if "ix_llm_usage_user_created" in indexes:
        op.drop_index("ix_llm_usage_user_created", table_name="llm_usage")
    if "ix_llm_usage_total_tokens" not in indexes:
        op.create_index("ix_llm_usage_total_tokens", "llm_usage", ["total_tokens"])
