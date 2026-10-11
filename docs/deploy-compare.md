# 线上 Writing Turn vs 本地新代码对照

## 结论怎么读

| 读数 | 回答什么 | 能否单独宣称「更好」 |
|------|----------|----------------------|
| 人评五维盲测（甲/乙） | 写感是否更好 | **主结论：可以** |
| `structureGate` / vn-sota | 结构有没有变坏 | 否，只作辅证与门禁 |
| 模块是否增多 | — | 否 |

人评完成前，**不得**对外说「已超过线上部署」。

## 环境变量

| 变量 | 含义 |
|------|------|
| `VNSS_BASELINE_URL` | 线上 API 根，如 `https://your.domain`（勿带尾斜杠；可带 `/api/v1`） |
| `VNSS_BASELINE_TOKEN` | 登录后的 Bearer access token |
| `VNSS_BASELINE_PROJECT_ID` | 线上用于对照的工程 id（建议用与夹具同设定的副本） |

本地臂使用 `.env` 里的 `DEEPSEEK_*`（与线上**同一模型名**时结论才可比）。

## 命令

```bash
# 1) 结构门禁（本地，零线上调用）
python -m app eval --vn-sota --overall-table -o vn-sota-now.json

# 2) 双臂出稿 + 盲评包
python -m app eval --deploy-compare --cases 5 -o compare/

# 3) 打开 compare/blind-deploy.md，按 docs/blind-ab.md 打分
# 4) 评完再看 compare/blind-deploy-key.json 拆封
```

可选：

- `--vn-sota-gate`：结构未过则 CLI 退出码非 0  
- `--scores scores.json`：把人评汇总挂进 vn-sota appendix（不进主 overall）  
- `--skip-deployed`：只跑本地臂（调试用，不能得出对线上结论）

## 通过线

1. `structureGate.passed == true`（overall 差 ≥ −ε）  
2. 人评：local 五维均分 ≥ deployed，一票否决不更多  
3. 样本：≥ 5 用例；单评估者须标注局限  

## 夹具

- 用例：`backend/app/fixtures/vn_compare/cases.json`  
- 工程：`backend/app/fixtures/vn_compare/project.json`  
- 结构基线：`backend/app/fixtures/vn_compare/vn_sota_baseline.json`  

更新基线（仅当有意接受结构变化时）：

```bash
python -m app eval --deploy-compare --write-baseline
```
