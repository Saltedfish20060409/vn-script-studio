# ADR 0002：VN / 轻小说垂直 SOTA 议程

**状态**：Accepted（议程启动）  
**日期**：2026-10-10  
**决策者**：产品负责人 + 工程协作  

## 标题

以「领域垂直指标」而非通用写作榜定义 SOTA；产品约束与评测同生。

---

## 1. 背景

通用 LLM 榜（MMLU / Arena）无法刻画视觉小说与轻小说的核心失败模式：

- 他线事实污染本路线；
- 伏笔埋了不收、或错误重置；
- 假选择 / 不可演说明书腔；
- 声线跑偏却只在写后才发现。

本仓库已有长程暴露率基准（`eval_longrange`）与 Writing Turn（ADR 0001）。  
下一层把 **VN 特异约束**做成写路径一等公民，并用可本地回归的指标定义垂直 SOTA。

## 2. 决策

1. **不追求通用模型 SOTA**；追求「长篇 VN/LN 连贯性」窄任务上的可复现领先。
2. **产品约束与评测同生**：能进 `stage_write` 注入的，必须有对应 metric。
3. **v1 指标轴（本地、零 API）+ 固定权重 overall**：

| ID | 权重 | 含义 | 实现 |
|----|------|------|------|
| `route_isolation` | 0.25 | 他线伏笔隔离率 | `branch_memory` |
| `foreshadow_ending_completeness` | 0.20 | 伏笔落在结局路径回收机会上的比例 | `foreshadow_endings` |
| `capability_probes` | 0.20 | 推理/注意力/记忆/指令遵循画像均值 | `capability_probes` |
| `foreshadow_payoff_graph` | 0.15 | 未回收钩子挂上候选回收场的比例 | `foreshadow_graph` |
| `voice_prior_coverage` | 0.10 | 焦点出场角色有写时指纹先验的比例 | `voice_write_prior` |
| `playtest_hook_density` | 0.05 | 读者证据就绪时钩子注入覆盖率（样本不足 score=None） | `playtest_write_hints` |
| `stageable_blocker_rate` | 0.03 | 草稿可演硬伤（对给定 draft） | `write_gate` |
| `longrange_exposure_synthetic` | 0.02 | 复用长程暴露率（可选） | `eval_longrange` |

缺测或 `score=None` 的轴**不进** overall，出席轴权重重归一。  
`eval --ab` 五维人评/对照**只挂 appendix**，永不进主 overall。  
**免责声明**：本 overall **非通用 Arena**，不得与 LMSYS / 通用写作榜混比。

4. **写路径注入模块**（`vn_write_bundle`）：
   - 分支条件记忆
   - 伏笔支付图强制曝光
   - 可演场景硬约束
   - 声线指纹写时先验

5. **CLI**：`python -m app eval --vn-sota`（可选 `--vn-sota-longrange`、`--overall-table`、`--ab-appendix PATH`）。

## 3. 第二期进度

| 项 | 状态 | 实现 |
|----|------|------|
| flag/变量状态切片 | **已交付** | `flag_slice.py` → `branch_memory.resolve_branch_memory_scope` |
| 伏笔结局路径完备性 | **已交付** | `foreshadow_endings.py` + 写路径注入 + `eval --vn-sota` |
| 能力探针集 | **已交付** | `capability_probes.py`；`AgentTurnIn.run_capability_probes` |
| 子代理隔离 | **已交付** | `subagent_isolation.py`（线程池窄上下文，只回传结论） |
| 读者试玩覆盖 → 钩子密度 | **已交付** | `playtest_write_hints.py`；**样本不足写路径静默**（只 meta） |
| `writing_assist=weak` 安全阀 | **已交付** | `vn_write_bundle` intensity=light |
| 试玩器 → `assumed_flags` | **已交付** | 本机 `assumedFlags.ts` → Turn 请求体 |
| 设置页能力探针 tiers | **已交付** | Turn `capabilityProfile` → 本机只读 |
| 对外盲测挂 overall | **已交付** | 加权 overall + `--overall-table`；`--ab-appendix` 仅附录 |
| 硬锚标签 + 预算 | **已交付** | `<important>` 开闭标签 + `CRITICAL_ANCHOR_BUDGET_CHARS` |
| strategyAdapt 落盘 | **已交付** | `strategy_adapt_log.py`；`VNSS_STRATEGY_ADAPT_LOG=all\|changed\|off` |
| 写路径语义重排 | **已交付** | `semantic_search.rerank_texts`（词面重叠；pgvector 仍可选） |
| 全局记忆 graded | **已交付** | `format_global_memory_for_agent(graded=True)` 写路径默认 |
| 本地小分类器 | **已交付** | `vn_classifiers.py` → 子代理预筛 |
| 真 LLM 子代理 | **已交付（可选）** | `VNSS_LLM_SUBAGENT=1` / 设置页；默认关，失败回落本地 |
| 线上对照盲测 | **已交付** | `eval --deploy-compare` + `docs/deploy-compare.md`；人评为主结论 |
| strategyAdapt bandit | **已交付** | 采纳/拒绝 → `strategy_bandit`；样本不足不覆盖 |
| Embedding 余弦重排 | **已交付** | 有 `EMBEDDING_*` 时混余弦；否则词面 |
| assumed_flags 会话侧车 | **已交付** | `run_state.assumedFlags` |
| harness 诊断面板 | **已交付** | 设置页折叠区 |

## 4. 证伪条件

若连续两季垂直套件 overall 提升但作者主观「更差写」，则约束注入过重——改为按 `writing_assist` 档位关闭 VN 块。

## 5. 后果

- `stage_write` 默认挂 `assemble_vn_write_bundle`（`enrich_context=True`）。
- 新增文件：`branch_memory.py` / `foreshadow_graph.py` / `vn_scene_constraints.py` / `voice_write_prior.py` / `vn_write_bundle.py` / `eval_vn_sota.py`。
