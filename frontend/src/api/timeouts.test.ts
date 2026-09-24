/**
 * 超时预算契约：前端每档预算必须覆盖后端的真实最坏耗时。
 *
 * 这一层防的是用户实际踩到的那个 bug：前端按「一个 HTTP 请求」计时、后端按
 * 「一次 LLM 调用 × 重试」计时，于是整类端点满足 `前端预算 < 后端最坏耗时`，
 * 前端先掐断并弹出「请确认后端服务已启动」——后端其实活得好好的。
 *
 * 测试直接读后端源码（`app/core/llm_budget.py` 的命名预算、
 * `app/config.py` 的思考档系数），所以后端改数字而前端没跟上时，这里会红。
 */
import { readFileSync, readdirSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

import { JOB_POLL_TIMEOUT_MS, TIMEOUTS } from "./timeouts";

const API_DIR = fileURLToPath(new URL(".", import.meta.url));
const BACKEND_APP = fileURLToPath(new URL("../../../backend/app/", import.meta.url));
const COMPONENTS_DIR = fileURLToPath(new URL("../components/", import.meta.url));

/** 前端可以比后端"刚好够"多留一点时间，好让后端自己的如实报错先到。 */
const SLACK_MS = 30_000;

function read(file: string): string {
  return readFileSync(file, "utf8");
}

function readApi(file: string): string {
  return read(`${API_DIR}${file}`);
}

/**
 * 去掉注释后再断言"文案"。
 *
 * 注释里会**引用**那句误导文案（「此前写的是……」），直接对全文断言会把
 * 说明文字当违规。判据只该看真正会发给用户的字符串。
 */
function stripComments(src: string): string {
  return src.replace(/\/\*[\s\S]*?\*\//g, "").replace(/(^|[^:])\/\/.*$/gm, "$1");
}

/** 解析 llm_budget.py 里的命名预算（秒）。 */
function backendBudgets(): Record<string, number> {
  const src = read(`${BACKEND_APP}core/llm_budget.py`);
  const out: Record<string, number> = {};
  for (const m of src.matchAll(/^([A-Z][A-Z_]*)\s*=\s*([0-9.]+)\s*$/gm)) {
    out[m[1]] = Number(m[2]);
  }
  return out;
}

/** 思考档加时系数：后端 config 的默认值（环境变量可覆盖，测试按默认值校验）。 */
function thinkingFactor(): number {
  const src = read(`${BACKEND_APP}config.py`);
  const m = src.match(/llm_thinking_timeout_factor:\s*float\s*=\s*([0-9.]+)/);
  expect(m, "config.py 里找不到 llm_thinking_timeout_factor").toBeTruthy();
  return Number(m![1]);
}

/**
 * 预填充加时上限（秒）：长提示词让后端 read timeout 变长，前端必须跟上。
 *
 * 为什么这是**每一轮**都要加、而不是"某一档"的常数：非流式请求的 read timeout
 * 覆盖"预填充 + 整段生成"，而上下文预算放大后（默认 48k 字符，上限 96k），
 * 预填充本身就是几十秒量级。后端 `llm_budget.PREFILL_MAX_BONUS` 与
 * `agent_context.MAX_CONTEXT_MAX_CHARS` 成对，后端有跨模块不变量测试钉着；
 * 这里读同一个数，保证"后端能拼出来的最长上下文"前端也等得起。
 */
function prefillAddMs(): number {
  const budgets = backendBudgets();
  const bonus = budgets.PREFILL_MAX_BONUS;
  expect(bonus, "llm_budget.py 里找不到 PREFILL_MAX_BONUS").toBeGreaterThan(0);
  return bonus * 1000;
}

/**
 * 一轮 = 请求内**串行**的一次 LLM 调用。
 * 并发调用（gather）只算一轮；串行的两段就必须写两轮。
 */
interface Round {
  /** 后端模块（相对 backend/app/），用来确认它真的用了这个预算常量。 */
  file: string;
  /** llm_budget 里的常量名。 */
  constant: string;
}

interface Contract {
  /** 前端源码里定位调用点的锚点。 */
  anchor: string;
  apiFile: string;
  budget: keyof typeof TIMEOUTS;
  rounds: Round[];
  /**
   * `sync`（默认）：请求内跑完，预算必须覆盖所有串行轮次。
   * `job`：**作业化**端点——请求只登记作业，真正的耗时走作业通道
   * （`waitProjectJob` 轮询，不受 HTTP 超时约束），所以预算只需覆盖登记时间；
   * 这条同时要求调用点真的带 `async_mode: true`、且后端注册了对应作业类型。
   */
  mode?: "sync" | "job";
  /** job 模式：前端调用点必须出现这段源码（证明走的是异步分支）。 */
  mustContain?: string;
  /** job 模式：后端必须注册的作业 kind（形如 kind="brainstorm"）。 */
  jobKind?: string;
  /**
   * 这一轮会不会带上"按预算拼装的整书上下文"（默认 true，保守）。
   * 只有**确认提示词固定且极短**的端点才可写 false——那类请求的预填充是秒级，
   * 给它加 60s 只会让"卡住"的报错变迟钝（例如设置页的连通性测试）。
   */
  prefill?: boolean;
  /** 为什么是这些轮数（人工核对过调用结构，写在这里以便复核）。 */
  why: string;
}

const CONTRACTS: Contract[] = [
  {
    // 同步路径（仍保留给 API 客户端/脚本）：两轮串行，预算必须覆盖思考档最坏耗时。
    anchor: "/brainstorm",
    apiFile: "misc.ts",
    budget: "long",
    rounds: [
      { file: "core/lenses/brainstorm.py", constant: "CHAT" },
      { file: "core/lenses/brainstorm.py", constant: "CHAT" },
    ],
    why: "run_brainstorm：2–3 位作家 gather 并发一轮，再让责编综合一轮",
  },
  {
    // UI 走的是作业化路径：预算回到"登记作业"这一档，不再承担两轮生成的耗时。
    anchor: "startBrainstormJob",
    apiFile: "misc.ts",
    budget: "upload",
    rounds: [],
    mode: "job",
    mustContain: "async_mode: true",
    jobKind: 'kind="brainstorm"',
    why: "两轮串行改后台作业：发起只登记，进度/结果走作业通道（waitProjectJob）",
  },
  {
    anchor: "/generate-rpy",
    apiFile: "projects.ts",
    budget: "chat",
    rounds: [{ file: "core/prose_rpy.py", constant: "CHAT" }],
    why: "use_llm 默认 true：正文 → Ren'Py 脚本要过模型（此前漏设超时，吃 30s 默认值）",
  },
  {
    anchor: "/voice-check",
    apiFile: "projects.ts",
    budget: "chat",
    rounds: [{ file: "core/voice_check.py", constant: "CHAT" }],
    why: "单次声线核对",
  },
  {
    anchor: "/recap",
    apiFile: "projects.ts",
    budget: "write",
    rounds: [{ file: "core/recap.py", constant: "WRITE" }],
    why: "单次回述生成，但预算更长",
  },
  {
    anchor: "/marks/revise",
    apiFile: "projects.ts",
    budget: "long",
    rounds: [
      { file: "core/mark_revise.py", constant: "CHAT" },
      { file: "core/mark_revise.py", constant: "CHAT" },
    ],
    why: "revise_marked_text 首轮 + 校验不过时的一轮重写",
  },
  {
    anchor: "/agent/chapter-revise`",
    apiFile: "projects.ts",
    budget: "batch",
    rounds: [
      { file: "core/chapter_revise.py", constant: "WRITE" },
      { file: "core/chapter_revise.py", constant: "LONG" },
    ],
    why: "_chat_json 一轮 + _chat_text 一轮（同步路径；UI 也可走 async_mode 作业）",
  },
  {
    anchor: "/consistency/audit",
    apiFile: "projects.ts",
    budget: "write",
    rounds: [{ file: "core/consistency_audit.py", constant: "WRITE" }],
    why: "单次一致性审计",
  },
  {
    anchor: "/style-memory/learn",
    apiFile: "projects.ts",
    budget: "write",
    rounds: [{ file: "core/style_memory.py", constant: "WRITE" }],
    why: "单次文风记忆学习",
  },
  {
    anchor: "/analysis/facts/scan",
    apiFile: "projects.ts",
    budget: "chat",
    rounds: [{ file: "core/fact_llm.py", constant: "CHAT" }],
    why: "事实抽取",
  },
  {
    anchor: "/analysis/facts/reconcile",
    apiFile: "projects.ts",
    budget: "chat",
    rounds: [{ file: "core/fact_llm.py", constant: "CHAT" }],
    why: "事实对账",
  },
  {
    anchor: "/analysis/consistency-scan",
    apiFile: "projects.ts",
    budget: "long",
    rounds: [{ file: "core/consistency_scan.py", constant: "WRITE" }],
    why: "窗口用 asyncio.gather 并发，按一轮算",
  },
  {
    anchor: "/voice/generate",
    apiFile: "voice.ts",
    budget: "chat",
    rounds: [{ file: "core/character_voice/generate.py", constant: "CHAT" }],
    why: "单次声线样本生成",
  },
  {
    anchor: "/voice/synthesize",
    apiFile: "voice.ts",
    budget: "chat",
    rounds: [{ file: "core/character_voice/synthesize.py", constant: "CHAT" }],
    why: "单次声线心智合成",
  },
  {
    anchor: "/workshop/chat",
    apiFile: "voice.ts",
    budget: "chat",
    rounds: [{ file: "core/character_voice/workshop_chat.py", constant: "CHAT" }],
    why: "角色工坊单轮对话",
  },
  {
    anchor: "/agent/pre-questions",
    apiFile: "projects.ts",
    budget: "quick",
    rounds: [{ file: "core/pre_questions.py", constant: "QUICK" }],
    why: "短问答，预算是 QUICK",
  },
  {
    anchor: "/agent/ingest-settings",
    apiFile: "projects.ts",
    budget: "chat",
    rounds: [{ file: "core/settings_ingest.py", constant: "CHAT" }],
    why: "设定摄入要过模型",
  },
  {
    anchor: "/pipeline/ledger/digest",
    apiFile: "pipeline.ts",
    budget: "quick",
    rounds: [{ file: "core/pipeline/ledger_enrich.py", constant: "MEDIUM" }],
    why: "账本补全，预算 MEDIUM",
  },
  {
    anchor: "/pipeline/gate",
    apiFile: "pipeline.ts",
    budget: "write",
    rounds: [
      { file: "core/pipeline/beat_check.py", constant: "QUICK" },
      { file: "core/voice_check.py", constant: "CHAT" },
    ],
    why: "stage_check_async 串行两段：节拍核对 → 声线核对",
  },
  {
    anchor: "/localization/translate",
    apiFile: "projects.ts",
    budget: "chat",
    rounds: [{ file: "api/v1/projects.py", constant: "CHAT" }],
    why: "AI 代翻一批句子",
  },
  {
    anchor: "/settings/test-llm",
    apiFile: "misc.ts",
    budget: "probe",
    rounds: [{ file: "api/v1/settings.py", constant: "PROBE" }],
    // 提示词是一句固定的探测文本（几百字符），永远不会带整书上下文 → 不加预填充。
    prefill: false,
    why: "测试连接用 PROBE，思考档 ×2 后正好顶到旧的前端 30s 默认值以上",
  },
];

describe("超时预算阶梯", () => {
  it("阶梯单调递增且都不小于 fast", () => {
    const ladder = [
      TIMEOUTS.fast,
      TIMEOUTS.probe,
      TIMEOUTS.upload,
      TIMEOUTS.quick,
      TIMEOUTS.chat,
      TIMEOUTS.write,
      TIMEOUTS.long,
      TIMEOUTS.batch,
    ];
    for (let i = 1; i < ladder.length; i += 1) {
      expect(ladder[i], `阶梯第 ${i} 档应不小于前一档`).toBeGreaterThanOrEqual(
        ladder[i - 1]
      );
    }
    expect(TIMEOUTS.quick).toBeLessThan(TIMEOUTS.chat);
    expect(TIMEOUTS.chat).toBeLessThan(TIMEOUTS.write);
    expect(TIMEOUTS.write).toBeLessThan(TIMEOUTS.long);
    expect(TIMEOUTS.long).toBeLessThan(TIMEOUTS.batch);
  });

  it("异步作业轮询预算单独成档（作业不受 HTTP 超时约束）", () => {
    expect(JOB_POLL_TIMEOUT_MS).toBeGreaterThanOrEqual(TIMEOUTS.batch);
  });

  it("后端命名预算与思考档系数都能读到（否则契约测试是空转）", () => {
    const budgets = backendBudgets();
    expect(budgets.CHAT).toBeGreaterThan(0);
    expect(budgets.WRITE).toBeGreaterThan(budgets.CHAT);
    expect(budgets.LONG).toBeGreaterThan(budgets.WRITE);
    expect(thinkingFactor()).toBeGreaterThanOrEqual(1);
  });
});

describe("每个在请求内调用模型的端点", () => {
  for (const c of CONTRACTS) {
    const isJob = c.mode === "job";

    it(`${c.anchor} 的前端预算覆盖后端最坏耗时（${c.why}）`, () => {
      const budgets = backendBudgets();
      const factor = thinkingFactor();
      if (isJob) {
        // 作业化端点：请求只登记作业，唯一要覆盖的是"登记 + 落库"这段时间，
        // 所以断言的是"至少比 30s 默认值宽裕"，而不是 Σ(轮次×预算)。
        expect(c.rounds, `${c.anchor} 作业化后不该再按轮次算预算`).toEqual([]);
        expect(TIMEOUTS[c.budget]).toBeGreaterThanOrEqual(TIMEOUTS.fast + SLACK_MS);
        return;
      }
      // 后端单轮预算 → 思考档实际生效的预算 → 加上预填充上限 → 串行各轮求和
      const perRoundAdd = c.prefill === false ? 0 : prefillAddMs();
      const neededMs =
        c.rounds.reduce((sum, r) => {
          const base = budgets[r.constant];
          expect(base, `llm_budget.${r.constant} 不存在`).toBeGreaterThan(0);
          return sum + base * factor * 1000 + perRoundAdd;
        }, 0) + SLACK_MS;
      expect(
        TIMEOUTS[c.budget],
        `前端 ${c.budget}=${TIMEOUTS[c.budget]}ms < 后端最坏 ${neededMs}ms`
      ).toBeGreaterThanOrEqual(neededMs);
    });

    it(`${c.anchor} 的后端模块确实用了那个预算常量`, () => {
      for (const r of c.rounds) {
        const src = read(`${BACKEND_APP}${r.file}`);
        expect(
          src.includes(`llm_budget.${r.constant}`),
          `${r.file} 里没有 llm_budget.${r.constant}（预算表已过期）`
        ).toBe(true);
        if (c.prefill === false) {
          // `prefill: false` 是在断言"这个端点的提示词固定且极短"。这条把谎话钉住：
          // 端点所在模块一旦开始拼装整书上下文，它就不再享有豁免。
          expect(
            src.includes("build_agent_context"),
            `${r.file} 开始拼装 agent 上下文了，不能再用 prefill: false 豁免预填充`
          ).toBe(false);
        }
      }
    });

    it(`${c.anchor} 的调用点显式设了 TIMEOUTS.${c.budget}`, () => {
      const src = readApi(c.apiFile);
      const at = src.indexOf(c.anchor);
      expect(at, `${c.apiFile} 里找不到 ${c.anchor}`).toBeGreaterThanOrEqual(0);
      const call = src.slice(at, src.indexOf("});", at));
      expect(call).toMatch(/timeoutMs:\s*TIMEOUTS\.\w+/);
      if (c.mustContain) {
        expect(call, `${c.anchor} 必须走异步分支`).toContain(c.mustContain);
      }
    });

    if (isJob) {
      it(`${c.anchor} 的后端确实注册了作业类型 ${c.jobKind}`, () => {
        // 跨语言：作业 kind 写错（或忘了注册）时，前端会一直轮询一个查不到的作业。
        const src = read(`${BACKEND_APP}api/v1/lenses.py`);
        expect(src, `backend 里找不到 ${c.jobKind}`).toContain(c.jobKind);
      });
    }
  }
});

describe("不允许回落到 30s 默认值", () => {
  it("api 层不再出现裸数字 timeoutMs", () => {
    const offenders: string[] = [];
    for (const f of readdirSync(API_DIR).filter((n) => n.endsWith(".ts") && !n.endsWith(".test.ts"))) {
      const src = readApi(f);
      for (const m of src.matchAll(/timeoutMs:\s*([0-9][0-9_]*)/g)) {
        offenders.push(`${f}: timeoutMs: ${m[1]}`);
      }
    }
    expect(offenders).toEqual([]);
  });

  it("http.ts 的默认预算仍是 fast 档", () => {
    expect(readApi("http.ts")).toContain("const REQUEST_TIMEOUT_MS = TIMEOUTS.fast;");
  });
});

describe("流式路径不设总超时（改为靠心跳判活）", () => {
  it("runAgentStream 不设总超时，并把每次收到字节上报为 activity", () => {
    const src = readApi("projects.ts");
    const fn = src.slice(
      src.indexOf("export async function runAgentStream"),
      src.indexOf("export interface AgentConversationSummary")
    );
    expect(fn).toContain("onActivity");
    expect(fn).not.toContain("timeoutMs");
  });

  it("pipelineRunStream 同样不设总超时", () => {
    const src = readApi("pipeline.ts");
    const fn = src.slice(
      src.indexOf("export async function pipelineRunStream"),
      src.indexOf("export async function waitProjectJob")
    );
    expect(fn).toContain("onActivity");
    expect(fn).not.toContain("timeoutMs");
  });

  it("Agent 看门狗由心跳复位，且不再把「模型慢」说成「配置错」", () => {
    const src = stripComments(read(`${COMPONENTS_DIR}AgentChat.tsx`));
    // 看门狗必须在收到任何字节时复位
    expect(src).toContain("armIdleWatchdog");
    // 并且真的接进了流式调用（第 5 个参数 = onActivity）
    const start = src.indexOf("await runAgentStream(");
    expect(start, "AgentChat 里找不到 runAgentStream 调用").toBeGreaterThanOrEqual(0);
    const call = src.slice(start, src.indexOf(");", src.indexOf("controller.signal", start)));
    expect(call).toContain("controller.signal");
    expect(call).toContain("armIdleWatchdog");
    // 这是误导了两轮用户的那句话：90s 无业务事件 ≠ 模型配置错误
    expect(src).not.toContain("请检查模型配置");
  });
});

describe("报错文案指向真因", () => {
  it("http.ts 不再让用户去检查后端是否启动", () => {
    const src = stripComments(readApi("http.ts"));
    expect(src).not.toContain("请确认后端服务已启动");
    expect(src).not.toContain("请检查网络或后端服务");
    expect(src).toContain("timeoutMessage");
  });

  it("超时文案说明结果会继续跑完并指向运行记录", () => {
    const src = readApi("timeouts.ts");
    expect(src).toContain("运行记录");
  });
});
