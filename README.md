# VN Script Studio

面向**视觉小说 / 轻小说向剧本**的 AI 辅助写作工作室。  
默认用自然语言写剧本，需要上演时再切到 Ren'Py（`.rpy`）。

应用内顶栏 **帮助** 有完整使用说明。AI 生成内容请自行审稿后再用于发行。

## 许可

本项目代码采用 **MIT License**（见 [LICENSE](LICENSE)）。  
ACG 设定卡内容参考自 **萌娘百科（Moegirlpedia）**，遵循其 **CC BY-NC-SA 3.0 CN** 许可（以各条目页面标注为准）；卡片为精炼改写，来源链接见各卡片 `source_url`。

---

## 给作者

想先上手体验的话，最快的方式是本地 Docker 一键跑起来（见下方「给开发者 · 方式 A」）；需要公网服务时，把 `vnscriptstudio.cn`（或你自己的域名）解析到你的服务器即可，README 其余部分不绑定任何特定站点。

自建见下方「给开发者」。

### 怎么写

- **写作页默认是自然语言剧本**：旁白直接写，对白写成「角色名：台词」。
- 同一编辑器可切到 **RPY**：两份稿互不覆盖。RPY 可手写，也可点「根据剧本生成」（设置里填了模型 Key 则走 AI，否则用规则解析）。
- 剧本改过、RPY 没重生时会提示过期。
- **顶栏导出跟当前视图**：剧本 → `.docx`，RPY → `.rpy`。整包工程 / Markdown / Ren'Py 项目 zip 在「项目 → 导出」。
- **试玩读的是 RPY 稿**。只写了自然语言时，先生成或手写脚本再试玩。
- **保存即攒记忆，不用你吩咐**：每次保存会自动刷新**章节摘要**（梗概 / 出场角色 / 开场收束钩子）并更新**写作账本**（每章事实、角色情绪与最近动作、章末钩子记为未回收伏笔），纯本地抽取、不调模型也不额外花额度。它们会作为「项目硬锚」自动进 AI 责编的上下文，让续写与审稿不跑偏。想看它记住了什么：**项目 → 账本 / 摘要**。
- **改稿用得上的手感**：编辑器内 `Ctrl/Cmd+F` 查找替换（浏览器自带的搜不到这里），中文引号/括号自动配对，写作页顶部有**字数目标进度**（本章 / 本卷 / 今日）与**分场导航**（`◇◇◇` 或 `【场景名】` 即成一个可跳转的场景），还有一条**笔误体检**（引号不配对、半角标点贴汉字、`--`/`...`、80 条常见成语别字，点一下跳到那一处）。
- **稿件体检（不花额度）**：**项目 → 稿件体检** 跑的是纯文本统计——表记/引号/人名变体/视角称呼 + 注音写法/拟声密度/章末钩子评分/对白占比。它不调用模型，所以可以每改完一章点一次；面板会如实写明扫了几章、哪几章没正文。语义层面的矛盾检查仍由「结构分析」里的模型审计负责。
- **连载工作台**：**项目 → 连载 / 发布** 一页看完今日净增与日更目标、连续更新天数（今天还没写不算断）、近 12 周更新日历、存稿与已发布进度；发布状态由你自己标（记时间，回头改完可以再发一次），工具不去猜哪一章像发过的。
- **投稿包**：**项目 → 导出 → 投稿包**：按投稿方格式排版（首行缩进 2 字符、每章另起一页、文末标字数、开头一页投稿信息），或**分章打包**（一章一个 `.docx` + 投稿信息.txt）。**章节梗概默认不带**——那是写给自己看的备注，混进稿子会被编辑当成正文。
- **写小说而不是写游戏脚本**：帮助面板顶部可以切到「轻小说 / 网文」，那里有 9 步上手与投稿相关的 FAQ；新建项目时也能选「轻小说起步工程」模板（一卷三章、正文与节拍表都已就位）。作品的体裁决定界面用词（剧本 / 正文·分卷·投稿），在「视图 → 设定」可以显式指定，不改则按题材自动判断、且**老工程默认不变**。

### 其它常用入口

| 入口 | 做什么 |
|------|--------|
| 设定 | 角色卡、世界观、设定库 |
| 地图 | 从剧本抽地点，点地点可跳回写作 |
| 角色工坊 | 定声音 → 思维包 → 试聊。手机上点「换角色」打开名单 |
| 账本 / 摘要 | 翻看自动攒下的章节摘要、角色状态、未回收伏笔 |
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

#### 方式 A：Docker 一键试用（推荐，无需装 Node/Python）

只要装了 [Docker Desktop](https://www.docker.com/products/docker-desktop/)（Windows/macOS）或 Docker Engine（Linux），clone 后直接起全栈：

```bash
git clone <本仓库>
cd vn-script-studio
docker compose up -d        # 构建 api/web + 起 postgres/redis
```

打开 **http://localhost:8080**，注册账号即可使用（试用模式**注册后免邮箱验证**，直接登录）。

| 组件 | 地址 |
|------|------|
| Web 界面 | http://localhost:8080 |
| API 文档 | http://localhost:8000/docs |
| PostgreSQL | localhost:54102（vnss/vnss） |

- AI 功能：登录后在「设置 → 模型」按账号填你的 LLM Key（如 DeepSeek），或启动时注入服务端 Key：`DEEPSEEK_API_KEY=sk-xxx docker compose up -d`
- 停止：`docker compose down`（数据保留在卷里；`docker compose down -v` 会清空）
- 需要固定密钥 / 真实邮箱验证时，见下方环境变量节

#### 方式 B：源码开发模式（改代码用）

**前置**：Docker Desktop（跑 PostgreSQL / Redis）+ Node.js 20+ + Python 3.12+。

日常开发可一键启动：

```powershell
# Windows（仓库根目录）
.\dev.ps1
# 或双击 / 运行
.\dev.bat
```

```bash
# macOS / Linux
./dev.sh
```

会：必要时 `docker compose up -d` → 起后端 `:8000` → 起前端 `:5173` → 打开浏览器。  
已在跑的端口会跳过。加 `-SkipDocker`（dev.ps1）或 `--skip-docker`（dev.sh）可跳过数据库；`-NoBrowser` / `--no-browser` 不自动开页。

首次仍需装好依赖（只需一次）：

```bash
# 数据库
docker compose up -d

# 后端
cd backend
python3 -m venv .venv
source .venv/bin/activate       # Windows: .venv\Scripts\activate
pip install -r requirements.txt
cp .env.example .env            # Windows: copy .env.example .env
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

Postgres 用 Docker 常驻即可，不必每次重建；每次写代码通常只需前后端两个进程（或跑一次 `dev.ps1` / `dev.sh`）。

### 生产构建（Docker）

后端镜像依赖已锁定（`requirements.txt` 为精确版本；`requirements-lock.txt` 为全量冻结参考）：

```bash
# 后端镜像
cd backend
docker build -t vnss-api .

# 前端产物（nginx / 任意静态服务器托管 frontend/dist）
cd frontend
npm ci && npm run build
```

自己长期运行时，可用任意 Nginx / Caddy 反代 `/api` 到后端 :8000 并托管 `frontend/dist`；备份与日常维护由你自行安排（本仓库只含应用代码与本地部署入口，不含特定服务器的运维脚本）。

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
| `GET …/analysis/branch-report` | 分支结构体检：label 图 / 环检测 / 分支覆盖 / 条件可满足性 / 无后果选项 / 结局对账（纯本地） |
| `GET …/analysis/voice-report` | 角色声线体检：语言画像 / 逐章声线漂移 / 角色间可混淆度（纯本地） |
| `GET …/analysis/continuity` | 跨章事实一致性：未登记说话人 / 悬空关系 / 时间线错序 / 死亡后仍出场（纯本地） |
| `GET …/analysis/story-metrics` | 故事层指标：**伏笔回收率**（含最老未回收钩子的章龄）与**情感弧线**（逐角色 + 逐章断裂 + 与节拍表声明对账，纯本地） |
| `GET …/analysis/adaptive-plan` | **自适应选项**：从现有 `set` 块自动派生"读者倾向"计数器（persistent、跨存档）与可照抄的条件（纯本地） |
| `GET …/export/rpy` · `…/export/bundle` | 导出 .rpy / zip（支持 `?adaptive_reader=true` 注入读者倾向计数，默认关） |
| `GET …/playtest/recommendations` | **分支改进建议**：把静态结构分析与读者实际行为融成可执行改法（"这个选项选哪个都一样""没人走到这个结局"） |
| `POST …/playtest/record` · `GET/PUT …/playtest/settings` · `GET …/playtest/analytics` | 读者行为遥测：默认关闭、只存 id/索引/计数、不记任何正文；开启后可看选项占比、漏斗、没人选的选项/结局与读者侧覆盖率 |
| `POST …/analysis/consistency-scan` | 全书**分片全量**一致性扫描（调模型；如实上报覆盖率，不再静默截断在前 14 章） |
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
# 对照盲评：「工具流程」vs「裸聊」两臂，同一模型同一任务、量具完全相同
#   --repeats N 看采样方差；--judge-model 换成独立裁判（默认与选手同模型，会告警）
python -m app eval --ab --repeats 3 --judge-model <独立模型> -o ab.json
# 长程一致性基准：造带标准答案的合成长篇，量「章距 vs 暴露率/检出率」。**不需要 API key**
python -m app eval --longrange --longrange-chapters 60
# 上下文政策 A/B：量「该进上下文的材料有没有真的进来」（埋点事实命中、焦点章覆盖率、
#   整块让位 vs 中段切一刀）。**不需要 API key**，两臂跑的是同一份真实代码
python -m app eval --context-ab --context-ab-chapters 40
```

对照盲评（`--ab`）用来回答「这软件是不是还不如直接跟聊天框说一句」这类质疑：

- **两臂只差流程**：`tool` 臂走线上真实链路（检索拼装上下文 + 工艺卡 + 输出契约 +
  作者硬规则 + 任务分档温度 + 第二遍自检修订）；`bare` 臂是同一个模型、**同一句用户话术**，
  只有一句通用「写作助手」人设，不给上下文、不给工艺、不做自检。
- **量具完全相同**：两臂产出都用同一套确定性 lint（`harness.audit_full`）和同一份
  Rubric Judge（逐维打分 + 一票否决）评分，避免「自己当裁判还改尺子」。
- **随机标签盲评**：每例的甲/乙分配按 `--seed` 独立随机，盲评文件（`blind-ab.json`）
  **不含答案**、可直接交给别人或另一个模型评；答案单独写在 `blind-ab-key.json`，
  评完再拆封。换个 `--seed` 可复现另一套标签，用来检查评审自身是否稳定。
- **不确定度一起报**：报告里给配对 bootstrap 95% 区间、符号检验与 veto 的 McNemar 精确检验；
  区间跨 0 时会明确打印「未达显著」，不拿一个均值差当结论。
- **裁判不再被透题**：用例文案里写给我们自己的评测元信息
  （如「（测试：审稿应抓住…，判定不合格）」）会在送裁判前剔除；
  裁判默认与选手同模型时会在报告与终端里**明确告警**（`judgeIndependent=false`）。
- 报告里保留集看 lint 通过率与 Rubric 均分，边界集（`trap-*`）看检出率与 veto，
  并直接打印「工具 − 裸聊」的差值。

长程一致性基准（`--longrange`）回答的是另一个问题：**长篇从第几章开始失效？**
它造一部带标准答案的合成长篇，在受控章距上注入矛盾，同时埋入诱导项（看着可疑但不矛盾）
用来量误报，然后分章距分桶给出：

- **暴露率**：矛盾所在的章有没有被送进检测器视野（检测的必要条件，纯结构量、不需模型）；
- **检出率 / precision / recall / F1**：拿现成的确定性检查当被测量具。

实测结论：旧实现（只扫前 14 章）在 16 章以外的暴露率是 **0**——那些章的召回在构造上就不可能为 1；
分片方案把暴露率做到 1.00。完整口径、数字与**仍未解决的部分**见
[docs/longrange-consistency-and-eval.md](docs/longrange-consistency-and-eval.md)。

上下文政策 A/B（`--context-ab`）回答第三类问题：**这一轮长上下文改动，材料有没有真的进来？**
它同一部合成长篇上跑「改动前 vs 改动后」两臂（`policy="legacy"` / 默认），三组对照
（同预算 / 同紧预算 / 各自默认），给配对 bootstrap 区间与 McNemar 精确检验：

- 每章埋一条不重复的事实句、焦点章切成 10 段哨兵 → 「记忆层命中几条」「焦点章进了几段」是可逐字核对的**结构量**；
- 一次真实读数是焦点章覆盖率 10/10 vs 4/10、旧式「中段切一刀」0% vs 100%（p=0.0078）；
- 它**不**回答「写得更好」——那是人工盲测（`--ab` + `docs/blind-ab.md`）的事；
  报告里会**连反向读数一起打印**（紧预算下记忆层命中反而落后 21 条，成因与取舍见文档）。
- 完整三张量具的分工、这张量具自己的边界，见
  [docs/long-context-policy.md](docs/long-context-policy.md) 第十节。

### 超时预算（前端与后端必须对齐）

前端每个请求等多久，必须覆盖后端在**同一次请求内**串行跑完的所有 LLM 调用（含思考档加时，
以及**长提示词的预填充加时**：read timeout 覆盖"预填充 + 整段生成"，所以上下文预算放大后
前端阶梯必须同步上调）。两侧的命名真源分别是 `backend/app/core/llm_budget.py` 与
`frontend/src/api/timeouts.ts`，并由 `frontend/src/api/timeouts.test.ts` 直接读后端源码逐端点校验。
慢思考档（`*-think`）由后端自动加时，读超时**不重试**，流式路径不设总超时（靠 20s 心跳判活）。
背景、失配表与残余风险见 [docs/llm-timeout-budget.md](docs/llm-timeout-budget.md)；
上下文预算与预填充加时的成对关系见 [docs/long-context-policy.md](docs/long-context-policy.md)。
**耗时分布**（The Tail at Scale 的"先量后决"）在 `GET /admin/llm-latency`：按
模型 × 思考档 × 能力给出 p50/p95/p99、超时率与流式首字耗时；**hedged request 判定为不做**
（单一上游没有独立副本，第二路只多花一份 token），量化理由见 timeout 文档第十节。

### 写作界面（编辑手感 / 离线体检 / 轻小说路径）

编辑器里的查找替换、中文标点自动配对、分场导航、字数目标、笔误体检，以及
**不调用模型**的稿件体检（`POST /projects/{id}/analysis/novel-audit`、Agent 工具
`novel_audit`、前端「项目 → 稿件体检」）与轻小说起步模板，记在
[docs/writing-surface.md](docs/writing-surface.md)：包括每条的取舍、项目级字段必须同时改
的四处白名单（漏一处就静默丢数据），以及明确的未做清单。

### 依据与参考（规范 / 论文 → 我们的哪个决定）

每条表记规则的**依据**都写在代码里（`_RULE_BASIS` / `RULE_BASIS`，界面上逐条显示），
指向 GB/T 15834-2011《标点符号用法》、GB/T 15835-2011《出版物上数字用法》、
CY/T 154-2017《中文出版物夹用英文的编辑规范》、W3C《中文排版需求》(clreq) 等公开可查的规范；
没有公开规范可依的（视角、称呼、别字词表）如实标成"作品自身的一致性（启发式）"，不假借国标。
论文层面的技术依据、按模块的落点与**待办清单**见 [docs/references.md](docs/references.md)。

### 环境变量（backend/.env）

| 变量 | 说明 |
|------|------|
| `DATABASE_URL` | 默认 `postgresql+asyncpg://vnss:vnss@localhost:54102/vnss`（宿主机端口与 docker-compose 一致） |
| `SECRET_KEY` | JWT 签名密钥，**必须**设为强随机值（至少 32 字符），否则启动拒绝 |
| `DEEPSEEK_API_KEY` / `DEEPSEEK_BASE_URL` / `DEEPSEEK_MODEL` | **服务端** LLM 凭据（前端不参与）；用户也可在「设置 → 模型」页签按账号配置自己的 Key（加密存储，优先于服务端） |
| `LLM_PROVIDER` | `openai`（默认）/ `ollama`；或把 `DEEPSEEK_BASE_URL` 设为 `http://localhost:11434` 自动走本地 Ollama |
| `AGENT_CRAFT_MODE` | 写作工艺：`auto` / `off` / `lite` / `full` |
| `AGENT_SELF_REVIEW` | 自检：`auto` / `on` / `off` |
| `LLM_THINKING_TIMEOUT_FACTOR` | 思考档（`*-think`）的 LLM 超时倍数，默认 `2.0`（夹在 1.0–5.0）。reasoning 期间上游不产出，非流式请求的 read 超时覆盖整段生成，所以思考档要更宽。见 `app/core/llm_budget.py` |
| `AGENT_UNKNOWN_MODEL_WINDOW_K` | 预设表里**没收录的模型**按多大的窗口保守处理（千 token，默认 `128`）。为什么不默认"不夹"：撑爆窗口时上游直接拒答，用户什么都拿不到。自部署大窗口模型可以在这里声明真实值；**0 或负数 = 不夹**。用户也可以在「设置 → 模型 → 上下文窗口」按账号声明（那会覆盖这里的保守假设；已知模型只能调低） |
| `DISCONNECT_CANCEL_ENABLED` | 客户端断开时是否中止正在进行的模型调用（默认 `true`，省 token 并释放并发闸）。只作用于"正在等模型"的窗口，不影响已落库的写入与后台作业；见 `app/core/disconnect.py` |
| `CRITIC_API_KEY` / `CRITIC_API_BASE_URL` / `CRITIC_API_MODEL` | 可选责编模型（空则复用写作模型） |
| `CORS_ORIGINS` | 前端源，逗号分隔 |
| `REDIS_URL` | 协作 SSE 与接口限流跨 worker；留空 = 单进程内存。线上 compose 会写入 `redis://redis:6379/0` |
| `EMBEDDING_BASE_URL` / `EMBEDDING_API_KEY` / `EMBEDDING_MODEL` | 可选：pgvector 语义搜索的 embedding 端点；留空 = 启发式关键词检索 |
| `LLM_DAILY_TOKEN_CAP` | 用户自备 Key 的每日上限（**0 = 不限**，默认） |
| `LLM_SHARED_KEY_DAILY_CAP` | 仅当请求落到**服务端** `DEEPSEEK_API_KEY` 时的**每用户每日**上限。代码默认 20 万；生产现设为 **200 万** |
| `AGENT_CONTEXT_MAX_CHARS` | Agent 单次注入的项目上下文预算（字符）。代码默认 **48000**（质量优先，见 [docs/long-context-policy.md](docs/long-context-policy.md)），会被夹在 3000–96000 之间（**流式端点**可到 240000，见下）；**≥8000 字符的提示词会同步放宽 LLM 读超时**（预填充加时，最多 +60s / 流式 +240s），生产可按机器实测继续调 |
| `SAMPLE_PROJECT_ON_SIGNUP` | 注册时自动送示例项目（激活用，默认 `true`） |
| `MEMORY_AUTO_ARCHIVE` | 每攒满 10 章自动重建章节记忆归档（纯本地计算、不调模型，默认 `true`） |
| `MAX_PROJECTS_PER_USER` | 每账号项目数上限（默认 80） |
| `ALLOW_REGISTRATION` | `false` 一键关注册 |
| `ADMIN_USERNAMES` | 逗号分隔管理员用户名；可调用 `/api/v1/admin/*` 封禁/解禁。空 = 仅 CLI |
| `RATE_LIMIT_ENABLED` | 登录/注册/新建限流（默认 true；限额较宽） |
| `RESEND_API_KEY` / `RESEND_FROM_EMAIL` / `PUBLIC_APP_URL` | 注册验证与找回密码邮件。未配置则无法注册 |
| `AUTH_AUTO_VERIFY` | 仅测试/e2e：跳过发信并直接验证新账号 |

前端「设置」含外观、工具背景、用量与**模型凭据**（用户级 Key 按账号加密存储）；服务端级模型接入改 `backend/.env` 后重启 API。

> **上下文预算怎么定？**（2026-09 实测 + 2026-09 政策调整）`AGENT_CONTEXT_MAX_CHARS` 是**上限**
> 而不是固定开销：拼装量小于上限时提高它不产生任何额外 token。抽查线上 8 个真实项目时，
> 拼装量只有 698–2679 字符（章节最多 5 章），**没有一个触顶**——所以把它从 12000 提到 48000
> 对短篇几乎没有影响。
>
> 真正影响"写长篇时突然变笨"的是另外三处，这次一起改了：焦点章正文的**写死上限 5000 字符**
> （一章两万字时续写只看得到最后一小截）、记忆层的单块上限（3200/2400）、以及超预算时
> "从中间切一刀"的处理方式。同时按 Lost in the Middle 的位置结论重排了上下文，
> 并让模型在提示词里就能看到"这次省了什么、用哪个工具取回"。
>
> 注意：**调大窗口不解决连贯性**——真正管用的仍是检索命中、章节目录与记忆层归档
> （`MEMORY_AUTO_ARCHIVE`）。完整政策、代价（预填充 ⇒ 超时同步放宽）与未做清单见
> [docs/long-context-policy.md](docs/long-context-policy.md)。

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
> 连不上时这些用例自动跳过，所以本地不配库也能跑（本机实测 350 passed / 76 skipped）；
> CI 的 `integration.yml` 自带 Postgres service，会真跑这一层（≈450 用例）。
> 想在**服务器上**用容器里的 Python 跑全量（比本地隧道稳且快）：
> `python deploy/run_db_tests.py`（见 `deploy/`，不入库；需要线上有独立测试库）。
> 前端：`cd frontend && npm test`（vitest，纯函数单测）。
> 前端 e2e：`cd frontend && npm run build && npm run test:e2e`（需本地 PG 可达，见 playwright.config.ts）。

### CI 策略（约定）

自动 CI（`.github/workflows/ci.yml`，push/PR 触发）**只跑干净环境必然能过的检查**：

- 后端：`ruff check app/` + `pytest tests/`（不连库 → DB 集成用例自动 skip）
- 前端：`npm ci` → typecheck → `lint:strict` → `npm test` → `npm run build` → bundle 体积门禁

需要真实数据库、但要密钥 / 外部服务 / 真数据才能跑的检查，走独立工作流：

| 工作流 | 触发 | 需要什么 |
|---|---|---|
| `integration.yml` | **自动（backend/** 变化）+ 可手动** | Postgres service（工作流自己起）+ 真库跑 `tests/`；第一步显式确认测试库可达，避免用例静默 skip |
| `e2e.yml` | 手动 | Postgres + 后端 + 前端构建 + Playwright 浏览器（注册走 `AUTH_AUTO_VERIFY=true` 免发信） |

> 2026-09 调整：`integration.yml` 从"仅手动"改为**后端改动时自动跑**。原因是本层用例才抓得住
> 真实缺陷（jsonb 键序导致的指纹漂移、注册/重发邮件的静默失败、并发与行锁语义），而"手动"
> 等于没人跑。它自带 Postgres service、不依赖任何密钥或外部服务，且容器内实测全量约 2.5 分钟。

**加新检查时的原则**：先在本机把它跑绿，再放进自动 CI；凡是要密钥、要外部服务、要真数据的，
放进独立工作流，并在文件头注明需要什么环境。

### 备份 / 恢复

本机 Windows（PostgreSQL 数据在本地 Docker 卷中时同样适用）：

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
