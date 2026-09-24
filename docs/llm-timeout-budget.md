# LLM 超时预算：为什么会"慢思考模型必超时"，以及这次是怎么修的

> 起因：用户报「用深度思考模型很容易超时，前端弹窗提示『请检查后端』；慢思考模型 100% 超时」。
> 本文记录**核实到的真因**（不是猜的）、修法、以及仍然没解决的部分。

## 一、结论先行

用户看到的弹窗是真实存在的，但它**指错了方向**：

- 原文案是 `请求超时（180s）——请确认后端服务已启动`（`frontend/src/api/http.ts`）。
  后端**完全正常**，只是这次模型调用比前端愿意等的时间更长。
- 根因不是"后端没启动"，而是**两侧对"超时"的定义根本不是同一件事**：
  - 后端写的是「**一次** LLM 调用的上限」，而且默认还会**重试 3 次**；
  - 前端写的是「**这个 HTTP 请求**总共等多久」。
  两边从来没有对齐过，于是存在一整类端点满足 `前端预算 < 后端最坏耗时`。
- 慢思考档（`*-think`）是这条线上最惨的一端：reasoning 阶段上游长时间一个字节都不发，
  而非流式请求的 httpx read 超时覆盖**整段生成**，所以同一个预算在思考档上必然提前击中。
- 还有两处独立的放大器：**读超时被当成可重试错误**（重试必然再超时 → 3 倍时间/费用），
  以及**后端的 `: keepalive` 心跳被前端解析器丢掉**（于是 90s"无事件"看门狗把
  "模型在思考"判成"模型配置错误"）。

## 二、核实过的证据（都在这个仓库里，可复核）

| 项 | 修前 | 说明 |
| --- | --- | --- |
| 前端默认超时 | 30s | `frontend/src/api/http.ts` 的 `REQUEST_TIMEOUT_MS` |
| 前端 apiFetch 调用点 | 134 个 | 只有 36 个显式设了 `timeoutMs`，**其余 98 个吃 30s 默认值** |
| 后端数值 `timeout=` | 37 处 | 其中 31 处是 `chat_completions` 调用点 |
| 后端重试 | 默认 3 次 | `llm_http.chat_completions(max_retries=3)`；`httpx.TimeoutException` 原本**也在重试范围内** |
| 反向代理 | 不是瓶颈 | `nginx.conf` 已设 `proxy_read_timeout 3600s` |
| 客户端断开后的取消 | 非流式端点无处理 | 全仓没有 `request.is_disconnected()`：前端 abort 后后端继续跑完并计费。流式侧已有协作式取消（`api/v1/pipeline.py` 的取消标志 + `_runner` 在阶段边界退出；agent 流会 `_mark_run_state("interrupted")`），非流式端点一条都没有 |
| SSE 心跳 | 20s 一次 | 三个流式端点的 `asyncio.wait_for(queue.get(), timeout=20)` + `": keepalive\n\n"` |
| 前端 SSE 解析 | 只认 `data:` 行 | `chunk.split("\n").find((l) => l.startsWith("data:"))` → 心跳被丢弃 |

### 失配表（"最坏耗时"= 串行各轮 × 后端预算 × 思考档系数 2.0）

| 端点 | 修前前端 | 后端每轮预算 | 串行轮数 | 思考档最坏 | 修后前端 |
| --- | --- | --- | --- | --- | --- |
| `/settings/test-llm` | **30s（默认）** | `PROBE` 30s | 1 | 60s | 120s |
| `/generate-rpy` | **30s（默认）** | `CHAT` 120s | 1 | 240s | 300s |
| `/brainstorm` | **30s（默认）** | `CHAT` 120s | 2 | 480s | 600s |
| `/agent/pre-questions` | 90s | `QUICK` 60s | 1 | 120s | 240s |
| `/voice-check` | 180s | `CHAT` 120s | 1 | 240s | 300s |
| `/pipeline/gate` | 180s | `QUICK`+`CHAT` | 2 | 360s | 480s |
| `/analysis/facts/scan`、`/reconcile` | 180s | `CHAT` 120s | 1 | 240s | 300s |
| `/agent/ingest-settings` | 180s | `CHAT` 120s | 1 | 240s | 300s |
| `/localization/translate` | 180s | `CHAT` 120s | 1 | 240s | 300s |
| `/characters/*/voice/generate`、`/synthesize`、`/workshop/chat` | 180s | `CHAT` 120s | 1 | 240s | 300s |
| `/recap` | 240s | `WRITE` 180s | 1 | 360s | 480s |
| `/consistency/audit` | 240s | `WRITE` 180s | 1 | 360s | 480s |
| `/style-memory/learn` | 240s | `WRITE` 180s | 1 | 360s | 480s |
| `/marks/revise` | 180s | `CHAT` 120s | 2 | 480s | 600s |
| `/analysis/consistency-scan` | 600s | `WRITE` 180s | 1（窗口并发） | 360s | 600s |
| `/agent/chapter-revise` | 180s | `WRITE`+`LONG` | 2 | 840s | 900s |

修前**每一行都不满足** `前端 ≥ 后端最坏耗时`。`/brainstorm` 最夸张：前端 30s，
后端是「2–3 位作家 `asyncio.gather` 并发一轮 + 责编综合一轮」，思考档最坏 480s——差 16 倍。

## 三、五个具体缺陷

1. **口径不一致（主因）**：见上表。前端按请求计时、后端按"单次调用 × 重试"计时。
2. **慢思考档没有任何加时**：`llm_models.resolve_chat_model()` 只改写模型名与
   `thinking` 字段，超时是各调用点的静态值。思考档在 reasoning 期间不产出，
   非流式的 read 超时（= 整段生成时间）必然先到。
3. **读超时被重试**：`httpx.TimeoutException` 原本与 429/5xx 一起被当成"可重试"。
   但"模型太慢导致超时"重试一次只会再慢一遍，还把最坏耗时乘 3——**前端无论填多少都不够**。
4. **心跳被丢弃 → 看门狗误杀**：`AgentChat.tsx` 的 90s"无事件"看门狗只被 `data:` 行复位，
   而服务端在模型思考时只发 `: keepalive`。结果：模型正常思考 90s 就被 abort，
   并弹出 `Agent 长时间无响应：请检查模型配置（Base URL / API Key / 模型名）后重试`
   ——把"模型慢"说成"配置错"。
5. **报错文案甩锅后端**，且**客户端 abort 不会取消后端**：用户以为请求失败了，
   其实服务端还在跑完并计费（非流式端点丢弃响应，副作用已发生）。

## 四、修了什么

### 后端

- 新增 `backend/app/core/llm_budget.py`：超时预算的**唯一真源**。
  命名常量 `PROBE/QUICK/MEDIUM/CHAT/WRITE/LONG`（值刻意与迁移前的字面量一致，迁移不改行为）、
  思考档系数 `THINKING_TIMEOUT_FACTOR=2.0`（可用环境变量 `LLM_THINKING_TIMEOUT_FACTOR` 覆盖，
  夹在 1.0–5.0）、以及 `effective_timeout()` / `worst_case_seconds()` 供测试与文档引用。
- `llm_http.py` 三条行为改动：
  1. **思考档自动加时**：出站 body 带 `thinking: enabled` 时按系数放大 → 覆盖全部 32 个调用点。
  2. **读/写超时不再重试**（`ReadTimeout`/`WriteTimeout` 明确排除在重试之外），
     连接类错误（`ConnectTimeout`/`PoolTimeout`/`NetworkError`/`RemoteProtocolError`）照旧重试。
     连接阶段单独封顶 10s，重试变便宜。
     > 这也正是前端预算能收得住的前提：最坏耗时不再是无脑 ×3。
  3. 超时**如实报错**：`模型响应超时：240s（基础 120s × 思考模式 2.0）内没有返回结果（模型 …）。
     常见原因是当前档位偏慢…可换成非思考档…或改用会持续输出进度的流式入口后重试。`
  4. **长提示词的预填充加时**（后续补充，见本节末尾"补记"）。
- 31 处 `chat_completions(timeout=…)` 全部换成 `llm_budget.*`；给 `localization/translate`
  补上原本缺失的显式预算（此前吃 provider 默认值，前端无法与之核对）。
- **客户端断开时中止在飞的模型调用**（新增 `backend/app/core/disconnect.py`）：
  中间件给每个请求挂一个 `DisconnectGuard`，`llm_http` 在**真正等上游**的那段时间外面套
  `model_call_watch()`——窗口内每 1 秒探一次连接，断开就取消**当前正在等模型的那个任务**。
  两条边界是刻意设计的：
  - **只覆盖"正在等模型"的窗口**，所以取消不会落在提交写入的过程中（业务是先拿结果再写库）；
  - 进入窗口时先探一次：客户端已经走了就**一个字节都不发**——多轮端点（头脑风暴的
    "作家 → 责编"、章节回炉的两段）不会再把下一轮也跑完；
  - 后台作业必须活过客户端（"结果能在运行记录里找到"），所以 `jobs._spawn` 在新任务里
    `detach_guard()` 主动脱离；它们继续用原有的协作式取消。
  - 链路若无法把断开告知应用层，探测不触发即退化为改造前的行为——**不会误杀**正常请求
    （探测本身报错也按"还在"处理）。可用 `DISCONNECT_CANCEL_ENABLED=false` 关掉。
- **一致性扫描在 HTTP 入口有了默认窗口上界**（`HTTP_DEFAULT_MAX_WINDOWS = 16`）：
  窗口是并发发出的，但进程内只有 16 个 LLM 并发额度，超过就要排队、墙钟时间成倍增长，
  而请求自带超时预算——等不到就是白扫还照付 token。要扫更多请显式传 `max_windows`，
  真被截断时 `coverage.maxWindowsHit=true` 且 `ceilingNote` 会写明还有几章没扫。
- 测试：`tests/test_llm_timeout_budget.py`（15 例）、`tests/test_disconnect_cancel.py`（10 例）。
- 测试 `backend/tests/test_llm_timeout_budget.py`（13 例）：思考档加时、连接阶段封顶、
  读超时不重试且报错不甩锅、连接类仍重试、429/5xx 策略不变、流式中途卡住如实报错。
### 前端

- 新增 `frontend/src/api/timeouts.ts`：预算阶梯 `fast/probe/upload/quick/chat/write/long/batch`
  + `JOB_POLL_TIMEOUT_MS`，以及 `timeoutMessage()` / `networkErrorMessage()`。
  规则写在文件头：**凡是请求内会调用模型的端点必须显式选一档，不许吃 30s 默认值**。
- 41 个调用点改用 `TIMEOUTS.*`（**0 处裸数字**），并按上表把预算提到"覆盖后端最坏耗时 + 30s 余量"
  ——留余量是为了让**后端自己的如实报错先到**，而不是前端抢先翻译成误导文案。
- 4 个原本漏设超时的 LLM 端点补上预算：`/brainstorm`、`/generate-rpy`、
  `/settings/test-llm`、`/lore/lookup|inspire`（后者会去外部百科取数，后端连接超时 25s，
  30s 默认值太紧）。
- **心跳计入存活**：`runAgentStream` / `pipelineRunStream` 增加 `onActivity`，
  收到**任何字节**（含 `: keepalive`）都回调；`AgentChat` 的 90s 看门狗改为由它复位，
  文案改成"连接已 90 秒没有任何数据（连心跳都没有）"——判据从"没有业务事件"变成"连接真的死了"。
- 流式路径**不设总超时**（有测试钉住）：给流式设总超时会重新引入同一类 bug。
- 测试 `frontend/src/api/timeouts.test.ts`（70 例）：直接读后端源码解析
  `llm_budget.py` 的常量与 `config.py` 的系数，逐端点校验
  `前端预算 ≥ Σ(每轮预算 × 思考系数) + 30s`、校验后端模块确实用了那个常量、
  校验调用点确实显式设了预算、禁止裸数字、禁止流式设总超时、禁止误导文案回归。

> 这一层是防复发的关键：后端改数字而前端没跟上时，前端测试会红。

## 五、为什么不只是"把数字调大"

把 30s 改成 300s 治不了根：两侧口径不同、读超时被重试导致最坏耗时无上限、
思考档没有加时、心跳被丢弃。这次改动里真正起作用的是三条**结构性**修复：

1. 读超时不重试 → 最坏耗时才是一个有限、可计算的数（否则永远追不上）；
2. 思考档集中加时 → 覆盖全部调用点，而不是逐个调用点去猜；
3. 心跳算存活 + 前端预算 ≥ 后端最坏 + 余量 → 让**后端**的如实报错成为用户看到的第一个错误。

对于"更长远"的三层方案（统一参数 / 交互路径改流式 / 后台作业调优），核实结果：

- **第一层（统一超时参数）**：必要但不充分，本次已做（两处命名真源 + 跨语言不变量测试）。
- **第二层（交互路径改 SSE）**：方向正确，且**已经存在**三处流式实现
  （Agent `/agent/stream`、管线 `/pipeline/run?stream`、协作 `/projects/{id}/events`）。
  本次修的是它们**共有的心跳记账缺陷**；把 `/brainstorm`、`/marks/revise`、门禁等
  同步端点也改成流式，是后续可做项（见第六节）。
- **第三层（后台作业调优）**：作业机制也在（`app/core/jobs.py` + `AgentJob` 表 +
  `/pipeline/run` 的 `async_mode` + 前端 `waitProjectJob` 15 分钟轮询），
  管线和章节回炉都已支持。真正缺的是**同步端点的作业化**：`/brainstorm` 之类的
  多轮调用目前只能在请求内跑完，前端预算被迫拉到 10 分钟级。

## 六、残余风险与未做的事

（原来列在前两条的"客户端放弃后后端仍在跑"与"多窗口扫描可能超出预算"已在本轮修掉：
断开取消见第四节，窗口上界见 `HTTP_DEFAULT_MAX_WINDOWS`。下面是在做的取舍与仍然没做的部分。）

1. **取消只在"正在等模型"的窗口内生效**，且依赖部署链路把断开告知应用层
   （`Request.is_disconnected()`）。代理若不传递断开，行为与改造前一致：不省 token，但不误杀。
   另外，取消意味着这次生成**不会**有结果——所以文案必须区分"同步端点被中止"与
   "后台作业继续跑完"（`timeouts.ts` 已按这个口径写）。
2. **同步端点的预算偏长**：为了覆盖思考档，`chat` 档是 300s、`batch` 档是 900s。
   非思考档下"卡住"要多等一会儿才报错。这是有意的取舍（宁可多等，也不要在结果已生成时掐断），
   但更好的做法是把这些端点作业化/流式化，让预算不再承担这个职责——属于功能级改动，见第五节。
3. **思考档系数的默认值 2.0 是工程取值**，不是实测标定：本环境没有可用的 API Key，
   无法测出各厂商思考档的真实耗时分布。它是可配置的（`LLM_THINKING_TIMEOUT_FACTOR`），
   夹在 1.0–5.0。要真正标定，需要按模型采集线上"首字节/总耗时"分位数再回填。
4. **契约表覆盖的是"在请求内调用模型"的端点**；`/lore/*`（确定性检索，仅外部 HTTP 25s）、
   快照/上传/应用类端点（不调模型）只受"引用命名常量"与
   `test_llm_call_sites_use_named_budgets_only`（源码级：LLM 调用点禁止裸数字）两道约束。

## 七、同类问题的排查结果（"其他模块会不会也这样"）

修完主症之后，专门按**缺陷类别**把整个后端过了一遍（AST 扫描 + 逐条人工核对）：

| 检查项 | 结果 |
| --- | --- |
| 有没有**在循环里**调用模型（轮数随作品规模膨胀 → 最坏耗时无上界） | **没有**。扫出 `beat_check.py`、`recap.py` 两处"疑似"，逐行核对确认都是**准备数据的循环**，模型调用在循环之后（缩进相同但语义在循环外）——属误报 |
| 每个会调模型的 HTTP 路由是否都知道自己的预算 | 共 **23 条**能到达 `chat_completions` 的路由，已全部登记。其中 `/harness/run`、`/ai`、`/pipeline/check` 目前**前端无调用方**（API-only），已在登记表注明 |
| 客户端断开后是否还会白跑 | 见第四节；流式侧本来就有协作式取消，非流式侧现由 `disconnect.py` 覆盖 |
| 会不会有新端点再犯同一个错 | 新增守卫 `backend/tests/test_llm_route_registry.py`：用 AST 自动发现"路由 → 处理函数 → 是否触达模型调用"，漏登记直接红（写完当场就抓到 `/pipeline/run` 漏登记）。已知盲区是**二级间接**调用（如 `/pipeline/gate` 经 `gate.py` → `stage_check_async`），这类在登记表里手工列出并注明 |

### 多轮端点：改成作业，而不是继续加预算

`/brainstorm` 是"2–3 位作家并发 + 责编综合"的**两轮串行**调用，思考档最坏 ~8 分钟。
硬把等待预算拉到 10 分钟级只是"能对上账"，体验依然很差（转圈等 8 分钟）。
所以按仓库既有范式（与 `pipeline/run`、`agent/chapter-revise` 同一套）改造：

- 后端：`BrainstormIn.async_mode`；为 true 时只 `create_job(kind="brainstorm")` 并返回 jobId，
  两轮调用在 detached 后台作业里跑（`job.touch` 报进度、`job.set_result` 存结果，
  异常由 `_run` 兜成 `status=error`）；**同步路径原样保留**给 API 客户端。
- 前端：UI 改走 `startBrainstormJob` + `waitProjectJob`（进度显示"作家们正在各自发言…/责编正在综合…"），
  kickoff 预算回到 `upload`（180s）一档——**不再需要 600s**。
- 契约测试新增 `mode: "job"`：断言调用点真带 `async_mode: true`、后端真注册了该作业 kind，
  且不再按"轮次×预算"算（防止有人改回同步却留着旧预算）。
- 顺带修了测试基建的坑：新增 `db_gate.background_jobs_use_test_db()`——作业在请求结束后自己开
  `app.db.AsyncSessionLocal` 会话，而原夹具只覆盖了 HTTP 的 `get_db`，于是作业写到开发库、
  测试里永远看到 `queued`（表现像"后台任务没执行"，极难查）。

**没有一起改的**：`/marks/revise`（同为两轮）在前端**没有任何 UI 调用方**（只有 API 函数定义），
作业化没有用户可见收益，且它的同步预算 600s 与后端最坏耗时是对得上的，所以留着——
将来真接进 UI 时照同一范式改即可。`/agent/chapter-revise` 早就支持 `async_mode`。

## 八、怎么自查

```bash
# 后端：预算换算、重试策略、思考档加时、预填充加时、报错文案、源码级裸数字约束
cd backend && PYTHONPATH=. .venv/Scripts/python -m pytest tests/test_llm_timeout_budget.py -q

# 后端：上下文预算政策 + "上下文上限 ≤ 预填充加时上限"的跨模块不变量
cd backend && PYTHONPATH=. .venv/Scripts/python -m pytest tests/test_context_budget_policy.py -q

# 后端：耗时分位统计（The Tail at Scale 的"先量后决"）+ "不做 hedging"的源码级守卫
cd backend && PYTHONPATH=. .venv/Scripts/python -m pytest tests/test_latency_stats.py -q

# 后端：多变体按证据排序（Best-of-N）+ logprobs 通道的能力门控
cd backend && PYTHONPATH=. .venv/Scripts/python -m pytest tests/test_variant_select.py tests/test_llm_logprobs.py -q

# 后端：客户端断开 → 中止在飞调用；后台作业不受影响
cd backend && PYTHONPATH=. .venv/Scripts/python -m pytest tests/test_disconnect_cancel.py -q

# 后端：所有能调模型的路由都登记在案（AST 自动发现 + 作业 kind 核对）
cd backend && PYTHONPATH=. .venv/Scripts/python -m pytest tests/test_llm_route_registry.py -q

# 后端：作业化的头脑风暴（需要测试库；无库自动跳过）
cd backend && PYTHONPATH=. .venv/Scripts/python -m pytest tests/test_api_brainstorm_job.py -q

# 前端：逐端点不变量（读后端源码核验）
cd frontend && npx vitest run src/api/timeouts.test.ts

# 看一眼预算真源与契约表
sed -n '1,60p' backend/app/core/llm_budget.py
sed -n '1,80p' frontend/src/api/timeouts.ts
```

复现原 bug 的最短路径（改回旧行为即可看到）：把 `llm_budget.thinking_factor()` 返回 1.0、
或把 `_RETRYABLE_TRANSPORT` 里加回 `httpx.ReadTimeout`，前端契约测试就会指出某一档不够。
复现"白烧 token"：把 `config.disconnect_cancel_enabled` 设为 false 或让
`DisconnectGuard._gone()` 永远返回 False，`test_disconnect_cancel.py` 会红。
复现"漏登记"：在任一端点里加一句 `await run_recap(...)`，`test_llm_route_registry.py` 会红。

## 九、补记：长提示词的预填充加时（同一类 bug 的第二种形态）

用户后来明确要求"上下文限额加长很多甚至不限额不是问题"（质量优先，见
[docs/long-context-policy.md](long-context-policy.md)）。这件事有一个**必然的副作用**：
非流式请求的 read timeout 覆盖的是**预填充 + 整段生成**，预填充耗时随提示词长度线性增长。
只把上下文预算放大而超时不动，就会以另一种形式重演本文档开头的那个 bug——
用户看到「请确认后端已启动」，而后端只是还没吐出第一个字。

所以 `llm_budget` 增加了一条与提示词长度挂钩的加时项：

```
加时 = min(PREFILL_MAX_BONUS, max(0, 提示词字符数 - PREFILL_FREE_CHARS) / PREFILL_CHARS_PER_SECOND)
     = min(60s, (chars - 8000) / 1500)
```

- `PREFILL_FREE_CHARS = 8000`：这个长度以下不加时。既符合事实（小提示词的预填充是秒级），
  也保证**既有行为逐字不变**（`effective_timeout(120) == 120` 仍然成立）。
- `PREFILL_CHARS_PER_SECOND = 1500`：刻意保守的下界。真实预填充（尤其命中上下文缓存时）
  快得多，但排队/冷启动/免费档限流会明显更慢——延续"宁可多等，也不要在结果已生成好时
  把连接掐掉"的取舍。
- **思考档 ×2 与预填充叠加**，两者是不同来源的时间。
- 流式路径同样计入：那里的 timeout 是"多久没有新字节"的空闲上限，而**等第一个字节**
  的时间就包含预填充。
- 文案也变得可执行：`模型响应超时：146s（长上下文预填充 +27s）内没有返回结果…`。

配套的两处对齐（缺一处就会重新失配）：

1. **后端不变量**：`(agent_context.MAX_CONTEXT_MAX_CHARS - PREFILL_FREE_CHARS) /
   PREFILL_CHARS_PER_SECOND ≤ PREFILL_MAX_BONUS`——"允许拼出来的最长上下文，一定落在
   超时预算能覆盖的范围内"（`tests/test_context_budget_policy.py`）。
2. **前端阶梯**：`timeouts.test.ts` 读同一个 `PREFILL_MAX_BONUS`，按
   `基础预算 × 思考档系数 + 预填充上限 + 余量` 逐端点校验，于是
   `quick 240→300s`、`chat 300→360s`、`write 480→540s`、`long 600→660s`、
   `batch 900→1020s`、作业轮询 `15→20min`。唯一豁免的是设置页的连通性测试
   （提示词固定是 `"ping"`，且契约测试会钉住"该模块不得拼装 agent 上下文"）。

## 十、The Tail at Scale：为什么不 hedge（先量后决）

Dean & Barroso 的结论里，对我们最有用的不是那个对策，而是**那句操作方法**：
"看均值没用，看 p99"。此前我们没有任何耗时分布数据——预算按最坏情况推、
取舍靠推理，所以这一轮先补了量测。

### 10.1 量测（新增）

`core/latency_stats.py`：进程内**有界窗口**的分位统计（最近秩，可手算），

- 按 **模型 × 是否思考档 × 能力 kind** 分桶（`deepseek-flash|think|write` 这种键）：
  三者的耗时量级完全不同，混在一起算出的 p99 既不能用来调预算，也不能定位是哪条链路慢；
- 指标：`p50/p95/p99/max/mean`、**超时率**、以及流式的**首字耗时**（`firstToken`）。
  超时必须进样本：只统计成功的请求会把 p99 稀释掉——而尾部正是由超时构成的；
- 边界如实写在模块文档里：**进程内、重启清零、多 worker 不合并、不落库**。
  它的用途是运维判断（"这条链路离预算还有多远"），不是监控系统；要历史 p99 就该写进用量表。
- 只记耗时，不记用户、不记 prompt/输出内容；入口是管理员接口 `GET /admin/llm-latency`。

### 10.2 决定：**不做 hedged request**

论文的 hedge 前提是"**有独立副本**"：同一份请求发给另一台机器，谁先返回用谁的，
超时概率相乘、尾延迟显著下降。我们的处境是：

| 维度 | hedged request 的假设 | 我们的实际 |
|---|---|---|
| 副本 | 多个独立副本（容量互相独立） | **一个上游端点**（DeepSeek/GLM/…，同一个 Key 的同一个池） |
| 第二路的延迟 | 独立抽样，可能更快 | 排在同一段容量后面，**与第一路同分布**，甚至因为挤占而更慢 |
| 收益 | p99 显著下降 | **≈ 0**（没有独立样本可用） |
| 成本 | 被 hedge 的请求 token ×2 | 同样 token ×2，且思考档下输入也可能很大 |

量化：设 hedge 触发比例 p（例如"超过 p95 才开始第二路"→ p≈5%），
一次 hedge 的成本是**双份输入 + 双份输出**（思考档的 reasoning token 也算钱），
所以总成本增加 `≈ p × 100%`；而在单上游下延迟收益 ≈ 0 ——
**用确定的成本换一个不存在的收益**。

### 10.3 我们实际用来治尾部的办法（都已实现）

1. **让尾部可见**：流式首字可见 + 心跳判活（用户不会盯着空白猜）；
2. **让尾部不致命**：多轮端点作业化（`/brainstorm`、章节回炉 → 作业通道，不受 HTTP 超时约束）；
3. **让尾部不浪费**：客户端断开即取消在飞调用（`core/disconnect.py`）；
4. **让预算与之匹配**：预算按最坏情况推、思考档加时、预填充加时（第八/九节）；
5. **把"该并发的"和"不该并发的"分开**：不同 prompt 的独立工作可以并发
   （多变体采样、多窗口扫描，都受 `_LLM_SEMAPHORE` 与各自上界约束），
   而**同一个请求不发第二路**——这条由 `tests/test_latency_stats.py` 的源码级守卫钉住。

将来若真的出现"多上游 Key / 多区域端点"（容量互相独立），hedge 就值得重新评估：
那时**先看 `latency_stats` 的 p95/p99**，再决定触发点（论文建议 p95），
而不是凭感觉打开。
