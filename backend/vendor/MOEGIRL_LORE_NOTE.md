# 萌娘百科 Lore 接入说明

本工作室用萌娘百科作 **ACG 术语 / 套路启发**，不是整站镜像。

## 原则

1. **按需 API**：只通过 `api.php` 搜索与 intro extract，不整站爬。
2. **CC BY-NC-SA**：署名、非商用整页复用；工程内只存精炼工艺卡。
3. **写表现勿念标签**：Agent 注入工艺卡时明确禁止把百科正文写进剧本。
4. **离线种子**：常见属性/类型（傲娇、三无、世界系等）可无网使用。

## 配置

```env
MOEGIRL_ENABLED=true
MOEGIRL_API_BASE=https://zh.moegirl.org.cn/api.php
MOEGIRL_USER_AGENT=VNScriptStudio/0.1 (...)
```

## API

- `GET  /projects/{id}/lore/meta`
- `GET  /projects/{id}/lore/checklist`
- `POST /projects/{id}/lore/search|lookup|inspire`
- `GET|POST|DELETE /projects/{id}/lore/cards`

Agent / Harness Writer 会自动注入匹配到的工艺卡。
