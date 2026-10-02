# 清空 UX：确认后再清两面

**日期**：2026-10-02  
**状态**：已实现（前端确认闸）  
**范围**：编辑器清空当前档且会连带清另一面时，先确认再执行 2026-10-01「清两面」规则。  
**不占** P4.5 / P5 编号。

---

## 行为

- **进闸**：`inspectClearImpact.needsConfirm` ⇔ flush 会 `clearedOther`（当前面删光 + 另一面有正文）。
- **弹窗**：取消 / 确认清空两面；正文含另一面约 N 字。
- **取消**：不落盘；编辑器恢复到**清空前最后一次非空缓冲**（含未落盘改动；若无则回落存盘当前面）。含义 = **放弃本次清空，回到清空前的编辑内容**（不是保留空编辑器）。
- **确认**：现有 `flushChapterSurface` 清两面 + status toast。
- **不进闸**：P4.5 空 prose + 空编辑器 no-op；另一面本空；非空改写。

落点：`frontend/src/lib/chapterSurfaces.ts`、`clearConfirmGate.ts`、`StudioApp`（`confirmClearBothSurfacesIfNeeded`）。

---

## 追问留痕（2026-10-02）

### 1. Agent flush 怎么弹？

**同步阻塞**（同一 `confirm` modal），不是异步通知。

路径：`beforeAgentRun` → `flushBeforeAgent` → `await commitEditor()` →（若需）`await confirm(...)` → 用户点完再继续 `buildLatestProject` / `persistProject` → Agent 才开跑。

对齐：

| 用户 | 落盘 | Agent 读到 |
|------|------|------------|
| 确认清两面 | 两面已空 | 清空后工程 |
| 取消 | 不落盘；编辑器恢复清空前缓冲 | 恢复后内容 |

第二道闸：`buildLatestProject` 在仍 `needsConfirm` 时**拒绝静默 flush**，原样返回工程。

测试：`chapterSurfaces.test.ts`「Agent/buildLatest 第二道闸」；弹窗本身走既有 `useConfirm`，无单独 Agent E2E。

### 2. 取消恢复语义

**恢复到清空前的编辑内容**（`lastNonEmptyEditor` 优先，否则存盘当前面）。  
不是「保留空编辑器当作用户只清当前面」。

测试：`clearConfirmGate.test.ts` → `resolveClearCancelRestoreText`。

### 3. 防连弹锁窗口期

**无固定毫秒**。窗口期 = 弹窗从打开到关闭整段（`createClearConfirmLock` 的 in-flight Promise）。

- 连弹：第二次 `joinOrStart` **join 同一 Promise**，不新开弹窗。
- 第二次真实操作：上一轮 `finally` 清掉 in-flight 后可再开。

测试：`clearConfirmGate.test.ts` 两条。

### 4. 「只清当前面」归期

| 项 | 决定 |
|----|------|
| 排期 | **暂不排**（单独立项候选；**不归 P5**——P5 是 writeOps，与 sticky SoT 正交） |
| 前置 | 必须先定章级 **sticky SoT**（prose 空时禁止 blocks 作 `chapter_plain` 回落），否则会复现 2026-10-01 复活 |
| 用户临时路径 | 只能 **取消**（恢复清空前内容）后 **手动**处理另一面；或 **确认清两面**。无「只清一面」按钮 |

---

## 本轮明确不做：「只清当前面」

读侧 `chapter_plain` 仍是 **prose 空 → 回落 blocks**。若只清正文档而保留 blocks，Agent 会再次把「已删」正文当原文（2026-10-01 复活）。

**Follow-up（暂不排 / 单独立项）**：章级 sticky + `chapter_plain` 条件回落 → 再开放「只清当前面」。

---

## 测试

- `frontend/src/lib/chapterSurfaces.test.ts` → `清空 UX：inspectClearImpact 确认闸条件`
- `frontend/src/lib/clearConfirmGate.test.ts` → 锁 + 恢复语义
