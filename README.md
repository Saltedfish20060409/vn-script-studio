# VN Script Studio

面向**视觉小说 / 轻小说向剧本**的 AI 辅助写作工作室。  
前后端分离：FastAPI + React (Vite) + PostgreSQL，以 Ren'Py 可上演脚本为目标。

## 能做什么

- **写作台**：章节编辑、地图、分支分析、云端工程与快照
- **Agent 审稿**：服务端写回剧本；可选写作工艺 / 自检；作家透镜与头脑风暴
- **角色工坊**：多场景语料塑形 → 思维包合成 → 有思维包后可试聊 / 角色互聊
- **扩展能力**：导师包、小说记忆归档、流水线闸门、Harness 质检、萌娘百科 lore 蒸馏（可选）

## 系统形态

```
vn-script-studio/
├── docker-compose.yml   # PostgreSQL 16（宿主机默认 15432 → 容器 5432）
├── backend/             # FastAPI + 全部业务逻辑
├── frontend/            # Vite + React SPA
├── examples/            # 示例工程
├── dev.bat / dev.ps1    # Windows 一键开发启动
└── legacy/packages/     # 旧 Next.js monorepo（对照用，可忽略）
```

| 层 | 技术 |
|----|------|
| 后端 | FastAPI、SQLAlchemy 2、Alembic、JWT、httpx |
| 前端 | Vite 6、React 19、React Router、CSS Modules |
| 数据库 | PostgreSQL 16（Docker） |
| LLM | OpenAI 兼容 Chat Completions（默认 DeepSeek） |

## 快速开始

### Windows 一键启动

```powershell
# 仓库根目录
.\dev.ps1
# 或
.\dev.bat
```

会：必要时 `docker compose up -d` → 新开窗口跑后端 `:8000`（**项目 `.venv`**）→ 新开窗口跑前端 `:5173` → 打开浏览器。  
已在跑的端口会跳过；若发现 8000 被非本仓库 `.venv` 占用，脚本会尝试替换。  
加 `-SkipDocker` 可跳过数据库；`-NoBrowser` 不自动开页。

### 首次依赖（只需一次）

```bash
docker compose up -d

cd backend
python -m venv .venv
.venv\Scripts\activate          # macOS/Linux: source .venv/bin/activate
pip install -r requirements.txt
copy .env.example .env          # 或 cp .env.example .env
# 编辑 .env：DATABASE_URL 端口默认 15432（与 docker-compose 一致）
# 填入 DEEPSEEK_API_KEY 以启用 Agent / 角色工坊生成

cd ../frontend
npm install
```

### 手动分别启动

请用 **`backend\.venv`**，不要用 Anaconda / 系统全局 Python 另开一份 uvicorn（否则容易出现「旧 API / 长场次无结果」）。

```bash
# 后端（backend/）
set PYTHONPATH=.
.venv\Scripts\python.exe -m uvicorn app.main:app --reload --host 127.0.0.1 --port 8000

# 前端（frontend/）
npm run dev
```

打开 http://localhost:5173 ，注册账号后即可使用。Vite 将 `/api` 代理到后端。  
API 文档：http://localhost:8000/docs

### 结束使用时

关掉后端、前端两个窗口（或先在窗口里 `Ctrl+C`）。若怀疑端口残留：

```powershell
Get-NetTCPConnection -LocalPort 8000,5173 -State Listen -ErrorAction SilentlyContinue |
  ForEach-Object { Stop-Process -Id $_.OwningProcess -Force -ErrorAction SilentlyContinue }
```

Postgres 用 Docker 常驻即可，不必每次重建。

## 主要 API（`/api/v1`）

| 分组 | 说明 |
|------|------|
| `POST /auth/register` `POST /auth/login` `GET /auth/me` | JWT 认证 |
| `GET/POST /projects` … | 云端剧本库 CRUD、导入、导出、快照 |
| `POST /projects/{id}/agent` 等 | 审稿 Agent、会话记忆、撤回 |
| `…/characters/{id}/voice/*` `…/workshop/chat` | 角色工坊：生成 / 入库 / 合成思维包 / 试聊 |
| `…/lenses` `…/mentors` | 作家透镜、导师包 |
| `…/memory/*` `…/pipeline/*` `…/harness/*` | 记忆归档、流水线、Harness |
| `…/lore/*` | 萌娘百科相关 lore（可选） |
| `POST /projects/{id}/voice-check` `POST /projects/{id}/ai` | 语气检查 / 旧式 AI |
| `POST /projects/{id}/shares` `GET /shares/{token}` | 云端只读分享 |
| `GET/PUT /settings` | 用户设置（外观等；LLM Key 以服务端 `.env` 为准） |

完整契约见运行中的 [OpenAPI](http://localhost:8000/docs)。

## CLI

```bash
cd backend
set PYTHONPATH=.
python -m app demo out.json
python -m app export out.json out.rpy
python -m app ai out.json continue --instruction "更压抑"
```

## 环境变量（`backend/.env`）

| 变量 | 说明 |
|------|------|
| `DATABASE_URL` | 默认 `postgresql+asyncpg://vnss:vnss@localhost:15432/vnss` |
| `SECRET_KEY` | JWT 签名密钥 |
| `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` / `DEEPSEEK_MODEL` | **服务端** LLM 凭据（勿提交真实 Key） |
| `AGENT_CRAFT_MODE` | 写作工艺：`auto` / `off` / `lite` / `full` |
| `AGENT_SELF_REVIEW` | 自检：`auto` / `on` / `off` |
| `CRITIC_API_*` | 可选责编模型（空则复用写作模型） |
| `MOEGIRL_*` | 可选萌娘百科 lore |
| `CORS_ORIGINS` | 前端源，逗号分隔 |

**切勿**把含真实密钥的 `.env` 提交到 Git；仓库只保留 `.env.example`。

## 测试

```bash
cd backend
set PYTHONPATH=.
pytest tests/ -q
```

## 与旧版差异

- 工程与 Agent 会话进入 PostgreSQL，不再依赖浏览器 localStorage 作为主存储
- 分享为云端 token，跨设备可访问
- Agent 写回由服务端完成后返回最新工程
- 旧 `legacy/packages/*` 仅作对照，日常开发请用 `backend/` + `frontend/`

## 许可与声明

自用 / 协作向工作室。使用第三方模型 API 时请遵守对应服务商条款。AI 生成内容请人工审稿后再进入发行流程。
