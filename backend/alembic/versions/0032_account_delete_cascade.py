"""account delete cascade — 让「删除账号」能一条 DELETE 清干净

新增「设置 → 账号 → 删除账号」（`DELETE /api/v1/auth/me`）后，删除路径依赖数据库
级联把自己名下的数据一起带走。真实库里有两处缺口，这次一并补上：

1. ``projects.owner_id → users.id`` **没有** ON DELETE CASCADE。于是
   `DELETE FROM users` 只要名下还有项目就直接外键报错（实测：删号 500）。
2. ``user_settings.user_id → users.id`` 同样没有级联，设置了主题 / Key 的用户删不掉。
3. ``chapter_memory_slices.archive_id → chapter_memory_archives.id`` 也没有级联。
   这一层不属于「users」链，但会挡住同一条路径：删项目时档案级联删除，切片却
   还指着档案。0012_project_cascade 只补了指向 ``projects.id`` 的那一层，漏了
   archive → slice —— 也就是说**带章节记忆存档的项目，此前删项目本身就会失败**。

其余指向 users 的外键已经是正确的：``auth_email_tokens`` / ``product_events``
是 CASCADE，``error_reports`` 是 SET NULL（错误报告要留在库里做诊断，只脱敏作者）。

没有外键的软引用（``agent_jobs.user_id`` / ``llm_usage.user_id`` /
``project_members.user_id`` / ``chapter_locks.user_id`` / ``project_comments.user_id``
/ ``project_invites.created_by``）由 `app.services.account_delete` 显式清理。
"""

from __future__ import annotations

import sqlalchemy as sa

from alembic import op

revision = "0032_account_delete_cascade"
down_revision = "0031_user_context_budget"
branch_labels = None
depends_on = None

# (表, 列, 被引用表, 被引用列)
_CASCADE_TARGETS = [
    ("projects", "owner_id", "users", "id"),
    ("user_settings", "user_id", "users", "id"),
    ("chapter_memory_slices", "archive_id", "chapter_memory_archives", "id"),
]


def _rewrite_fk(table: str, column: str, ref_table: str, ref_col: str, ondelete):
    """把 table.column → ref_table.ref_col 这条外键重建成指定 ON DELETE 行为。"""
    bind = op.get_bind()
    insp = sa.inspect(bind)
    if table not in insp.get_table_names():
        return
    target = None
    for fk in insp.get_foreign_keys(table):
        if fk.get("referred_table") != ref_table:
            continue
        if column in (fk.get("constrained_columns") or []):
            target = fk
            break
    if target is None:
        # 表结构不由本迁移负责建（可能是半迁移库），没有这条外键就没什么可改的。
        return
    current = (target.get("options") or {}).get("ondelete")
    if (current or "").upper() == (ondelete or "").upper():
        return
    name = target["name"]
    op.drop_constraint(name, table, type_="foreignkey")
    op.create_foreign_key(
        name,
        table,
        ref_table,
        local_cols=[c for c in target["constrained_columns"]],
        remote_cols=[c for c in target["referred_columns"]],
        ondelete=ondelete,
    )


def upgrade() -> None:
    for table, column, ref_table, ref_col in _CASCADE_TARGETS:
        _rewrite_fk(table, column, ref_table, ref_col, "CASCADE")


def downgrade() -> None:
    # 回到「没有 ON DELETE 行为」（RESTRICT 语义）：删号接口会因此失败，
    # 但库结构与 0031 一致。
    for table, column, ref_table, ref_col in _CASCADE_TARGETS:
        _rewrite_fk(table, column, ref_table, ref_col, None)
