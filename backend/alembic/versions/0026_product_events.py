"""product_events + users.signup_source — 最小产品埋点与渠道归因。

- product_events：只记「谁在什么时候触发了哪个关键动作」（不记正文内容），
  用于算激活漏斗（注册 → 建项目 → 首次写作 → 首次 AI → 试玩/导出）。
- users.signup_source：首次归因渠道（?ref=bili / douyin / github …），
  注册时写入，用于回答"哪条视频真的带来了用户"。
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0026_product_events"
down_revision = "0025_users_token_version"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS product_events (
              id VARCHAR(36) PRIMARY KEY,
              user_id VARCHAR(36) REFERENCES users(id) ON DELETE CASCADE,
              name VARCHAR(48) NOT NULL,
              props JSONB NOT NULL DEFAULT '{}'::jsonb,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
    )
    # 漏斗查询按 (name, created_at) 过滤；按用户看时序也常用。
    conn.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_product_events_name_created "
            "ON product_events (name, created_at DESC)"
        )
    )
    conn.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_product_events_user_name "
            "ON product_events (user_id, name)"
        )
    )
    conn.execute(
        sa.text(
            """
            ALTER TABLE users
              ADD COLUMN IF NOT EXISTS signup_source VARCHAR(64)
            """
        )
    )


def downgrade() -> None:
    op.execute("DROP INDEX IF EXISTS ix_product_events_user_name")
    op.execute("DROP INDEX IF EXISTS ix_product_events_name_created")
    op.execute("DROP TABLE IF EXISTS product_events")
    op.execute("ALTER TABLE users DROP COLUMN IF EXISTS signup_source")
