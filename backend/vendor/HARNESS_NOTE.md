# NovelMaster Harness adaptation

Source: https://github.com/necolo007/NovelMaster (MIT)

Ported into VN Script Studio as `app/core/harness/` + `app/core/pipeline/`.

## Industrial loop (current)

1. **Deterministic full audit** (`harness/audit_full.py`) — AI-flavor + narrative + style Skill  
   Used by: lint, pipeline check/gate, editor pass, Agent `lint_draft`, agent_loop self-review.
2. **Roles** Architect / Writer / Editor — `POST .../harness/run` + pipeline stages.
3. **Plan → Write → Check → Revise×N → Check** — `POST .../pipeline/run`  
   - Default `max_revise_rounds=2` until gate pass or cap.  
   - Check: keyword beats + **LLM semantic beats** when API key present.  
   - Final check: optional **voice** merge (`voice_check`, high→warn by default).  
   - On gate pass + `apply_to_chapter`: structured blocks into chapter.  
   - Every run appends `project.harnessRuns` (capped) + returns `runId` / `trace`.
4. **Quality gate / finalize** — `finalize_chapter_async`: same audit standard as pipeline,  
   optional semantic + voice, structured apply, **LLM ledger enrich** (fallback heuristic), run history.
5. **Writing ledger** — heuristic digest; digest/finalize enrich defaults on.
6. **Observability** — `GET .../pipeline/runs`, stage `trace` (ms, beatMode, blockTypes, revise round).
7. **Tests** — golden (30+) + mock E2E + multi-revise + run history / voice soft-fail; 自动 CI 见 `.github/workflows/ci.yml`（纯单元 + 静态检查），连真库的集成用例走手动 `integration.yml`，端到端走手动 `e2e.yml`。
8. **Agent prefs** — Help 面板可开「声线硬门禁 / 终检声线 / 修正轮次」（localStorage）。

## Product entry (Agent chat)

- 「跑流水线：…」→ pipeline run (+ multi-revise + apply on pass)
- 「文风体检」→ harness lint (full audit)
- 「定稿」→ async finalize (semantic/voice + enrich + history)
- 「更新账本」→ ledger digest (enrich)

## Ops / P0 reliability

- Save conflict: PUT 409 returns structured detail; FE keeps local draft + dialog (force overwrite / take server / download).
- Alembic: real `0001`–`0003` (idempotent); startup runs `alembic upgrade head` then `create_all` safety net.
- Long jobs: `async_mode` on pipeline run & chapter-revise → `jobId` + `GET .../jobs/{id}` poll (in-process store).
- P2: `chapterIndex` hashes on save; content-addressed snapshots (object + hash dedupe); `voiceReports` persist/stale; `LlmProvider` (DeepSeek default).
