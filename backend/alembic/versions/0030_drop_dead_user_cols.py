"""drop user_settings.craft_mode / self_review —— 两列既不写也不读。

背景（2026-09-27 的 prompt/skills 审计）：这两列是"每账号工艺档 / 自检开关"的遗留设计，
但从没接上——
- 没有任何代码写它们（设置页的 craft/self-review 开关根本没做出来）；
- 也没有任何代码读它们：Agent 实际用的是**服务端**设置
  （`projects.py` 的 `craftMode=settings.agent_craft_mode` / `selfReview=settings.agent_self_review`，
  来自环境变量 `AGENT_CRAFT_MODE` / `AGENT_SELF_REVIEW`）。

留着的坏处不是占空间，是**骗人**：看到列名会以为"用户能选工艺档"，于是把真实的
唯一开关（服务端环境变量）忘掉。故回收。

保留 product_events / llm_usage（分析仍在用），这里只回收这两列。
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0030_drop_dead_user_cols"
down_revision = "0029_user_api_context_window"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(sa.text("ALTER TABLE user_settings DROP COLUMN IF EXISTS craft_mode"))
    conn.execute(sa.text("ALTER TABLE user_settings DROP COLUMN IF EXISTS self_review"))


def downgrade() -> None:
    # 回滚只把列加回来（历史取值不恢复——它们从来没被读过，也就没有"历史取值"可言）
    conn = op.get_bind()
    conn.execute(
        sa.text(
            "ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS craft_mode VARCHAR(16) DEFAULT 'auto'"
        )
    )
    conn.execute(
        sa.text(
            "ALTER TABLE user_settings ADD COLUMN IF NOT EXISTS self_review VARCHAR(16) DEFAULT 'auto'"
        )
    )
