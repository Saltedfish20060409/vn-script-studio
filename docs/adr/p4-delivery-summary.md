# P4 交付摘要（ADR 0001）

**日期**：2026-10-02  
**状态**：**正式通过**（2026-10-02）。  
**门禁**：Capability 路由落地；write 仅 continue/rewrite；相关测试绿；P2.5 已通过。  
**附带事故修复**：快照恢复竞态 hotfix（commit `732154d`）。

---

## 已交付

1. **Capability 路由表**（`backend/app/core/capability_router.py`）
   - `write` / `critique` / `ingest` / `chat`
   - write 仅 `continue` / `rewrite`；P5 ops → HTTP 400
   - critique / chat：薄委托既有 `/agent/stream`（turn meta `delegated`）
   - ingest：薄委托 Diff 引导（不静默直写）

2. **前端意图映射**（`frontend/src/lib/agentTurnRoute.ts`）
   - `write_to_script` → write + continue/rewrite（视选区）
   - `targeted_revise` → write + rewrite（Writing Turn 草稿）
   - critique / chat → turn 薄委托
   - `chapter_revise` / `chapter_polish`：**旁路保留**多窗口作业（P5 再收）

3. **气泡作用域切换**（P3 遗留）
   - 章末追加 / 替换选区 / 替换整章；无选区时禁用「替换选区」
   - 默认值 = 原推断规则；用户可改后再点写入

4. **RPY 短期导正**（并入 P4，非完整映射）
   - doctrine：任何写入面都不是生成 `.rpy` 的入口；引导正文档 +「根据剧本生成」

---

## 产品验证清单

- [x] 续写 → turn `continue` → 气泡 → 写入（章末追加）
- [x] 有选区改写 → turn `rewrite` → 气泡可切换作用域后再写入
- [x] 闲聊 / 审稿 → 经 turn 不 501（薄委托）
- [x] script 面 Agent 不诱导直接吐 `.rpy`；应用「根据剧本生成」
- [x] 整章回炉（chapter-revise）仍可用（旁路）

**结论（2026-10-02）**：P4 **正式通过**。进入 P5（polish/expand/condense/style_transfer）前须先处理「清 RPY 静默清 prose」UX 陷阱（见后续小轮），不阻塞本摘要记为通过。
