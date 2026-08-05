# 角色工坊流水线（语料 → 思维包 → 对话）

应用内路径：**设定角色卡** → 顶栏 **角色工坊** → 塑形语料 → 合成/导入思维包 → 与角色对话或角色互聊。

女娲（[nuwa-skill](https://github.com/alchaincyf/nuwa-skill)）仍是 **Cursor / Claude 侧离线工厂**，不进 FastAPI。应用内「合成思维包」是同结构的轻量版，立刻可解锁对话；女娲用于加深替换。

## 塑形（加厚语料）

| 通道 | 作用 |
|------|------|
| 三选一 | 同一场景三组差异对白，定感觉方向（冷启动） |
| 长场次 | 8～12 轮可演对白，整段入库（高密度） |
| 扮演采访 | 提问 + 三选一/手写回答，喂心智与反模式 |
| 手写金句 | 作者自写台词作金标准 |
| 剧本抽取 | 从章节已有对白勾选入库 |
| 对话回灌 | 工坊聊到满意后「存入正例」 |

合成门槛（满足其一即可，仍可强制）：≥6 条短正例，或场景覆盖 ≥5，或角色台词字量 ≥800，或长场次 ≥2，或采访 ≥4 且字量 ≥400。

## 思维包

1. 工坊「思维包」区 → **合成思维包**（女娲五层缩略：视角 / 心智 / 表达 DNA / 启发式 / 审阅问句 / 反模式 / 诚实边界）  
2. 或 **导出女娲包** → Cursor 安装女娲后蒸馏加深 → **导入思维包**  

frontmatter 建议：

```yaml
---
id: character-your-id
name: 显示名
kind: character_lens
persona: character
modes: [voice, write]
budget_chars: 2400
provenance: nuwa-distilled
---
```

**必须有非空思维包才能进入对话区。**

## 对话

- **与 TA 聊**：用户 ↔ 焦点角色（注入思维包 + 正例）  
- **角色互聊**：两个已有思维包的角色，用户出题/旁白后生成交锋  

写作 Agent / 语气检查仍会注入思维包与语料。冲突优先级：`style_guide` > 写作导师 > **角色思维包/语料** > 账本事实。

## API 摘要

- `POST .../voice/generate`：`kind=preference|scene|interview`  
- `POST .../voice/accept` / `synthesize` / `export` / `import-mind`  
- `POST .../workshop/chat`：`mode=user|duo`（duo 需 `partner_id`）  
