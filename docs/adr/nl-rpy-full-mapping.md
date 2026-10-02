# ADR：自然语言 ↔ RPY 完整映射

**状态**：Accepted（与 P6–P9 同一次大交付）  
**日期**：2026-10-02  
**前置**：

| 阶段 | 归属 | 状态 |
|------|------|------|
| 短期导正 | P4 + P4.5 | 已通过 |
| 中期打通 | P5-B | 已通过 |
| **完整映射** | **本 ADR** | 本交付实现 |

---

## 1. 问题

双面存盘（`prose` + `blocks`）转换曾是单向章级、易丢结构。「完整映射」= 两端可互推、结构可锚定、漂移可解释。

## 2. 设计钉死

### 2.1 锚定单位

- RPY：`ScriptBlock.mapId`（可选；缺则生成稳定 id）。
- 章级 `nlRpyMap`：`{ version, proseFingerprint, blocksFingerprint, segments: [{ id, proseStart, proseEnd, mapIds[] }] }`。
- **不在** prose 正文插入不可见标记。

### 2.2 冲突策略

- 双指纹：仅 prose 变 / 仅 blocks 变 / 双变。
- 双变 → 冲突面板（保留 prose / 保留脚本 / 分段重映射）；禁止静默盖写。
- 单变 → 可一键按映射更新对面。

### 2.3 结构资产 round-trip

尽量保留：`label.id/name`、`menu` 跳转、`characterId`/`defineName`、条件、音乐/场景标签。  
`generate_rpy_from_prose` 保 `mapId` regenerate；未对齐块进「未映射」区。

### 2.4 RPY→prose

- 默认只读投影；写回须确认闸。

### 2.5 Flag / 回滚

- `NL_RPY_FULL_MAP` 默认开；关 → P5（hash + 章级 generate）。

### 2.6 验收夹具

- 含 menu/label 的章 regenerate 后 mapId/跳转仍在。
- 双变不静默。
- 与清空闸 / auto-RPY inflight 正交。

## 3. 与 ADR 0001

不占 P 编号；与 P6–P9 同一次统一验收。见 [p6-p9-delivery-summary.md](./p6-p9-delivery-summary.md)。
