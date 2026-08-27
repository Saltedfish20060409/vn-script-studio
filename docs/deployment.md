# 部署与运维手册（VN Script Studio）

> 面向**新服务器部署 / 迁移 / 排障**的一线操作记录。部署脚本在本地 `deploy/`（gitignored，不入库），
> 本手册是它的「人肉文档」，换机器/换人时先读这里。

## 1. 架构

- **前端**：React SPA（Vite 构建），nginx 托管静态文件 + 反代 API
- **后端**：FastAPI async + SQLAlchemy asyncpg + PostgreSQL 16 + Redis 7（SSE 跨 worker 桥）
- **音乐**：vnss-ncm（binaryify/netease_cloud_music_api），backend 通过 `NETEASE_API_URL` 调用
- **全部容器化**（Docker Compose），`/opt/vn-script-studio` 为根目录

## 2. 服务器初始化（全新机器，约 10 分钟）

```bash
# 1) 上传部署素材并执行初始化脚本（装 Docker、生成密钥、搭目录、写 compose/.env/nginx）
scp deploy/setup_server.sh root@<IP>:/tmp/
scp deploy/docker-compose.yml root@<IP>:/tmp/
scp frontend/nginx.conf root@<IP>:/tmp/
ssh root@<IP> "sudo bash /tmp/setup_server.sh <域名>"
#   脚本内找不到 nginx.conf 时手动补：cp /tmp/nginx.conf /opt/vn-script-studio/nginx.conf

# 2) 权限（非 root 用户部署时）
sudo usermod -aG docker <user> && sudo chown -R <user>:<user> /opt/vn-script-studio

# 3) 修改 .env 业务值（见下），并强制重建 api 容器
#    ⚠️ 改 .env 后必须 `docker compose up -d --force-recreate api`——
#    `docker compose restart` 不会重读 .env（容器环境在创建时固化）

# 4) 从开发机部署代码（见第 4 节）
```

## 3. 环境变量（/opt/vn-script-studio/.env）

| 变量 | 说明 |
|---|---|
| `POSTGRES_PASSWORD` | 由 setup 脚本随机生成 |
| `DATABASE_URL` / `REDIS_URL` | 容器内服务名连接（`@postgres:5432` / `redis://redis:6379/0`） |
| `SECRET_KEY` | setup 随机生成；**生产必须改**（默认值会被 config 拒绝） |
| `CORS_ORIGINS` / `PUBLIC_APP_URL` | 正式域名；备案前可临时用 `http://<IP>` |
| `DEEPSEEK_API_KEY/BASE_URL/MODEL` | **服务端兜底 LLM**（用户无 key 时用）。当前指向智谱免费模型：`https://open.bigmodel.cn/api/paas/v4` + `glm-4-flash-250414`。换模型：改 MODEL 后 `up -d --force-recreate api` |
| `LLM_SHARED_KEY_DAILY_CAP` | 服务端 key 每用户每天 token 上限（现 200 万） |
| `LLM_PROVIDER` | `openai`（默认）/ `ollama` |
| `RESEND_API_KEY` / `RESEND_FROM_EMAIL` | 事务邮件；域名需在 Resend 验证（含 send 子域 MX/SPF、resend._domainkey、_dmarc） |
| `AUTH_AUTO_VERIFY` | `false` = 注册须邮箱验证（生产）；`true` = 免验证（本地/测试） |
| `ADMIN_USERNAMES` | 管理员（逗号分隔）；留空 = 首个注册者自动升管 |
| `NETEASE_API_URL` | 音乐代理地址 `http://vnss-ncm:3000` |
| `ICP_BEIAN_NUMBER` / `GONGAN_BEIAN_NUMBER` | 备案号（通过后填写，网站底部自动显示） |

## 4. 部署代码（开发机执行）

```bash
# PowerShell（凭据按次内联，不要长期保存在环境里）
$env:SSH_HOST='<IP>'; $env:SSH_USER='root'; $env:SSH_PASS='<密码>'
$env:PIP_INDEX_URL='https://mirrors.aliyun.com/pypi/simple/'   # 大陆服务器必须（连不上 pypi.org）

python deploy/pack.py            # 打包 backend.tar.gz + dist.tar.gz
python deploy/push.py --backend --frontend
```

- 首次部署：push.py 假定 compose/.env/nginx 已就位（见第 2 节）；后端镜像首次构建需拉基础镜像+装依赖，**约 5-15 分钟**
- 之后每次：pack + push 一条命令，前端原子切换（dist.new → mv），后端 `compose build && up -d api`

## 5. 历史踩坑（务必先读）

| 坑 | 现象 | 修复 |
|---|---|---|
| **`alembic.ini` 漏打包** | 全新服务器 `docker compose build api` 报 `/alembic.ini not found` | pack.py 与 push.py 的打包清单都要含 `alembic.ini`（旧服务器因 tar 覆盖残留未暴露） |
| **`/v4/v1` 双重路径** | 智谱 GLM 预设请求 404 | `llm_http._chat_url` 归一化：裸根→`/v1/chat/completions`；`/v1` 或 `/v4` 前缀→直接 `+ /chat/completions`；已含 `/chat/completions` 原样用 |
| **大陆连不上 PyPI** | 构建时 pip 报 `No matching distribution` | Dockerfile 支持 `ARG PIP_INDEX_URL`；构建加 `--build-arg PIP_INDEX_URL=https://mirrors.aliyun.com/pypi/simple/` |
| **上传断点续传拼坏** | 远端 tar 尾部垃圾 → 解包失败 | push.py 上传前 `rm -f /tmp/vnss-bk/bk.part* /tmp/vnss-ds/ds.part*`（内容变化时按大小 resume 会把新旧字节拼一起） |
| **长构建被掐断** | paramiko 报 socket.timeout | remote.py 的 run() 对 channel 设 `settimeout(max(timeout,900))` |
| **web 端口未映射** | 裸机访问不到 80 | deploy/docker-compose.yml 的 web 服务加 `ports: ["80:80"]`（旧机靠 Coolify 反代所以没暴露） |
| **`docker compose restart` 不重读 .env** | 改 env 后容器仍用旧值 | 必须 `up -d --force-recreate <svc>` |
| **Resend 发信 403 (error 1010)** | 验证/重置邮件发不出（旧站可能一直静默失败） | Resend API 在 Cloudflare 后，默认 python UA 被拦；`email_send.py` 需带品牌 UA |
| **检查点写入连错库** | 测试环境 run_state 静默丢失 | 检查点会话工厂从请求会话 `db.bind` 派生（不能用 `app.db.AsyncSessionLocal`） |
| **JSONB 原地修改不落库** | run_state 状态更新 commit 后丢失 | `Mapped[dict]` 列不追踪原地修改，必须重建 dict 整体赋值 |

## 6. 备份 / 恢复

- **每日 03:00**（root crontab）：`/opt/vn-script-studio/scripts/backup_pg.sh` → pg_dump 到 backups/，保留 14 份
- **异地**：开发机 `python deploy/pull_backup.py`（需 SSH 凭据）拉取最新 dump 到本地 deploy/backups/
- **恢复演练**：
  ```bash
  LATEST=$(ls -1t /opt/vn-script-studio/backups/*.dump | head -1)
  docker cp $LATEST vnss-postgres:/tmp/restore.dump
  docker exec vnss-postgres createdb -U vnss vnss_restore_test
  docker exec vnss-postgres pg_restore -U vnss -d vnss_restore_test /tmp/restore.dump
  # 验证后删除临时库
  ```

## 7. 迁移到新服务器

1. 新机跑第 2 节初始化
2. 旧机最新 dump → 新机恢复（`docker compose exec postgres pg_restore`）
3. 复制旧机 `.env`（业务值）→ 新机
4. 开发机 `pack.py + push.py` 部署代码
5. 域名 DNS 指向新 IP（Cloudflare 改 A 记录）
6. 验证 health + 页面 hash + 登录

## 8. 免费模型兜底（当前配置）

- 服务端兜底：智谱 `glm-4-flash-250414`（免费、json 模式可用）
- `glm-4.7-flash` 免费档曾持续 429（访问量过大）——可用后再切
- 免费档是**限速**（RPM/并发）不是限总量：并发闸(16) + 240次/时 + 200 万/天 已兜住
- 兜底仅作试用通道，用户自带 key 才是主路
