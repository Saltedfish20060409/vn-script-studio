"""在**本机**把"需要真库"的那一层跑起来：确保测试库存在 → 跑 pytest。

为什么需要这个脚本
------------------
README 过去让读者跑 `python deploy/run_db_tests.py`，而 `deploy/` 是被 `.gitignore`
排除的（`.gitignore` 里那条 `deploy/`）——干净 clone 的人根本拿不到它。
更糟的是那个脚本其实是**作者在服务器上走 SSH** 跑的（需要 `SSH_HOST`/`SSH_USER`），
对本地开发毫无用处。于是"照着 README 做"的实际结果是：

    pytest tests/  →  全绿

而这份绿是假的：需要真库的几百个用例全部静默 skip 掉了
（skip 理由原文是 `PostgreSQL test DB unreachable (set DATABASE_URL_TEST)`），
偏偏那一层才是最能抓住真实缺陷的（jsonb 键序导致的指纹漂移、注册/重发邮件的静默失败、
快照与行锁的并发语义）。这个脚本只依赖 `docker compose up -d` 起出来的库。

用法
----
    docker compose up -d
    cd backend
    python scripts/run_db_tests.py                 # 建库（如缺）+ 跑全部用例
    python scripts/run_db_tests.py -k test_api_    # 透传 pytest 参数
    python scripts/run_db_tests.py --ensure-only   # 只建库，不跑测试（CI 准备用）

退出码与 pytest 一致；建库失败会明确报错，不会退化成"跑了一遍全 skip 的绿"。
"""

from __future__ import annotations

import argparse
import asyncio
import os
import subprocess
import sys
from urllib.parse import urlsplit, urlunsplit

#: 与 tests/db_gate.py 的默认值、以及 docker-compose.yml 暴露的宿主端口保持一致。
#: 三处必须同源，否则又回到"连不上就静默 skip"那件事上。
DEFAULT_TEST_URL = "postgresql+asyncpg://vnss:vnss@localhost:54102/vnss_test"


def asyncpg_url(sqlalchemy_url: str) -> str:
    """把 SQLAlchemy 驱动形式的 URL 转成 asyncpg 能直接吃的形式。

    `postgresql+asyncpg://…` 里的 `+asyncpg` 是 SQLAlchemy 的驱动标记，
    asyncpg 自己不认（会当成数据库名解析失败）。CI 的 integration.yml 里
    也是同一个处理（`replace("postgresql+asyncpg://", "postgresql://")`）。
    """
    return sqlalchemy_url.replace("postgresql+asyncpg://", "postgresql://", 1)


def maintenance_url(test_url: str) -> str:
    """同主机/凭据，但连到 `postgres` 维护库——只有连上它才能 CREATE DATABASE。"""
    parts = urlsplit(asyncpg_url(test_url))
    return urlunsplit((parts.scheme, parts.netloc, "/postgres", "", ""))


def target_db_name(test_url: str) -> str:
    name = urlsplit(asyncpg_url(test_url)).path.lstrip("/")
    if not name:
        raise SystemExit(f"DATABASE_URL_TEST 里没有库名：{test_url!r}")
    return name


async def ensure_database(test_url: str) -> str:
    """确保目标库存在；返回一句可打印的说明。已存在时是幂等的。"""
    import asyncpg

    db = target_db_name(test_url)
    conn = await asyncpg.connect(maintenance_url(test_url))
    try:
        exists = await conn.fetchval("SELECT 1 FROM pg_database WHERE datname = $1", db)
        if exists:
            return f"测试库 {db} 已存在"
        # 库名来自连接串而不是用户输入，但仍走标识符引号，避免奇怪名字拼坏 SQL
        await conn.execute(f'CREATE DATABASE "{db}"')
        return f"已创建测试库 {db}"
    finally:
        await conn.close()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="本地跑需要真库的后端测试")
    parser.add_argument(
        "--ensure-only",
        action="store_true",
        help="只确保测试库存在，不跑 pytest（CI 准备阶段用）",
    )
    parser.add_argument("pytest_args", nargs="*", help="透传给 pytest 的参数")
    args = parser.parse_args(argv)

    test_url = os.environ.get("DATABASE_URL_TEST") or DEFAULT_TEST_URL
    os.environ["DATABASE_URL_TEST"] = test_url

    try:
        print(f"[run_db_tests] 目标：{test_url}")
        print(f"[run_db_tests] {asyncio.run(ensure_database(test_url))}")
    except Exception as exc:  # noqa: BLE001 — 要把原因说清楚，而不是让用例静默 skip
        print(
            f"[run_db_tests] 连不上数据库：{type(exc).__name__}: {exc}\n"
            "  先起库：docker compose up -d\n"
            f"  或把 DATABASE_URL_TEST 指到已有实例（当前：{test_url}）",
            file=sys.stderr,
        )
        return 2

    if args.ensure_only:
        return 0

    here = os.path.dirname(os.path.abspath(__file__))
    backend_root = os.path.dirname(here)
    env = dict(os.environ)
    env.setdefault("PYTHONPATH", backend_root)
    cmd = [sys.executable, "-m", "pytest", "tests/", "-q", *args.pytest_args]
    print(f"[run_db_tests] {' '.join(cmd)}")
    return subprocess.call(cmd, cwd=backend_root, env=env)


if __name__ == "__main__":
    raise SystemExit(main())
