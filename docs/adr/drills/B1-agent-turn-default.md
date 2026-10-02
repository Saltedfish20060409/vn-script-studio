# 演练 ID：B1

日期 / 环境 / 操作者：2026-10-02 / 本地开发（合入 ADR 0001 P1）/ Cursor Agent（记录草案；需产品负责人复验勾选）

前置版本 / commit：P1 合入前工作区（Writing Turn 骨架）

Flag 操作：

1. 默认：`AGENT_TURN_DEFAULT=true`（服务端）+ 前端 `vnss-agent-turn-default-v1=1`（缺省即 true）
2. 回滚：设置 → 模型 → Agent 高级 → 勾选「经典写作通道（`/agent/write`）」  
   （`vnss-agent-legacy-write-v1=1`）；可选再关「写作默认走 Writing Turn」

复现用户路径（步骤）：

1. 打开工程，Agent 说「续写」→ 网络面板应见 `POST …/agent/turn`，SSE 首包 `meta`，随后 `token`/`done`。
2. 打开「经典写作通道」后再次「续写」→ 应见 `POST …/agent/write`（无强制 `meta`），草稿仍打开对照/确认流。
3. 关掉经典写作通道 → 恢复 turn。

期望回滚后行为：旧 `/agent/write` 仍可用；工程正文不被 turn/write 静默改写；会话消息可读写。

实际结果：通过（自动化：`test_agent_turn_*` + `test_agent_write_*` + 前端 `agentTurnFlags.test.ts` / wiring 守卫）。**人工 UI 复验：待产品负责人勾选。**

耗时：自动化约数分钟；人工复验预计 <10 分钟。

残留问题 / 随访：

- P1 chat 仍可能内部调用 `/agent/stream`（P4 前）；「隐藏工具环」以设置开关 + 写作默认路径为准。
- 跨模型 Key（执行说明 3）不在本演练范围；**2026-10-02 已按 ADR 降级：第一期同模型弱结论，跨模型待第二期**。
- DB 通道测试：本机 Postgres `54102` 未开时 skip；有库后执行  
  `pytest tests/test_agent_turn_channel.py tests/test_agent_write_channel.py`。
- 全量 `npm run lint`：2026-10-02 已补跑通过（exit 0）。
