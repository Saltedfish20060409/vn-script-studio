"""user_settings.context_budget_chars：作者自选的 Agent 上下文预算（字符）

背景（2026-10-01，作者原话）："上下文窗口能不能设置 128K 或者 256K 或者更大，
快到限额提示用户可以切换新对话。"

服务端那条一直是 `AGENT_CONTEXT_MAX_CHARS`（环境变量），作者在界面上够不着；
而"值不值"只有写的人知道：长篇把整章 + 记忆层 + 摘要一起带上，代价是每次调用十几万
输入 token、预填充要等更久。所以给账号设置一条**真被读**的开关：

- 写入时夹进 `[MIN_CONTEXT_MAX_CHARS, MAX_CONTEXT_MAX_CHARS_STREAMED]`；
- 读的时候经 `execution_profile.declared_budget_chars` 进 `context_budget_for_model`，
  仍被**执行档天花板**与**模型窗口**各夹一次（作者只能在这个范围内调，成本不会被打穿）。

与 0030 那次删除的区别写在明处：craft_mode / self_review 两列没人读，是假开关；
这一列有完整的写—读—夹链路，并由 `tests/test_execution_profile.py` 与
`tests/test_context_budget_policy.py` 钉住行为。
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0031_user_context_budget"
down_revision = "0030_drop_dead_user_cols"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS "
            "context_budget_chars INTEGER NOT NULL DEFAULT 0"
        )
    )


def downgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("ALTER TABLE user_settings DROP COLUMN IF EXISTS context_budget_chars")
    )
