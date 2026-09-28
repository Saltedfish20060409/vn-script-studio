"""本地 DB 测试跑腿脚本的纯函数部分 + 三处默认值不许分叉的守卫。

为什么值得单独测
----------------
这个脚本存在的唯一理由是修掉"**静默 skip 却看起来全绿**"：测试库不存在时，
需要真库的那几百个用例会被跳过，而跳过是绿的。所以这里钉的不是"能跑"，
而是两件更容易悄悄坏掉的事：

1. URL 改写（SQLAlchemy 驱动标记 → asyncpg 能吃的形式）必须对；
   改错了就是连不上 → 又回到静默 skip。
2. **三处默认值必须同源**：`tests/db_gate.py`（用例怎么连）、
   `docker-compose.yml`（库开在哪个宿主端口）、`scripts/run_db_tests.py`（谁来建库）。
   任一处被改而另两处没跟上，症状都是同一句"连不上，于是全 skip"——
   本项目已经有过一次"两处默认值分叉被跨语言守卫抓出来"的先例
   （见 `frontend/src/api/scanDefaults.test.ts`），这里是同一个模式的第三例。
"""

from __future__ import annotations

import re
from pathlib import Path

from scripts.run_db_tests import (
    DEFAULT_TEST_URL,
    asyncpg_url,
    maintenance_url,
    target_db_name,
)
from tests.db_gate import TEST_DB_URL

BACKEND_ROOT = Path(__file__).resolve().parents[1]
REPO_ROOT = BACKEND_ROOT.parent


def test_asyncpg_url_strips_the_driver_marker():
    assert (
        asyncpg_url("postgresql+asyncpg://u:p@h:5432/db") == "postgresql://u:p@h:5432/db"
    )
    # 已经是裸形式时不该被改坏
    assert asyncpg_url("postgresql://u:p@h:5432/db") == "postgresql://u:p@h:5432/db"


def test_maintenance_url_keeps_host_and_credentials_but_switches_database():
    """建库必须连维护库，否则 `CREATE DATABASE` 本身就跑不了。"""
    assert (
        maintenance_url("postgresql+asyncpg://vnss:vnss@localhost:54102/vnss_test")
        == "postgresql://vnss:vnss@localhost:54102/postgres"
    )


def test_target_db_name_is_read_from_the_url():
    assert target_db_name("postgresql+asyncpg://vnss:vnss@h:1/vnss_test") == "vnss_test"


def test_default_url_matches_the_test_gate():
    """脚本替 `db_gate` 建库，两者必须指向同一个库——否则脚本白建、用例照样 skip。"""
    assert DEFAULT_TEST_URL == TEST_DB_URL, (
        "scripts/run_db_tests.py 与 tests/db_gate.py 的默认测试库不一致："
        f"{DEFAULT_TEST_URL!r} vs {TEST_DB_URL!r}"
    )


def test_compose_publishes_the_port_the_defaults_assume():
    """compose 暴露的宿主端口必须与默认连接串里的端口一致。"""
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    port = re.search(r'"(\d+):5432"', compose)
    assert port, "docker-compose.yml 里找不到 postgres 的宿主端口映射"
    assert f":{port.group(1)}/" in DEFAULT_TEST_URL, (
        f"compose 把 postgres 开在 {port.group(1)}，而默认连接串是 {DEFAULT_TEST_URL}"
    )


def test_compose_mounts_the_init_script_that_creates_test_dbs():
    """没有这个挂载，干净 clone 的人拿不到 vnss_test，DB 层继续静默 skip。"""
    compose = (REPO_ROOT / "docker-compose.yml").read_text(encoding="utf-8")
    assert "init-test-dbs.sh" in compose, "compose 没有挂载建测试库的 initdb 脚本"
    assert "docker-entrypoint-initdb.d" in compose, "挂载点必须是 postgres 的 initdb 目录"
    script = REPO_ROOT / "ops" / "postgres" / "init-test-dbs.sh"
    assert script.is_file(), f"initdb 脚本不在仓库里：{script}"
    body = script.read_text(encoding="utf-8")
    for db in ("vnss_test", "vnss_e2e"):
        assert db in body, f"initdb 脚本没有创建 {db}"


def test_init_script_has_no_crlf():
    """CRLF 的 `#!/bin/sh` 在 Linux 容器里直接报 bad interpreter。

    这条不是洁癖：脚本是在**容器**里执行的，而在 `core.autocrlf=true` 的 Windows
    检出上它会被写成 CRLF——本地看不出问题，CI/容器里才炸。
    """
    raw = (REPO_ROOT / "ops" / "postgres" / "init-test-dbs.sh").read_bytes()
    assert b"\r\n" not in raw, "initdb 脚本含 CRLF，容器里会 bad interpreter"
    attrs = REPO_ROOT / ".gitattributes"
    assert attrs.is_file(), "缺少 .gitattributes，Windows 检出会把 .sh 写成 CRLF"
    assert "*.sh text eol=lf" in attrs.read_text(encoding="utf-8")
