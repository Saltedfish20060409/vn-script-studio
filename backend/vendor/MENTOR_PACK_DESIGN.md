# 写作导师包（Writing Mentor Pack）设计

面向 **轻小说 / 视觉小说** 剧本工作室。导师包给 Agent「可切换的创作方法论人格」；  
**不**替代项目级 `style_guide.md`（硬门禁），也**不**替代角色卡（人设事实）。

女娲.skill 等工具可在 **离线** 蒸馏出 `MENTOR.md`；本工作室 **运行时只加载与注入**。

---

## 1. 分层关系（谁说了算）

| 层级 | 文件/数据 | 作用 | 冲突时 |
|------|-----------|------|--------|
| L0 硬门禁 | `pipeline/style_guide.md` | Do NOTs / 质量门禁 | **永远优先** |
| L1 工程工艺 | `writing_craft` Skills | 反倾倒、接章末、VN 可演 | 次于 L0 |
| L2 导师包 | `mentors/*.md` + 工程选用 | 选题节拍、文风偏好、审稿口吻 | 不得推翻 L0 |
| L3 角色卡 | Character voice/bio | 谁在说话、欲望/软肋 | 对白事实优先于导师文风炫技 |
| L4 账本 | `writingLedger` | 已发生事实 / 伏笔 | 禁止推翻 |

一句话：导师教「怎么写得更像 LN/VN」，style_guide 管「什么绝对不许写」。

---

## 2. 包格式：`MENTOR.md`

每个包一个 Markdown，可选 YAML frontmatter。

```yaml
---
id: ln-vn-stagecraft
name: 轻小说×视觉小说舞台导师
version: "1.0"
kind: writing_mentor
media: [light_novel, visual_novel]
locale: zh-Hans
tags: [dialogue, beats, renpy, anti-exposition]
# 建议注入的流水线阶段
stages: [plan, write, check]
# 运行时裁剪预算（字符）
budget_chars: 2800
# 来源说明（蒸馏/手写）；勿塞进版权正文
provenance: handcrafted
---
```

正文固定六节（可缺省，加载器按节抽取）：

1. **人格一句话** — 这位导师怎么说话、关心什么  
2. **心智模型** — 3～7 条 LN/VN 向创作框架（非名人鸡汤）  
3. **决策启发式** — 面对「这段怎么写」时的 if/then  
4. **表达 DNA** — 推荐的句长、对白密度、旁白比例、钩子习惯  
5. **反模式** — 明确不做（可与 style_guide 重叠，但侧重方法论）  
6. **阶段检查清单** — Plan / Write / Check 各 3～5 条可勾选项  
7. **诚实边界**（可选）— 本包不擅长什么  

约束：

- 写 **技法与判断**，不粘贴小说原文大段。  
- 针对 **可上演脚本**：对白、可见动作、menu 代价、章末钩子。  
- 「轻小说可读 → 视觉小说可演」双向：大段心理要压成戏。

---

## 3. 存储与选用

### 3.1 仓库内置（只读种子）

```
backend/app/core/mentors/
  schema.md           # 本说明的机读摘要可放 loader docstring
  template.md         # 空白模板
  packs/
    ln-vn-stagecraft.md     # 默认：舞台与对白
    ln-hook-and-heat.md     # 钩子与类型热度（恋爱/学园等）
```

### 3.2 工程级选用（可写）

`VnProject.writingMentors`：

```ts
{
  activeIds: string[];      // 默认 1 个完整写作导师；不做多人格日常切换
  customPacks?: Array<{     // 可选：整包替换导入
    id: string;
    name: string;
    markdown: string;
    updatedAt: string;
  }>;
}
```

用户级（可选二期）：`UserSettings.mentorLibrary` —— 跨工程复用导入包。

### 3.3 离线蒸馏工作流（女娲等）

1. 在 Cursor 用女娲蒸馏「公开作家 / 自拟方法论」→ 得到 SKILL.md  
2. **人工改写为 MENTOR.md 六节**，删版权敏感正文，补 LN/VN 舞台条款  
3. 导入工程 `customPacks` 或放入 `packs/` 开源种子  

不要把女娲 runtime 嵌进 FastAPI。

---

## 4. 运行时注入

### 4.1 拼装顺序（Agent / Pipeline）

```
system ≈
  AGENT_SYSTEM
  + writing_craft (L1)
  + style_guide.prompt_block (L0)
  + mentors.prompt_block(active) (L2)   // 新增
user ≈
  context (bible / chapter / ledger)
  + user message
```

### 4.2 API（建议）

| 方法 | 路径 | 说明 |
|------|------|------|
| GET | `/mentors` | 列出内置包 meta |
| GET | `/mentors/{id}` | 取全文 |
| GET | `/projects/{id}/mentors` | 工程选用 + 自定义 |
| PUT | `/projects/{id}/mentors` | 更新 `activeIds` / 导入自定义 |
| POST | `/projects/{id}/mentors/import` | body: markdown，校验 frontmatter |

Agent 请求可带 `mentor_ids?: string[]` 覆盖工程默认；空则用 `activeIds`。

### 4.3 裁剪

- 单包 `budget_chars` 默认 2800；双包合计 ≤ 4500。  
- 优先保留：人格一句话 + 反模式 + 当前 `stage` 的检查清单 + 心智模型标题列表。  

### 4.4 与流水线阶段

| 阶段 | 导师包侧重 |
|------|------------|
| plan | 节拍、信息投放、menu 代价、钩子 |
| write | 表达 DNA、对白毛边、可演动作 |
| check / revise | 阶段检查清单 + 反模式 |

---

## 5. UI（最小）

Agent 浮窗：不必恢复按钮墙。自然语言即可：

- 「用舞台导师帮我看这场戏」  
- 「切换导师：钩子热度」  

二期：设置或工程页一个下拉「写作导师（可多选≤2）」。

---

## 6. 种子包规划

| id | 定位 |
|----|------|
| `ln-vn-editor` | **唯一内置**：完整 LN/VN 文学编辑（可演、钩子、类型热度合一） |

不做「舞台 / 钩子」等多人格切换——那会退化成岗位 UI。自定义导入仍可用于替换整份方法论，不是日常切换。

旧 id `ln-vn-stagecraft` / `ln-hook-and-heat` 运行时映射到 `ln-vn-editor`。

---

## 7. 验收标准

- 不启用导师时行为与现网一致。  
- 启用后，续写/流水线 system 中可见 `## 写作导师：…` 块。  
- 导师建议与 style_guide 冲突时，检查/门禁仍只执行 style_guide + harness lint。  
- 导入无 frontmatter 的女娲原文也能降级解析（整篇当正文，id 用文件名）。  

---

## 8. 实现切片（建议）

1. **本轮**：目录 + template + 2 种子包 + `mentor_pack.py` 加载/拼装（尚未接 API 也可单测）。  
2. **下一轮**：工程字段 + API + Agent/pipeline 注入。  
3. **再下一轮**：导入女娲产物的简单清洗提示 + UI 选用。
