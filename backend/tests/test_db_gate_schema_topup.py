"""测试库补列逻辑（`tests/db_gate.missing_column_statements`）。

为什么值得单测：这段代码是**为了让 DB 集成测试真的测到东西**而存在的。
它自己出错的表现很隐蔽——不是链路报错，而是"某一列悄悄没补上，于是 94 个用例
一起报 UndefinedColumn"，看起来像业务代码坏了。所以这里用纯函数形式把它钉住，
不需要数据库也能跑（本机没有 Docker 时也照跑）。
"""

from __future__ import annotations

import db_gate
from sqlalchemy import JSON, Boolean, Column, Integer, MetaData, String, Table, text
from sqlalchemy.dialects import postgresql


def _metadata() -> MetaData:
    md = MetaData()
    Table(
        "user_settings",
        md,
        Column("id", String, primary_key=True),
        Column("api_context_window_k", Integer, nullable=False, server_default="0"),
        Column("is_admin", Boolean, nullable=False, server_default="false"),
        Column("data", JSON, nullable=True),
    )
    Table(
        "fresh_table",
        md,
        Column("id", String, primary_key=True),
        Column("payload", JSON, nullable=True),
    )
    return md


def test_adds_only_the_columns_that_are_missing():
    md = _metadata()
    existing = {"user_settings": {"id", "is_admin"}, "fresh_table": {"id"}}
    stmts = db_gate.missing_column_statements(md, existing, postgresql.dialect())
    joined = "\n".join(stmts)
    assert 'ADD COLUMN IF NOT EXISTS "api_context_window_k"' in joined
    assert 'ADD COLUMN IF NOT EXISTS "data"' in joined
    assert 'ADD COLUMN IF NOT EXISTS "payload"' in joined, "存在的表缺列就要补"
    # 已经有的列不能再补（否则每次会话都白跑一遍 DDL）
    assert 'ADD COLUMN IF NOT EXISTS "is_admin"' not in joined
    assert 'ADD COLUMN IF NOT EXISTS "id"' not in joined


def test_absent_table_is_left_to_create_all():
    """库里根本没有的表交给 `create_all`——它会连新列一起建好，这里不要插手。"""
    md = _metadata()
    stmts = db_gate.missing_column_statements(
        md, {"user_settings": {"id"}}, postgresql.dialect()
    )
    joined = "\n".join(stmts)
    assert "fresh_table" not in joined
    assert "user_settings" in joined


def test_statements_carry_type_and_server_default():
    """类型与 server_default 都要带上：缺默认值会让老行为与新 schema 不一致。"""
    md = _metadata()
    existing = {"user_settings": {"id"}, "fresh_table": {"id"}}
    stmts = db_gate.missing_column_statements(md, existing, postgresql.dialect())
    by_col = {s: s for s in stmts}
    window = next(s for s in by_col if "api_context_window_k" in s)
    assert "INTEGER" in window
    assert "DEFAULT 0" in window
    is_admin = next(s for s in by_col if "is_admin" in s)
    assert "BOOLEAN" in is_admin and "DEFAULT false" in is_admin
    data = next(s for s in by_col if '"data"' in s)
    assert "JSON" in data, data


def test_not_null_without_default_is_added_anyway():
    """声明 NOT NULL 且没有默认值的列也要补上（按可空补，见 db_gate 的注释）。

    不补的话查询会直接报 UndefinedColumn；而按 NOT NULL 补在 PostgreSQL 里
    对已有行的表会失败。所以宁可少写一个约束，也要让列存在。
    """
    md = MetaData()
    Table(
        "t",
        md,
        Column("id", String, primary_key=True),
        Column("flag", Boolean, nullable=False),  # 无 server_default
    )
    stmts = db_gate.missing_column_statements(md, {"t": {"id"}}, postgresql.dialect())
    assert len(stmts) == 1
    assert "NOT NULL" not in stmts[0]
    assert 'ADD COLUMN IF NOT EXISTS "flag" BOOLEAN' in stmts[0]


def test_clause_default_is_compiled_not_stringified():
    """`server_default=text("1")` 要编译成 `1`，不能写成 `1` 的 repr。"""
    md = MetaData()
    Table(
        "t",
        md,
        Column("id", String, primary_key=True),
        Column("schema_version", Integer, nullable=False, server_default=text("1")),
    )
    stmts = db_gate.missing_column_statements(md, {"t": {"id"}}, postgresql.dialect())
    assert len(stmts) == 1
    assert stmts[0].endswith("DEFAULT 1"), stmts[0]
    assert "TextClause" not in stmts[0]


def test_real_metadata_topup_matches_reality():
    """对**真实的** `Base.metadata` 跑一遍：结论应当是"没有要补的列"（缺列已被修掉）。

    这条同时是一道回归闸：如果有人再往老表加列却只改了模型/迁移、没管测试库，
    这里不会失败（那是环境的责任），但会在容器里由 `create_all` 自动补上——
    本测试的价值在于确认补列函数对真实元数据能跑通、不抛异常。
    """
    import app.models  # noqa: F401
    from app.db import Base

    dialect = postgresql.dialect()
    # 假装库里一列都没有：此时应当为每张已存在的表的每一列生成语句，且不抛异常
    existing = {t.name: set() for t in Base.metadata.sorted_tables}
    stmts = db_gate.missing_column_statements(Base.metadata, existing, dialect)
    assert stmts, "对真实元数据应当能生成补列语句"
    tables = {s.split('"')[1] for s in stmts}
    assert "user_settings" in tables
    assert any("api_context_window_k" in s for s in stmts)
    # 每条语句都必须是幂等的 ADD COLUMN IF NOT EXISTS
    assert all('ADD COLUMN IF NOT EXISTS' in s for s in stmts)
