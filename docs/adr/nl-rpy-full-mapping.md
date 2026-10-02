# ADR：自然语言 ↔ RPY 完整映射

**状态**：Proposed（单独立项，**不占** ADR 0001 的 P 编号）  
**日期**：2026-10-02  
**前置**：

| 阶段 | 归属 | 状态 |
|------|------|------|
| 短期导正（doctrine / 双面 SoT / 清空闸） | P4 + P4.5 | 已通过 |
| 中期打通（条件自动 generate、禁静默 raw、hash 跟随） | P5-B | 已通过 |
| **完整映射** | **本 ADR** | 未开工 |

---

## 1. 问题

当前工程是**双面存盘**（`prose` SoT + `blocks` 脚本面），转换是**单向、章级、可丢结构**的：

- prose → RPY：`generate_rpy_from_prose`（成功则写 `rpyFromProseHash`）
- RPY → prose：无保真回写；手调 label / menu / characterId 在全文 replace 时易丢

「完整映射」指：两端可互推、结构资产可锚定、漂移可解释——不是再加一个自动按钮。

## 2. 非目标（本 ADR 明确不做）

- 不并入 P6–P9；不占用 Writing Turn 核心门禁编号。
- 不回退「只清当前面」而不做 sticky SoT（既有产品否定项）。
- 不把完整映射当成 P5 的尾巴补丁。

## 3. 设计须单独回答（开工前写清）

1. **锚定单位**：句 / 段 / 块 / label？跨面 id 如何分配与持久化？
2. **冲突策略**：手调 RPY 与新 prose 同时变时，以谁为准、如何三路合并或提示？
3. **结构资产表**：哪些字段必须 round-trip（label id、menu、条件、characterId…）？
4. **验收**：除盲测外，需要哪些确定性夹具（结构钉死 / 哈希 / 差分）？
5. **回滚**：关闭完整映射时，是否回退到 P5「hash 跟随 + 章级 regenerate」？

## 4. 建议交付切片（设计通过后再排期）

1. 映射模型 + 存盘字段（不破坏现有章节可读）
2. prose→RPY 保结构 regenerate（相对今日整章重排）
3. RPY→prose 投影（只读或可选写回）
4. 漂移 UI（与「脚本待更新」徽章衔接）
5. 夹具与 ADR 验收表

## 5. 与 ADR 0001 的关系

Writing Turn 第一期核心（P0–P5）**已收口**。本文件是旁路产品线；进度与 0001 附录互链，但不阻塞 P6+。

参见：

- [p4-delivery-summary.md](./p4-delivery-summary.md)（短期导正）
- [p5-delivery-summary.md](./p5-delivery-summary.md)（中期打通）
- [0001-writing-turn-orchestration.md](./0001-writing-turn-orchestration.md)（P5 正式通过留痕）
