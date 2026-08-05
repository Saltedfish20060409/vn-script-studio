# 工程化写作流水线（内置于统一 Agent）

流水线与 NovelMaster 式 Harness **不是「岗位」**，而是责编 Agent 的后台能力：

- 日常对话 / 快捷任务 → `POST /agent`（风格 Skill + 账本硬锚自动注入）
- 写作流水线 → `POST .../pipeline/run`（Plan→Write→Check→Revise）
- 文风体检 / 定稿门禁 / 账本 → `pipeline/gate`、`harness/lint`、`ledger/digest`

前端：一个 Agent 对话；工具条上的「写作流水线」等是能力入口，无需切换角色。

风格 Skill：`backend/app/core/pipeline/style_guide.md`（原则 → 规则 → 检查项）。
