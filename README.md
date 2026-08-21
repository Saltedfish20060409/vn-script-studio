# VN Script Studio

面向**视觉小说 / 轻小说向剧本**的 AI 辅助写作工作室。  
默认用自然语言写剧本，需要上演时再切到 Ren'Py（`.rpy`）。

应用内顶栏 **帮助**，以及公开页 [帮助与 FAQ](https://studio.nexesr.top/help)。AI 生成内容请自行审稿后再用于发行。

---

## 给作者

在线试用：[studio.nexesr.top](https://studio.nexesr.top)（需注册并验证邮箱）。

自建见下方「给开发者」。

### 怎么写

- **写作页默认是自然语言剧本**：旁白直接写，对白写成「角色名：台词」。
- 同一编辑器可切到 **RPY**：两份稿互不覆盖。RPY 可手写，也可点「根据剧本生成」（设置里填了模型 Key 则走 AI，否则用规则解析）。
- 剧本改过、RPY 没重生时会提示过期。
- **顶栏导出跟当前视图**：剧本 → `.docx`，RPY → `.rpy`。整包工程 / Markdown / Ren'Py 项目 zip 在「项目 → 导出」。
- **试玩读的是 RPY 稿**。只写了自然语言时，先生成或手写脚本再试玩。

### 其它常用入口

| 入口 | 做什么 |
|------|--------|
| 设定 | 角色卡、世界观、设定库 |
| 地图 | 从剧本抽地点，点地点可跳回写作 |
| 角色工坊 | 定声音 → 思维包 → 试聊。手机上点「换角色」打开名单 |
| Agent | 桌面多在右下角；手机是屏幕侧边贴片 |
| 齿轮（设置） | 外观、自己的模型 Key、用量 |

忘记密码走登录页找回。协作在顶栏「协作」：邀请成员、锁章节、批注。

---

## 给开发者

前后端分离：FastAPI + React (Vite) + PostgreSQL。

### 系统形态

```
vn-script-studio/
├── docker-compose.yml   # PostgreSQL 16
├── backend/             # FastAPI + 全部业务逻辑（原 @vnss/core）
├── frontend/            # Vite + React SPA
└── examples/            # 示例工程
```

| 层 | 技术 |
|----|------|
| 后端 | FastAPI、SQLAlchemy 2、Alembic、JWT、httpx |
| 前端 | Vite 6、React 19、React Router、CSS Modules |
| 数据库 | PostgreSQL 16（Docker） |
| LLM | OpenAI 兼容 Chat Completions（默认 DeepSeek） |

### 快速开始

日常开发（Windows）可一键启动：

```powershell
# 在仓库根目录
.\dev.ps1
# 或双击 / 运行
.\dev.bat
```

会：必要时 `docker compose up -d` → 新开窗口跑后端 `:8000` → 新开窗口跑前端 `:5173` → 打开浏览器。  
已在跑的端口会跳过。加 `-SkipDocker` 可跳过数据库；`-NoBrowser` 不自动开页。

首次仍需装好依赖（只需一次）：

```bash
# 数据库
docker compose up -d

# 后端
cd backend
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env          # 或 cp .env.example .env
# 编辑 .env：DATABASE_URL 端口需与 docker-compose 一致（默认宿主机 54102）
# 填入 DEEPSEEK_API_KEY 以启用 Agent
# 填入 RESEND_API_KEY 以启用注册验证 / 找回密码邮件

# 前端
cd ../frontend
npm install
```

手动分别启动时：

```bash
# 后端（backend/）
set PYTHONPATH=.
uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# 前端（frontend/）
npm run dev
```

打开 http://localhost:5173 ，注册账号后即可使用。Vite 已将 `/api` 代理到后端。

本地若未配 Resend，注册会返回 503。只跑前端 e2e 时后端会设 `AUTH_AUTO_VERIFY=true`，新账号直接已验证。

Postgres 用 Docker 常驻即可，不必每次重建；每次写代码通常只需前后端两个进程（或跑一次 `dev.ps1`）。

### 主要 API（`/api/v1`）

| 分组 | 说明 |
|------|------|
| `POST /auth/register` `POST /auth/login` `GET /auth/me` | JWT 认证（注册需邮箱验证） |
| `GET/POST /projects` … | 云端剧本库 CRUD、导入、导出、快照（content-addressed） |
| `POST /projects/{id}/generate-rpy` | 自然语言剧本 → Ren'Py（有 Key 走 LLM，否则规则解析） |
| `POST /projects/{id}/agent` | 审稿 Agent（多步 loop + trace；服务端 apply） |
| `GET/PUT …/agent/session` · `…/agent/conversations` | 对话 / 记忆 / 多会话 / 撤回栈 |
| `POST …/agent/chapter-revise` · `…/apply` | 章节回炉（可 async_mode → job） |
| `POST …/map/extract` · `…/extract/accept` | 地图智能提取预览与勾选写入 |
| `POST …/analysis/facts/*` · `…/lint` · `…/branch-tree` | 事实总线与分支树 |
| `POST …/voice-check` | 语气检查（写入 voiceReports） |
| `GET/POST …/memory/*` | 章节记忆归档 |
| `POST /harness/*` · `POST /pipeline/*` · `GET …/jobs/{id}` | 文风体检 / 流水线 / 异步任务轮询 |
| `GET/PUT …/mentors` · `…/lenses` · `…/brainstorm` | 写作导师 / 作家透镜 / 多视角脑暴 |
| `…/character-voice/*` | 角色工坊语料与思维卡 |
| `…/lore/*` | 萌百/设定卡（服务端与 Agent 用；前端无独立 UI） |
| `POST …/shares` · `GET /shares/{token}` | 真云端只读分享 |
| `GET/PUT /settings` | 用户设置（API Key 服务端加密，回写脱敏） |

完整契约见运行中的 [OpenAPI](http://localhost:8000/docs)。

### CLI

```bash
cd backend
set PYTHONPATH=.
python -m app demo out.json
python -m app export out.json out.rpy
python -m app ai out.json continue --instruction "更压抑"
# 生成质量评测（对写作任务跑目标模型，用确定性 lint 自动评分）
python -m app eval
python -m app eval -m qwen2.5:7b --base-url http://localhost:11434 --api-key ollama
```

### 环境变量（backend/.env）

| 变量 | 说明 |
|------|------|
| `DATABASE_URL` | 默认 `postgresql+asyncpg://vnss:vnss@localhost:54102/vnss`（宿主机端口与 docker-compose 一致） |
| `SECRET_KEY` | JWT 签名密钥，**必须**设为强随机值（至少 32 字符），否则启动拒绝 |
| `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` / `DEEPSEEK_MODEL` | **服务端** LLM 凭据（前端不参与）；用户也可在「设置 → 模型」页签按账号配置自己的 Key（加密存储，优先于服务端） |
| `LLM_PROVIDER` | `openai`（默认）/ `ollama`；或把 `DEEPSEEK_BASE_URL` 设为 `http://localhost:11434` 自动走本地 Ollama |
| `AGENT_CRAFT_MODE` | 写作工艺：`auto` / `off` / `lite` / `full` |
| `AGENT_SELF_REVIEW` | 自检：`auto` / `on` / `off` |
| `CRITIC_API_KEY` / `CRITIC_API_BASE_URL` / `CRITIC_API_MODEL` | 可选责编模型（空则复用写作模型） |
| `CORS_ORIGINS` | 前端源，逗号分隔 |
| `REDIS_URL` | 协作 SSE 与接口限流跨 worker；留空 = 单进程内存。线上 compose 会写入 `redis://redis:6379/0` |
| `EMBEDDING_BASE_URL` / `EMBEDDING_API_KEY` / `EMBEDDING_MODEL` | 可选：pgvector 语义搜索的 embedding 端点；留空 = 启发式关键词检索 |
| `LLM_DAILY_TOKEN_CAP` | 用户自备 Key 的每日上限（**0 = 不限**，默认） |
| `LLM_SHARED_KEY_DAILY_CAP` | 仅当请求落到**服务端** `DEEPSEEK_API_KEY` 时的每日上限（默认 20 万；无服务端 Key 则不会触发） |
| `MAX_PROJECTS_PER_USER` | 每账号项目数上限（默认 80） |
| `ALLOW_REGISTRATION` | `false` 一键关注册 |
| `ADMIN_USERNAMES` | 逗号分隔管理员用户名；可调用 `/api/v1/admin/*` 封禁/解禁。空 = 仅 CLI |
| `RATE_LIMIT_ENABLED` | 登录/注册/新建限流（默认 true；限额较宽） |
| `RESEND_API_KEY` / `RESEND_FROM_EMAIL` / `PUBLIC_APP_URL` | 注册验证与找回密码邮件。未配置则无法注册 |
| `AUTH_AUTO_VERIFY` | 仅测试/e2e：跳过发信并直接验证新账号 |

前端「设置」含外观、工具背景、用量与**模型凭据**（用户级 Key 按账号加密存储）；服务端级模型接入改 `backend/.env` 后重启 API。

### 可选功能：多 worker SSE 与语义搜索

- **多 worker 协作事件**：`uvicorn app.main:app --workers N` 时，设 `REDIS_URL` 即可让锁/成员/批注事件跨 worker 实时广播；不设则回退单 worker 进程内（docker-compose 已含 redis 服务）。
- **pgvector 语义搜索**：将 docker-compose 的 postgres 镜像换成 `pgvector/pgvector:pg16` 并 `CREATE EXTENSION vector`，再配置 `EMBEDDING_*` 环境变量，`POST /analysis/semantic-search` 即用向量相似度；缺省自动回落启发式关键词排序（无需额外配置）。

### 测试

```bash
cd backend
set PYTHONPATH=.
pytest tests/ -q
```

> API/DB 集成测试（`tests/test_api_*.py`）需要测试库 `vnss_test`：连接串来自
> `DATABASE_URL_TEST`（默认 `postgresql+asyncpg://vnss:vnss@localhost:54102/vnss_test`）。
> 连不上时这些用例自动跳过；CI 会起一个 Postgres service 全量运行。
> 前端：`cd frontend && npm test`（vitest，纯函数单测）。
> 前端 e2e：`cd frontend && npm run build && npm run test:e2e`（需本地 PG 可达，见 playwright.config.ts）。

### 备份 / 恢复 / 监控

线上：`scripts/ops/backup_pg.sh` 每天 03:00 UTC `pg_dump`（保留 14 份，目录 `/opt/vn-script-studio/backups`）。健康检查 `GET /health`（Cloudflare 可对 `https://studio.nexesr.top/health` 配 uptime）。容器日志 json-file 轮转（20MB × 5）。封禁字段为 `users.disabled_at`（登录 / refresh / 鉴权均检查）：`docker exec -it vnss-api python -m app ban <用户名>` / `unban` / `list-banned`；或设 `ADMIN_USERNAMES` 后调 `POST /api/v1/admin/users/{username}/ban`。

本机 Windows：

```powershell
cd backend
# 备份（默认 backend/backups/，保留最近 14 份）
.\scripts\backup.ps1

# 恢复（会清空并重建 vnss 库，先备份再恢复）
.\scripts\restore.ps1 -File .\backups\vnss-20260815-120000.dump
```

依赖本机可用的 `pg_dump` / `pg_restore`（或 PostgreSQL 客户端安装目录）。

### 与旧版差异

- 工程与 Agent 会话进入 PostgreSQL，不再依赖浏览器 localStorage 作为主存储
- 分享为云端 token，跨设备可访问
- Agent 写回由服务端 `apply_agent_actions` 完成后返回最新工程
- 旧 Next.js monorepo（legacy/）已随迁移完成而移除；历史版本见 git

### 许可与声明

自用 / 协作向工作室。使用第三方模型 API 时请遵守对应服务商条款。AI 生成内容请人工审稿后再进入发行流程。
