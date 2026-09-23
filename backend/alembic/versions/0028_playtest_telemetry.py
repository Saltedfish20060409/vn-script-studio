"""playtest_runs / playtest_choices / project_telemetry_settings — 读者行为建模。

补齐的缺口：此前全仓没有任何面向读者的建模。试玩器是纯内存播放器
（frontend/src/components/ScriptPlayer.tsx 不落任何状态），唯一的读者侧埋点是
product_events 里的 playtest_opened —— 它只能回答"有没有人点过试玩"，
答不出**玩家在哪个菜单选了哪一项、走到哪个结局、在第几章停下**。

三张表的分工：

- ``playtest_runs``：一次试玩一行。``(project_id, client_run_id)`` 唯一 —— 幂等依据。
- ``playtest_choices``：一次选择一行。``(run_id, seq)`` 唯一 —— 同一 run 内每个
  序号最多一行，重复上报只补缺失的 seq。
- ``project_telemetry_settings``：采集开关，**默认 false**（没有行 = 不采集）。

隐私取舍（重要）：这三张表里**没有任何自由文本列**。所有字符串列只放 ASCII 标识符
（chapter_id / menu_id / label / ending_label / client_run_id），写入前由
``app/services/playtest_telemetry.sanitize_identifier`` 做白名单校验；也**不存**
IP / UA / 指纹 / user_id。台词、选项文案、旁白因此没有容器可落。

downgrade 直接丢表：这些是纯统计数据，回滚即视为放弃采集（历史数据不迁移）。
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0028_playtest_telemetry"
down_revision = "0027_drop_signup_source"
branch_labels = None
depends_on = None


def upgrade() -> None:
    conn = op.get_bind()
    conn.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS playtest_runs (
              id VARCHAR(36) PRIMARY KEY,
              project_id VARCHAR(64) NOT NULL REFERENCES projects(id) ON DELETE CASCADE,
              client_run_id VARCHAR(64) NOT NULL,
              started_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              ended_at TIMESTAMPTZ,
              chapter_count INTEGER NOT NULL DEFAULT 0,
              choice_count INTEGER NOT NULL DEFAULT 0,
              ending_label VARCHAR(64),
              created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              CONSTRAINT uq_playtest_runs_project_client UNIQUE (project_id, client_run_id)
            )
            """
        )
    )
    # 分析按工程 + 时间取最近若干次试玩；漏斗也常按 started_at 排序。
    conn.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_playtest_runs_project_started "
            "ON playtest_runs (project_id, started_at DESC)"
        )
    )
    conn.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS playtest_choices (
              id VARCHAR(36) PRIMARY KEY,
              run_id VARCHAR(36) NOT NULL REFERENCES playtest_runs(id) ON DELETE CASCADE,
              seq INTEGER NOT NULL,
              chapter_id VARCHAR(64) NOT NULL DEFAULT '',
              label VARCHAR(64) NOT NULL DEFAULT '',
              menu_id VARCHAR(64) NOT NULL DEFAULT '',
              choice_index INTEGER NOT NULL DEFAULT -1,
              condition_passed BOOLEAN NOT NULL DEFAULT true,
              created_at TIMESTAMPTZ NOT NULL DEFAULT now(),
              CONSTRAINT uq_playtest_choices_run_seq UNIQUE (run_id, seq)
            )
            """
        )
    )
    conn.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_playtest_choices_run_seq "
            "ON playtest_choices (run_id, seq)"
        )
    )
    # 选项占比按 (menu_id, choice_index) 聚合
    conn.execute(
        sa.text(
            "CREATE INDEX IF NOT EXISTS ix_playtest_choices_menu_choice "
            "ON playtest_choices (menu_id, choice_index)"
        )
    )
    conn.execute(
        sa.text(
            """
            CREATE TABLE IF NOT EXISTS project_telemetry_settings (
              project_id VARCHAR(64) PRIMARY KEY
                REFERENCES projects(id) ON DELETE CASCADE,
              enabled BOOLEAN NOT NULL DEFAULT false,
              updated_at TIMESTAMPTZ NOT NULL DEFAULT now()
            )
            """
        )
    )


def downgrade() -> None:
    op.execute("DROP TABLE IF EXISTS project_telemetry_settings")
    op.execute("DROP INDEX IF EXISTS ix_playtest_choices_menu_choice")
    op.execute("DROP INDEX IF EXISTS ix_playtest_choices_run_seq")
    op.execute("DROP TABLE IF EXISTS playtest_choices")
    op.execute("DROP INDEX IF EXISTS ix_playtest_runs_project_started")
    op.execute("DROP TABLE IF EXISTS playtest_runs")
