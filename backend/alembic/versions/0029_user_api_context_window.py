"""user_settings.api_context_window_k — 用户声明的模型窗口（千 token）。

为什么要这一列：上下文预算要按**模型窗口**夹一次（否则小窗口模型会被上游直接拒答，
用户什么都拿不到），而预设表收不全——自建端点、自部署模型、厂商新名字都可能不在表里。
服务端只能按 `AGENT_UNKNOWN_MODEL_WINDOW_K` 给一个保守假设；真知道窗口的是用户自己，
所以让他声明一次，之后所有走他凭据的请求都用这个值。

0 = 自动（预设表 → 服务端保守假设）；负值 = 明确"不用夹"。
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0029_user_api_context_window"
down_revision = "0028_playtest_telemetry"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            ALTER TABLE user_settings
              ADD COLUMN IF NOT EXISTS api_context_window_k INTEGER NOT NULL DEFAULT 0
            """
        )
    )


def downgrade() -> None:
    op.execute("ALTER TABLE user_settings DROP COLUMN IF EXISTS api_context_window_k")
