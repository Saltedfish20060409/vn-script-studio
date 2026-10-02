# P6–P9 + NL↔RPY 交付摘要

**日期**：2026-10-02  
**状态**：实现完成；自动化相关用例绿；统一手测表如下（手测通过后才 push/部署）。  
**前置**：P0–P5 已通过。

---

## 交付物

| 项 | 要点 |
|----|------|
| P6 | `critique_contract` + `task=critique` + `genre_override`；FE `critiquePayload` + 一键标记 |
| P7 | 多源 ingest + dry-run → Diff 勾选 → `apply-actions`；`INGEST_DIRECT_APPLY` 默认关；LocationLink |
| P8 | 设置命名档标准/增强/最大；chars↔token=1.2；nearLimit 成本估算 |
| P9 | Agent 事件白名单扩展；`onboarding_step`；`analyticsEventsContract`；Admin funnel 挂 Agent 计数 |
| NL↔RPY | `nl_rpy_map` + 保结构 merge + `nlRpyMap`；双变冲突闸；flag 可关回 P5 |

## 统一验收（手测清单）

| # | 项 | 结果 |
|---|----|------|
| 1 | critique → 结构化 issues + 体裁可辨；可建标记 | ☐ |
| 2 | ingest 多源 → Diff → 确认（含 LocationLink） | ☐ |
| 3 | 标准/增强/最大档切换；最大档/近限见成本估算 | ☐ |
| 4 | 埋点：turn/写入/取消后事件可查（或契约测试绿） | ☐ 契约绿 |
| 5 | NL↔RPY：保结构 regenerate；漂移徽章；双变冲突；flag 关回退 P5 | ☐ |
| 6 | 回归：P5 手测 1–6 不回退；清空闸仍在 | ☐ |

通过后才 **push + 部署**（后端长跑勿 `--reload`）。

## 回滚

- `INGEST_DIRECT_APPLY=true` 仅事故  
- `NL_RPY_FULL_MAP=false` → P5 行为  
- critique/ingest 仍可走旧意图；turn 路由表保留  
