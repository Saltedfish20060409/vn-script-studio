# 用女娲.skill 蒸馏作家 → 导入本工作室

女娲（[nuwa-skill](https://github.com/alchaincyf/nuwa-skill)）是 **Cursor / Claude 侧的离线蒸馏工厂**，不是 FastAPI 运行时依赖。

## 推荐流程

1. 在 Cursor 安装女娲：`npx skills add alchaincyf/nuwa-skill`  
2. 对 Agent 说：`蒸馏一个渡航` / `蒸馏一个丸戸史明`（或你指定的轻小说/VN 作者）  
3. 得到 `SKILL.md` 后，**人工清洗**：  
   - 删掉大段可能侵权的原文摘录  
   - 补上「面向视觉小说可演 / 轻小说可读」条款  
   - 明确诚实边界：非本人、禁止仿写原文  
4. 改 frontmatter 为：

```yaml
---
id: author-your-id
name: 显示名
kind: author_lens
persona: author
modes: [review, plot]
budget_chars: 2400
provenance: nuwa-distilled
---
```

5. 正文尽量含：视角一句话 / 心智模型 / 表达 DNA / 决策启发式 / 审阅时问什么 / 剧情参谋时问什么 / 反模式 / 诚实边界  
6. 放入 `backend/app/core/lenses/authors/` 或调用  
   `POST /api/v1/projects/{id}/lenses/import` 导入工程。

## 本仓库已手写的作者卡（女娲五层格式）

文学：村上春树、东野圭吾  
轻小说向：渡航、西尾维新、鎌池和馬  
视觉小说向：奈須きのこ、麻枝准、丸戸史明、虚渊玄、田中罗密欧、林直孝、Looseboy、新岛夕、漆原雪人、Kai  

均为**公开技法启发**，非官方授权人格。可用女娲再蒸馏后替换/增补。

## 注意

- LN/VN **写作底盘**仍由「通用文学编辑」导师包自动注入，作家卡只叠加视角。  
- 不要把女娲 runtime 嵌进后端。  
- 虚构**角色**见角色工坊流水线：[NUWA_CHARACTER_VOICE_WORKFLOW.md](./NUWA_CHARACTER_VOICE_WORKFLOW.md)。  
