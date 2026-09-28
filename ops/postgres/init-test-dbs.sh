#!/bin/sh
# 为本地开发/测试创建**额外的**数据库。
#
# 为什么需要它：postgres 镜像只按 POSTGRES_DB 建一个库（`vnss`），而测试那一层
# 找的是 `vnss_test`（`backend/tests/db_gate.py` 的默认值，宿主端口 54102）。
# 结果是一个干净 clone 的人跑 `pytest tests/` 会得到"全绿"——但那是假的：
# 需要真库的那几百个用例全部**静默 skip** 掉了，而那恰恰是这个仓库里最能抓住
# 真实缺陷的一层（jsonb 键序导致的指纹漂移、注册邮件的静默失败、行锁并发语义）。
#
# 只在**首次初始化**（数据卷为空）时执行。已有旧卷的人不会自动获得这两个库，
# 需要手工建一次，或在确认可丢弃数据后 `docker compose down -v`：
#   docker compose exec postgres createdb -U vnss vnss_test
#   docker compose exec postgres createdb -U vnss vnss_e2e
set -e

create_db() {
    db="$1"
    # 用 SELECT 1 判断已存在，避免重复初始化时报错中断（幂等）
    exists=$(psql -v ON_ERROR_STOP=1 -tAc \
        "SELECT 1 FROM pg_database WHERE datname='${db}'" --username "$POSTGRES_USER")
    if [ "$exists" = "1" ]; then
        echo "init-test-dbs: ${db} 已存在，跳过"
    else
        echo "init-test-dbs: 创建 ${db}"
        createdb --username "$POSTGRES_USER" "$db"
    fi
}

# vnss_test：后端 DB 集成测试（DATABASE_URL_TEST 的默认目标）
create_db vnss_test
# vnss_e2e：前端 Playwright e2e 用的库（见 frontend/playwright.config.ts）
create_db vnss_e2e
