# VN Script Studio

面向**视觉小说 / 轻小说向剧本**的 AI 辅助写作工作室。  
前后端分离：FastAPI + React (Vite) + PostgreSQL，以 Ren'Py 可上演脚本为目标。

## 系统形态

```
vn-script-studio/
├── docker-compose.yml   # PostgreSQL 16
├── backend/             # FastAPI + 全部业务逻辑（原 @vnss/core）
├── frontend/            # Vite + React SPA
├── examples/            # 示例工程
└── legacy/packages/     # 旧 Next.js monorepo（对照用，可忽略）
```

| 层 | 技术 |
|----|------|
| 后端 | FastAPI、SQLAlchemy 2、Alembic、JWT、httpx |
| 前端 | Vite 6、React 19、React Router、CSS Modules |
| 数据库 | PostgreSQL 16（Docker） |
| LLM | OpenAI 兼容 Chat Completions（默认 DeepSeek） |

## 快速开始

### 1. 启动数据库

```bash
docker compose up -d
```

### 2. 后端

```bash
cd backend
python -m venv .venv

# Windows
.venv\Scripts\activate
# macOS/Linux
# source .venv/bin/activate

pip install -r requirements.txt
copy .env.example .env   # 或 cp .env.example .env
# 编辑 .env，至少可先用默认 DATABASE_URL；填入 DEEPSEEK_API_KEY 以启用 Agent
```

启动 API（默认 http://localhost:8000 ，文档 /docs）：

```bash
# 在 backend/ 目录
set PYTHONPATH=.
uvicorn app.main:app --reload --port 8000
```

### 3. 前端

```bash
cd frontend
npm install
npm run dev
```

打开 http://localhost:5173 ，注册账号后即可使用。Vite 已将 `/api` 代理到后端。

## 主要 API（`/api/v1`）

| 分组 | 说明 |
|------|------|
| `POST /auth/register` `POST /auth/login` `GET /auth/me` | JWT 认证 |
| `GET/POST /projects` … | 云端剧本库 CRUD、导入、导出、快照 |
| `POST /projects/{id}/agent` | 审稿 Agent（服务端 apply actions） |
| `GET/PUT /projects/{id}/agent/session` | 对话 / 记忆 / 撤回栈 |
| `POST /projects/{id}/voice-check` `POST /projects/{id}/ai` | 语气检查 / 旧式 AI |
| `POST /projects/{id}/shares` `GET /shares/{token}` | 真云端只读分享 |
| `GET/PUT /settings` | 用户设置（API Key 服务端加密存储，回写脱敏） |

完整契约见运行中的 [OpenAPI](http://localhost:8000/docs)。

## CLI

```bash
cd backend
set PYTHONPATH=.
python -m app demo out.json
python -m app export out.json out.rpy
python -m app ai out.json continue --instruction "更压抑"
```

## 环境变量（backend/.env）

| 变量 | 说明 |
|------|------|
| `DATABASE_URL` | 默认 `postgresql+asyncpg://vnss:vnss@localhost:5432/vnss` |
| `SECRET_KEY` | JWT 签名密钥 |
| `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` / `DEEPSEEK_MODEL` | **服务端** LLM 凭据（前端不参与） |
| `AGENT_CRAFT_MODE` | 写作工艺：`auto` / `off` / `lite` / `full` |
| `AGENT_SELF_REVIEW` | 自检：`auto` / `on` / `off` |
| `CRITIC_API_KEY` / `CRITIC_API_BASE_URL` / `CRITIC_API_MODEL` | 可选责编模型（空则复用写作模型） |
| `CORS_ORIGINS` | 前端源，逗号分隔 |

前端「设置」仅含外观与工具背景；模型接入一律改 `backend/.env` 后重启 API。

## 测试

```bash
cd backend
set PYTHONPATH=.
pytest tests/ -q
```

## 与旧版差异

- 工程与 Agent 会话进入 PostgreSQL，不再依赖浏览器 localStorage 作为主存储
- 分享为云端 token，跨设备可访问
- Agent 写回由服务端 `apply_agent_actions` 完成后返回最新工程
- 旧 `legacy/packages/*`（Next.js monorepo）仅作对照，日常开发请用 `backend/` + `frontend/`

## 许可与声明

自用 / 协作向工作室。使用第三方模型 API 时请遵守对应服务商条款。AI 生成内容请人工审稿后再进入发行流程。
