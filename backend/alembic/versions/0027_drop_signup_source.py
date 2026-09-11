"""drop users.signup_source — 渠道归因按需求移除。

背景：曾用 ?ref= 做首次归因（bili / douyin / github…），但实际使用中这个维度
判断成本高、噪声大（老用户全落 direct、跨设备会丢、抖音链接难带参），
所以整体移除：前端不再采集、注册不再接收、后台不再按渠道分组。

保留 product_events（激活漏斗仍在用），这里只回收那一列。
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0027_drop_signup_source"
down_revision = "0026_product_events"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text("ALTER TABLE users DROP COLUMN IF EXISTS signup_source")
    )


def downgrade() -> None:
    # 回滚只会把列加回来（历史数据不恢复——它本来就是可选的统计字段）
    conn = op.get_bind()
    conn.execute(
        sa.text("ALTER TABLE users ADD COLUMN IF NOT EXISTS signup_source VARCHAR(64)")
    )
