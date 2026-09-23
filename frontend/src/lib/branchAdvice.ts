/**
 * 分支改进建议的"翻译层"：把 `/playtest/recommendations` 的原始 JSON 变成给作者看的结论。
 *
 * 与 `lib/analysisReport.ts` / `lib/playtestReport.ts` 同一路子 —— 全是纯函数，
 * 不碰 DOM、不请求网络，所以每个边界（缺字段、`recommendations` 为 null、未知
 * `severity`、`counts` 对不上）都能用单测钉死，而不是在界面上显示 NaN / undefined。
 *
 * 这个端点与前几个最大的不同：它给的不是"事实"而是**改法**（`action`）。
 * 所以这一层有两条硬要求：
 *
 * 1. **`action` 不能被吞掉**。一行建议里 `why` 是依据、`action` 是"具体怎么改"，
 *    少了 `action` 这条建议就退化成泛泛而谈 —— 缺字段时也必须如实说明缺了什么。
 * 2. **`basis === "script-only"` 必须明说"只是还看不出来"，而不是让人以为"没问题"**。
 *    读者数据不够时后端**刻意不报**那些依赖行为的判断（没人选的选项、没人走到的结局、
 *    读者覆盖率），这种"缺席"在界面上极容易被读成"通过"。
 *
 * 输入类型刻意写宽（字段全可选）并单独定义，不直接吃 `api/projects` 的强类型：
 * 后端返回的是宽松 dict，字段可能缺失；面板传进来的强类型对象天然满足这些宽松类型。
 */

import { codeLabel, normalizeSeverity, type FindingSeverity } from "./analysisReport";

/* ------------------------------------------------------------------ 常量 */

/** 与后端 `core/branch_recommendations.MIN_RUNS_FOR_EVIDENCE` 对齐：低于这个试玩次数不做经验判断。 */
export const DEFAULT_MIN_RUNS = 10;

/** 后端把 `min_runs` 夹在 1–10000（见 `api/v1/playtest.py`），界面上不要给出会被静默改写的值。 */
export const MIN_RUNS_RANGE = { min: 1, max: 10000 } as const;

/** 空列表时**必须**跟着的那句话（语义层面的问题不在这条链路的射程内）。 */
export const ADVICE_CAVEAT =
  "这不等于剧本没问题：语义层面的问题（动机、反转、潜台词、文笔）不在这条链路的射程内。";

/** `script-only` 时必须明说的那句：不是"没问题"，是"还看不出来"。 */
export const SCRIPT_ONLY_CAVEAT =
  "「没有依赖读者行为的建议」不等于「没有问题」：没人选的选项、没人走到的结局、读者覆盖率这几类判断，样本不够时后端不会给，也不该被当成通过。";

/** 建议等级的用语刻意与 `analysisReport` 的「错误/警告/提示」不同：这里是**该做什么**，不是事实等级。 */
const ADVICE_SEVERITY_LABELS: Record<FindingSeverity, string> = {
  error: "必须改",
  warn: "建议改",
  info: "可以看看",
  other: "其它",
};

/** 后端真实发过的三个等级；其余一律进「其它」并按未知处理。 */
const KNOWN_SEVERITIES: readonly string[] = ["error", "warn", "info"];

/** 等级是不是后端登记过的（未知等级要在界面上说清楚，而不是混进已知等级里）。 */
export function isKnownSeverity(raw?: string | null): boolean {
  return KNOWN_SEVERITIES.includes((raw ?? "").trim().toLowerCase());
}

/** 建议 code → 给作者看的短名（只登记后端真实会发的 code，见 `core/branch_recommendations.py`）。 */
const ADVICE_CODE_LABELS: Record<string, string> = {
  loop_no_exit: "死循环",
  softlock_menu: "没有可选项的菜单",
  no_effect_menu: "选哪个都一样",
  single_option_menu: "只有一个选项",
  unreachable_ending: "走不到的结局",
  never_selected_option: "没人选过的选项",
  dominant_option: "只有一个真选项",
  low_reader_coverage: "读者没走到多少分支",
  never_reached_ending: "写得到却没人走到的结局",
};

/** 总述里会被单独点名的高价值 code（作者一眼要看到的那个）。 */
const NOTABLE_CODES: readonly string[] = [
  "no_effect_menu",
  "loop_no_exit",
  "softlock_menu",
  "never_selected_option",
];

/* ------------------------------------------------------------------ 小工具 */

function asText(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

function asCount(value: unknown): number {
  return typeof value === "number" && Number.isFinite(value) && value > 0 ? Math.floor(value) : 0;
}

/** `1 条` / `2 条`：中文里不需要复数形态，但数字缺失时必须显示 0 而不是 NaN。 */
function countText(n: number): string {
  return `${asCount(n)} 条`;
}

/* -------------------------------------------------------------- 等级与置信度 */

/** 建议等级的中文短名。未知等级归「等级未知」，**不丢**这条建议。 */
export function adviceSeverityLabel(raw?: string | null): string {
  return ADVICE_SEVERITY_LABELS[normalizeSeverity(raw)];
}

/** severity → 面板 `data-sev` 色语义（沿用现有 error / warn / info / other 四色）。 */
export function adviceSeverityTone(raw?: string | null): FindingSeverity {
  return normalizeSeverity(raw);
}

/** code → 中文短名；没登记的 code 原样露出代号（宁可露出代号，也不编一个可能说错的中文名）。 */
export function adviceCodeLabel(code?: string | null): string {
  const key = asText(code);
  if (!key) return "未标注类别的问题";
  return ADVICE_CODE_LABELS[key] ?? codeLabel(key);
}

export type ConfidenceView = {
  /** "有读者证据" / "纯静态推断" */
  label: string;
  tone: "evidence" | "static" | "other";
  /** 一句解释，说明这个结论有没有读者数据撑腰 */
  hint: string;
};

/**
 * 置信度：`evidence` = 有读者数据支撑，`static` = 纯静态推断。
 *
 * 两者必须在界面上分得开 —— 否则作者会把"剧本结构上推出来的"当成"读者真的这么干过"。
 */
export function confidenceView(raw?: string | null): ConfidenceView {
  const key = asText(raw).toLowerCase();
  if (key === "evidence") {
    return { label: "有读者证据", tone: "evidence", hint: "这条用上了读者实际行为数据。" };
  }
  if (key === "static") {
    return {
      label: "纯静态推断",
      tone: "static",
      hint: "只用剧本结构推出来的，没有读者数据支撑。",
    };
  }
  return {
    label: "置信度未知",
    tone: "other",
    hint: key
      ? `后端返回了没见过的置信度「${asText(raw)}」，按未知处理。`
      : "后端没给置信度字段，按未知处理。",
  };
}

/* -------------------------------------------------------------- 试玩次数门槛 */

/**
 * 输入框 → `min_runs`：空 / 非法回落到默认 10，超出后端范围时夹到 1–10000。
 *
 * 单独做成纯函数是因为"输入框里空着"和"输入了 0"必须都得到**可发送**的值，
 * 否则界面会把 NaN 拼进查询串。
 */
export function parseMinRuns(text: string | number | null | undefined): number {
  const n = typeof text === "number" ? text : Number.parseInt(asText(text), 10);
  if (!Number.isFinite(n)) return DEFAULT_MIN_RUNS;
  return Math.max(MIN_RUNS_RANGE.min, Math.min(MIN_RUNS_RANGE.max, Math.trunc(n)));
}

export type MinRunsView = {
  /** "经验判断门槛：至少 10 次试玩" */
  text: string;
  /** 解释这个门槛到底管什么 */
  hint: string;
  notes: string[];
};

export function minRunsView(minRuns?: number | null): MinRunsView {
  const given = typeof minRuns === "number" && Number.isFinite(minRuns);
  const value = given ? parseMinRuns(minRuns) : DEFAULT_MIN_RUNS;
  return {
    text: `经验判断门槛：至少 ${value} 次试玩`,
    hint: `试玩次数低于 ${value} 次时，后端不做任何经验判断，只出静态建议：小样本下的「没人选」说明不了任何事，报出来只会让人误改剧本。`,
    notes: given ? [] : [`后端没给门槛，这里按默认 ${DEFAULT_MIN_RUNS} 次显示。`],
  };
}

/* ------------------------------------------------------------------ 判断依据 */

export type BasisView = {
  tone: "ok" | "warn" | "other";
  /** 顶部一句话：这一轮的建议到底用了什么 */
  headline: string;
  /** 必须在界面上明说的那句话（`script-only` 时不能让人以为"没问题"） */
  caveat: string;
  /** 后端原样给的样本说明；缺失时给一句兜底 */
  sampleNote: string;
  /** true = 依赖读者数据的判断这一轮缺席 */
  readerAdviceMissing: boolean;
};

/** `basis` + `sampleNote` → 面板顶部那句最容易被误读的说明。 */
export function basisView(basis?: string | null, sampleNote?: string | null): BasisView {
  const key = asText(basis).toLowerCase();
  const note = asText(sampleNote);
  if (key === "script+readers") {
    return {
      tone: "ok",
      headline: "静态分析 + 读者实际行为：两类建议都在。",
      caveat: "",
      sampleNote: note || "后端没有给样本说明。",
      readerAdviceMissing: false,
    };
  }
  if (key === "script-only") {
    return {
      tone: "warn",
      headline: "只有静态建议，读者数据不足：这一轮没有做任何经验判断。",
      caveat: SCRIPT_ONLY_CAVEAT,
      sampleNote: note || "后端没有给样本说明（为什么只有静态建议）。",
      readerAdviceMissing: true,
    };
  }
  return {
    tone: "other",
    headline: key
      ? `后端返回了没见过的判断依据「${asText(basis)}」：按最保守的方式显示（只当静态建议看）。`
      : "后端没给判断依据字段：按最保守的方式显示（只当静态建议看）。",
    caveat: SCRIPT_ONLY_CAVEAT,
    sampleNote: note || "后端没有给样本说明。",
    readerAdviceMissing: true,
  };
}

/* ------------------------------------------------------------------ 行视图 */

/** 宽松的一条建议（后端字段可能缺失）。 */
export type AdviceRecommendation = {
  code?: string;
  severity?: string;
  priority?: number;
  confidence?: string;
  title?: string;
  why?: string;
  /** 具体怎么改 —— 这个端点的核心价值，**不能丢** */
  action?: string;
  /** 位置（如 `ch1/m1`）；没有就空串，界面不渲染空标签 */
  where?: string;
  evidence?: Record<string, unknown>;
};

/** 宽松的响应形状（面板传进来的强类型天然满足）。 */
export type AdviceInput = {
  basis?: string;
  sampleNote?: string;
  minRuns?: number;
  recommendations?: readonly AdviceRecommendation[] | null;
  counts?: Record<string, number> | null;
  summary?: { static?: number; evidence?: number; topCode?: string | null } | null;
  notes?: readonly string[] | null;
};

export type AdviceRowView = {
  key: string;
  severity: FindingSeverity;
  /** 后端原样给的等级（未知等级时用于显示） */
  rawSeverity: string;
  severityLabel: string;
  confidence: ConfidenceView;
  code: string;
  codeLabel: string;
  title: string;
  why: string;
  /** "" = 后端没给改法（界面据此说明"这条只有结论，没有可执行的一步"） */
  action: string;
  actionMissing: boolean;
  /** "" = 没有位置，界面不渲染空标签 */
  where: string;
  priority: number;
};

const SEVERITY_RANK: Record<FindingSeverity, number> = { error: 0, warn: 1, info: 2, other: 3 };

/**
 * 每条建议 → 一行可渲染的视图，**按 severity 排序**（error → warn → info → 未知），
 * 同等级内按 `priority` 降序（后端原始排序口径），再按位置 / code 稳定兜底。
 */
export function adviceRows(input?: AdviceInput | null): AdviceRowView[] {
  const list = Array.isArray(input?.recommendations) ? input!.recommendations! : [];
  const rows = list.filter(Boolean).map((rec, index) => {
    const severity = normalizeSeverity(rec.severity);
    const code = asText(rec.code);
    const where = asText(rec.where);
    const action = asText(rec.action);
    const title = asText(rec.title);
    const why = asText(rec.why);
    const priority =
      typeof rec.priority === "number" && Number.isFinite(rec.priority) ? rec.priority : 0;
    return {
      key: `${code || "rec"}#${where || "-"}#${index}`,
      severity,
      rawSeverity: asText(rec.severity),
      severityLabel: ADVICE_SEVERITY_LABELS[severity],
      confidence: confidenceView(rec.confidence),
      code,
      codeLabel: adviceCodeLabel(code),
      // 缺字段时如实说明缺了什么：宁可写"后端没给标题"，也不留一个空白行
      title: title || (code ? adviceCodeLabel(code) : "（后端没给标题）"),
      why: why || "（后端没给依据）",
      action,
      actionMissing: action === "",
      where,
      priority,
    } satisfies AdviceRowView;
  });
  return rows.sort(
    (a, b) =>
      SEVERITY_RANK[a.severity] - SEVERITY_RANK[b.severity] ||
      b.priority - a.priority ||
      a.where.localeCompare(b.where) ||
      a.code.localeCompare(b.code)
  );
}

export type AdviceGroupView = {
  severity: FindingSeverity;
  label: string;
  rows: AdviceRowView[];
};

/** 按 severity 分组（顺序固定），空组不出现；未知等级进「等级未知」而不是被丢掉。 */
export function adviceGroups(rows?: readonly AdviceRowView[] | null): AdviceGroupView[] {
  const buckets = new Map<FindingSeverity, AdviceRowView[]>();
  for (const row of rows ?? []) {
    if (!row) continue;
    const list = buckets.get(row.severity);
    if (list) list.push(row);
    else buckets.set(row.severity, [row]);
  }
  const out: AdviceGroupView[] = [];
  for (const severity of ["error", "warn", "info", "other"] as FindingSeverity[]) {
    const list = buckets.get(severity);
    if (list?.length) out.push({ severity, label: ADVICE_SEVERITY_LABELS[severity], rows: list });
  }
  return out;
}

/* ------------------------------------------------------------------ 总述 */

export type AdviceSummary = {
  counts: { error: number; warn: number; info: number; other: number; total: number };
  /** 一句话总述：几条必须改、几条建议改，其中几处是…… */
  headline: string;
  /** 置信度构成 */
  confidenceText: string;
  /** 与后端 `counts` / `summary` 对不上时如实说明的行 */
  notes: string[];
};

/**
 * 一句中文总述 + 计数。
 *
 * 计数一律**自己从列表重算**，后端 `counts` 只用来核对：两处不一致时按列表实际内容显示，
 * 并把分歧写出来（后端按 severity 原样累加，将来加等级时两边口径可能不同）。
 */
export function adviceSummary(input?: AdviceInput | null): AdviceSummary {
  const rows = adviceRows(input);
  const counts = { error: 0, warn: 0, info: 0, other: 0, total: rows.length };
  const confidence = { static: 0, evidence: 0, other: 0 };
  const byCode = new Map<string, number>();
  for (const row of rows) {
    counts[row.severity] += 1;
    if (row.confidence.tone === "evidence") confidence.evidence += 1;
    else if (row.confidence.tone === "static") confidence.static += 1;
    else confidence.other += 1;
    if (row.code) byCode.set(row.code, (byCode.get(row.code) ?? 0) + 1);
  }

  const parts: string[] = [];
  if (counts.error) parts.push(`${counts.error} 条必须改`);
  if (counts.warn) parts.push(`${counts.warn} 条建议改`);
  if (counts.info) parts.push(`${counts.info} 条可以看看`);
  if (counts.other) parts.push(`${counts.other} 条其它（等级未知）`);

  let headline = "这一轮没有任何建议。";
  if (parts.length > 0) {
    const notable = NOTABLE_CODES.find((code) => (byCode.get(code) ?? 0) > 0);
    const tail = notable
      ? `：其中 ${countText(byCode.get(notable) ?? 0)}是「${adviceCodeLabel(notable)}」`
      : "";
    headline = `${parts.join("、")}${tail}。`;
  }

  const confidenceParts: string[] = [];
  if (confidence.evidence) confidenceParts.push(`${confidence.evidence} 条有读者证据`);
  if (confidence.static) confidenceParts.push(`${confidence.static} 条纯静态推断`);
  if (confidence.other) confidenceParts.push(`${confidence.other} 条置信度未知`);
  const confidenceText =
    confidenceParts.length > 0 ? `置信度：${confidenceParts.join("，")}。` : "";

  const notes: string[] = [];
  if (!Array.isArray(input?.recommendations)) {
    notes.push("后端返回里没有建议列表（字段缺失），下面按「没有建议」显示。");
  }
  const reported = input?.counts;
  if (reported && typeof reported === "object") {
    const diffs: string[] = [];
    for (const [key, actual] of [
      ["error", counts.error],
      ["warn", counts.warn],
      ["info", counts.info],
    ] as const) {
      const said = reported[key];
      if (typeof said === "number" && Number.isFinite(said) && said !== actual) {
        diffs.push(`${ADVICE_SEVERITY_LABELS[key]} 后端报 ${said} 条、列表里 ${actual} 条`);
      }
    }
    const saidTotal = reported.total;
    if (typeof saidTotal === "number" && Number.isFinite(saidTotal) && saidTotal !== counts.total) {
      diffs.push(`合计 后端报 ${saidTotal} 条、列表里 ${counts.total} 条`);
    }
    if (diffs.length > 0) {
      notes.push(`后端计数与列表内容对不上（${diffs.join("；")}）：界面按列表实际内容显示。`);
    }
  }
  const reportedSummary = input?.summary;
  if (reportedSummary && typeof reportedSummary === "object") {
    const saidEvidence = reportedSummary.evidence;
    const saidStatic = reportedSummary.static;
    if (
      (typeof saidEvidence === "number" && saidEvidence !== confidence.evidence) ||
      (typeof saidStatic === "number" && saidStatic !== confidence.static)
    ) {
      notes.push(
        `后端说本轮有 ${asCount(saidEvidence)} 条读者证据、${asCount(saidStatic)} 条纯静态，与列表里逐条统计（${confidence.evidence} / ${confidence.static}）对不上：按列表显示。`
      );
    }
  }
  return { counts, headline, confidenceText, notes };
}

/* ------------------------------------------------------------------ 空列表 */

export type EmptyAdviceView = {
  headline: string;
  caveat: string;
  /** 后端 notes 原样带出（去掉与 caveat 重复的那句） */
  notes: string[];
};

/**
 * 空列表的文案。
 *
 * 两句话缺一不可：**"没有发现结构性问题"**（客观事实）与
 * **"这不等于剧本没问题"**（防止把"射程之外"读成"通过"）。
 */
export function emptyAdvice(input?: AdviceInput | null): EmptyAdviceView {
  const basis = basisView(input?.basis, input?.sampleNote);
  const headline = basis.readerAdviceMissing
    ? "没有发现结构性问题（本轮只做了静态分析，读者数据不足）。"
    : "没有发现结构性问题。";
  const notes = (input?.notes ?? [])
    .filter((n): n is string => typeof n === "string" && n.trim() !== "")
    .filter((n) => !n.includes("语义层面"));
  return { headline, caveat: ADVICE_CAVEAT, notes };
}

/* ------------------------------------------------------------------ 参数是否已失效 */

export type AdviceStaleView = { stale: boolean; reason: string };

/**
 * 界面上的开关 / 门槛改过之后，已经拿到的结果就不再对应现在这套参数了。
 *
 * 这里只说"参数变了、下面还是上一次的结果"，**不自动重新请求**：
 * 面板与其它子标签一致 —— 只有作者点按钮才发请求。
 */
export function adviceStale(
  input?: AdviceInput | null,
  opts?: { minRuns?: number; includeReaders?: boolean } | null
): AdviceStaleView {
  if (!input) return { stale: false, reason: "" };
  const wanted = parseMinRuns(opts?.minRuns);
  const have = parseMinRuns(input.minRuns);
  if (wanted !== have) {
    return {
      stale: true,
      reason: `当前门槛是 ${wanted} 次，下面是按 ${have} 次算出来的，点「重新生成建议」才会生效。`,
    };
  }
  if (opts?.includeReaders === false && asText(input.basis) === "script+readers") {
    return {
      stale: true,
      reason: "现在勾掉了「读读者数据」，下面是带读者数据算出来的，点「重新生成建议」才会生效。",
    };
  }
  return { stale: false, reason: "" };
}
