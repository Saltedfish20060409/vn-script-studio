/** 写作辅助强度（本机）：映射到后端 writing_assist → WritingStrategyProfile。 */

export type WritingAssistStrength = "strong" | "mid" | "weak";

const KEY = "vnss-writing-assist-v1";
const CAP_KEY = "vnss-capability-profile-v1";

export const DEFAULT_WRITING_ASSIST: WritingAssistStrength = "strong";

export type CapabilityProfileSnapshot = {
  at?: string;
  reasoning?: number;
  attention?: number;
  memory?: number;
  instruction_following?: number;
  tiers?: {
    reasoning?: string;
    attention?: string;
    memory?: string;
    instruction_following?: string;
  };
};

export function loadWritingAssist(): WritingAssistStrength {
  try {
    const raw = (localStorage.getItem(KEY) || "").trim().toLowerCase();
    if (raw === "strong" || raw === "mid" || raw === "weak") return raw;
  } catch {
    /* ignore */
  }
  return DEFAULT_WRITING_ASSIST;
}

export function saveWritingAssist(value: WritingAssistStrength): void {
  try {
    localStorage.setItem(KEY, value);
  } catch {
    /* ignore quota */
  }
}

/** 本场守卫建议抬档时：只升不降。 */
export function maybeBumpWritingAssist(
  suggested?: string | null
): WritingAssistStrength | null {
  const next = (suggested || "").trim().toLowerCase();
  if (next !== "strong" && next !== "mid" && next !== "weak") return null;
  const order: WritingAssistStrength[] = ["weak", "mid", "strong"];
  const cur = loadWritingAssist();
  if (order.indexOf(next) > order.indexOf(cur)) {
    saveWritingAssist(next);
    return next;
  }
  return null;
}

/** 最近一次 Writing Turn 回传的能力探针画像（只读展示）。 */
export function saveCapabilityProfile(
  profile: CapabilityProfileSnapshot | null | undefined
): void {
  if (!profile || typeof profile !== "object") return;
  try {
    localStorage.setItem(
      CAP_KEY,
      JSON.stringify({ ...profile, at: new Date().toISOString() })
    );
  } catch {
    /* ignore quota */
  }
}

export function loadCapabilityProfile(): CapabilityProfileSnapshot | null {
  try {
    const raw = localStorage.getItem(CAP_KEY);
    if (!raw) return null;
    const parsed = JSON.parse(raw) as CapabilityProfileSnapshot;
    if (!parsed || typeof parsed !== "object") return null;
    return parsed;
  } catch {
    return null;
  }
}

const ADAPT_LOG_KEY = "vnss-strategy-adapt-log-v1";
const ADAPT_LOG_MAX = 40;

export type StrategyAdaptLogEntry = {
  projectId?: string;
  chapterId?: string | null;
  changed?: boolean;
  suggestedAssist?: string;
  reasons?: string[];
  attention?: string;
  memory?: string;
  reasoning?: string;
  outcome?: "accept" | "reject";
  at?: string;
};

/** 本机保留最近若干条 strategyAdapt（与后端 JSONL 互补，供 bandit）。 */
export function appendStrategyAdaptLog(entry: StrategyAdaptLogEntry): void {
  if (!entry || typeof entry !== "object") return;
  try {
    const raw = localStorage.getItem(ADAPT_LOG_KEY);
    const prev: unknown[] = raw ? (JSON.parse(raw) as unknown[]) : [];
    const list = Array.isArray(prev) ? prev : [];
    list.push({ ...entry, at: new Date().toISOString() });
    localStorage.setItem(
      ADAPT_LOG_KEY,
      JSON.stringify(list.slice(-ADAPT_LOG_MAX))
    );
  } catch {
    /* ignore */
  }
}

export function loadStrategyAdaptLog(): StrategyAdaptLogEntry[] {
  try {
    const raw = localStorage.getItem(ADAPT_LOG_KEY);
    if (!raw) return [];
    const parsed = JSON.parse(raw) as unknown;
    return Array.isArray(parsed) ? (parsed as StrategyAdaptLogEntry[]) : [];
  } catch {
    return [];
  }
}

const BANDIT_MIN = 8;

/** 本机 bandit：样本足够时建议 assist（不强制覆盖用户手动档）。 */
/** 记录采纳/拒绝，供本机 bandit。 */
export function logStrategyOutcome(
  projectId: string,
  outcome: "accept" | "reject",
  extra?: Partial<StrategyAdaptLogEntry>
): void {
  const last = loadStrategyAdaptLog()
    .filter((r) => !projectId || r.projectId === projectId)
    .slice(-1)[0];
  appendStrategyAdaptLog({
    projectId,
    chapterId: extra?.chapterId ?? last?.chapterId,
    suggestedAssist: extra?.suggestedAssist ?? last?.suggestedAssist ?? loadWritingAssist(),
    changed: extra?.changed ?? last?.changed,
    attention: extra?.attention ?? last?.attention,
    memory: extra?.memory ?? last?.memory,
    reasoning: extra?.reasoning ?? last?.reasoning,
    reasons: extra?.reasons ?? last?.reasons,
    outcome,
  });
}

export function suggestAssistFromLocalBandit(
  projectId?: string
): WritingAssistStrength | null {
  const rows = loadStrategyAdaptLog().filter(
    (r) =>
      (!projectId || r.projectId === projectId) &&
      (r.outcome === "accept" || r.outcome === "reject") &&
      (r.suggestedAssist === "strong" ||
        r.suggestedAssist === "mid" ||
        r.suggestedAssist === "weak")
  );
  if (rows.length < BANDIT_MIN) return null;
  const buckets: Record<WritingAssistStrength, number[]> = {
    weak: [],
    mid: [],
    strong: [],
  };
  for (const r of rows) {
    const a = r.suggestedAssist as WritingAssistStrength;
    buckets[a].push(r.outcome === "accept" ? 1 : 0);
  }
  let best: WritingAssistStrength | null = null;
  let bestMean = -1;
  for (const a of ["strong", "mid", "weak"] as WritingAssistStrength[]) {
    const xs = buckets[a];
    if (!xs.length) continue;
    const mean = xs.reduce((s, x) => s + x, 0) / xs.length;
    if (mean > bestMean) {
      bestMean = mean;
      best = a;
    }
  }
  return best;
}

export const WRITING_ASSIST_OPTIONS: {
  value: WritingAssistStrength;
  label: string;
  hint: string;
}[] = [
  {
    value: "strong",
    label: "强（默认）",
    hint: "全量 VN 约束：分支记忆、伏笔图、声线先验、试玩钩子与子代理",
  },
  {
    value: "mid",
    label: "中",
    hint: "保留分支/伏笔/可演；关闭声线先验、结局完备与子代理",
  },
  {
    value: "weak",
    label: "弱",
    hint: "安全阀：关掉 VN 重块，只留薄可演约束与策略裁过的账本",
  },
];
