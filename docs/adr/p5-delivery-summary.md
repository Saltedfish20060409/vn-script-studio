# P5 交付摘要（ADR 0001）

**日期**：2026-10-02  
**状态**：**P5-A + P5-B 正式通过（2026-10-02）**。  
**门禁**：P4 通过 + P2.5 通过 + 清空 UX 通过 → 已满足。

附带：P0 hotfix（`732154d`）已本地 commit；`docs/adr/*` 下次工程 commit 一并带。

**下一项**：不占 P 编号 — [自然语言 ↔ RPY 完整映射](./nl-rpy-full-mapping.md)。

---

## P5-A writeOps

| op | 路径 | 说明 |
|----|------|------|
| polish / expand / condense / style_transfer | `/agent/turn` + `resolve_write_op` ok | framing 见 `capability_router.write_op_framing` |
| condense | 钩子优先 | `未回收钩子 > 因果主干 > 细节描写`；W05 fixture `shared/test-fixtures/condense_hook_w05.json` |
| style_transfer | `style_transfer_contract` | **验收=盲测 ≥2 处风格差异 + 情节不变**；不做相似度 `< X` 数值闸 |
| chapter_polish | turn `polish` | 不再默认多窗口回炉 |

回滚：前端不发该 op，或把 op 从 `ALL_WRITE_OPS` 移回拒绝集。

### 手测 3 · condense（写死）

- **通过**：输出须含锚句「雨里有人叫了她的旧名字」**或语义等价**（同钩子信息：雨里、有人叫她旧名字）。
- **不通过**：锚句与语义钩子皆无。
- **处理路径**（择一，写进本 ADR 备注）：
  1. 加强 `write_op_framing(condense)` / 注入 must_retain；或
  2. 换更稳的锚句并更新 W05 fixture；或
  3. 明确接受（注明模型波动 + 单测仍覆盖 checker）。

### 手测 4 · style_transfer（写死）

- **通过**：并排看原文 vs 输出，至少能说出 **2 处**风格差异（句式节奏 / 用词温度 / 对白口吻任选），且情节事实不变。
- **不通过**：差异不明显（同义微改）或情节漂移。
- **处理路径**：加强契约措辞 / 加本轮目标风格说明 / 接受并记观察项。

---

## P5-B RPY 中期

### 自动生成条件（`shouldAutoGenerateRpyAfterProseWrite`）

| 条件 | 行为 |
|------|------|
| 无 `rpyFromProseHash`（纯 LN 或未建基线） | **永不**自动；须手动「根据剧本生成」建 hash |
| 已有 hash 且与 prose 指纹一致 | 不自动 |
| 已有 hash 且 stale | 后台自动跟随 |
| 设置 `auto_rpy_after_prose_write` 关 | 不自动，只提示 |

「跟一次」= **第一次手动 generate 建立 hash 后**，此后 stale 时自动跟随。不是「有脚本正文无 hash 就跟一次」。

### 并发

- `createAutoRpyInflight`：新任务 `begin` abort 旧任务；旧结果 `isCurrent` 为 false 时丢弃。
- `generateRpyFromProse(..., signal)` + `http.fetchWithTimeout` 组合外部 abort。
- 测试：`autoRpyInflight.test.ts`「连续两次写入，只有一个任务存活」。

### 阻塞与失败 UX

- **不阻塞写入**：写入后 `busy=false`；RPY 后台跑。
- 会话内：`setError` + `lastContext`。
- **持久**：`rpyIsStale` → 章节列表徽章「脚本待更新」（切章/刷新仍在）；手动或自动生成成功写回匹配 hash 后消失。

### skipEditorReload 范围

- **只跳** `loadEditorFromChapter`（不抢编辑器空串 / 清空闸）。
- **仍刷新**：`applyRemoteProject` → 工程 state、章节列表徽章、状态栏、`scriptPreview` 只读预览（读 `chapter.blocks`）。
- 当前若在 **脚本面编辑器** 且正在清空中，缓冲区不强制重载；切面或再次打开章会看到新 blocks。

### 与清空 UX 正交

- 回归：`autoRpyClearConflict.test.ts`。

---

## 手测清单

1. polish → 气泡 → 写入  
2. expand → 写入  
3. condense → **须含**「雨里有人叫了她的旧名字」或语义等价（见上判定）  
4. style_transfer → **≥2 处**可指风格差异 + 情节不变  
5. 自动 RPY（已建 hash 且 stale）→ 后台更新；连续两次写入只保留后者；列表徽章在失败后仍在  
6. 关设置 → 写入 → 只提示不自动生成  
7. （可选）失败 → 错误条 + 章侧「脚本待更新」→ 手点「根据剧本生成」清除  

1–4 → P5-A。5–6 → P5-B。

---

## 测试

- `tests/test_capability_router.py` / `test_condense_hook_w05.py` / `test_prose_rpy.py`
- `autoRpyAfterWrite.test.ts` / `autoRpyInflight.test.ts` / `autoRpyClearConflict.test.ts`
