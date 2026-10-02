/**
 * P8：上下文档位（字符口径，与 ADR 0001 §8 一致）。
 * 后端夹紧用 _CHARS_PER_TOKEN=1.2（字/ token 粗算：token ≈ chars/1.2）。
 */

export type ContextBudgetTier = "standard" | "enhanced" | "max";

export const TIER_SYNC_CHARS: Record<ContextBudgetTier, number> = {
  standard: 128_000,
  enhanced: 192_000,
  max: 0, // 0 = 产品不设硬顶，跟服务端/模型窗口
};

export const TIER_STREAM_CHARS: Record<ContextBudgetTier, number> = {
  standard: 256_000,
  enhanced: 512_000,
  max: 0,
};

/** 与 backend agent_context._CHARS_PER_TOKEN 对齐 */
export const CHARS_PER_TOKEN = 1.2;

const TIER_KEY = "vnss-context-budget-tier-v1";

export function loadContextBudgetTier(
  storage: Pick<Storage, "getItem"> | null = defaultStorage()
): ContextBudgetTier {
  try {
    const v = storage?.getItem(TIER_KEY);
    if (v === "enhanced" || v === "max" || v === "standard") return v;
  } catch {
    /* ignore */
  }
  return "standard";
}

export function saveContextBudgetTier(
  tier: ContextBudgetTier,
  storage: Pick<Storage, "setItem"> | null = defaultStorage()
): void {
  try {
    storage?.setItem(TIER_KEY, tier);
  } catch {
    /* ignore */
  }
}

function defaultStorage(): Storage | null {
  try {
    return typeof globalThis !== "undefined"
      ? (globalThis as { localStorage?: Storage }).localStorage ?? null
      : null;
  } catch {
    return null;
  }
}

/** 档位 → 建议写入 settings 的 context_budget_chars（max→0 跟随服务端）。 */
export function tierToBudgetChars(tier: ContextBudgetTier): number {
  return TIER_SYNC_CHARS[tier] || 0;
}

export function budgetCharsToTier(chars: number): ContextBudgetTier {
  if (!chars || chars <= 0) return "max";
  if (chars <= TIER_SYNC_CHARS.standard) return "standard";
  if (chars <= TIER_SYNC_CHARS.enhanced) return "enhanced";
  return "max";
}

export type CostEstimate = {
  estInputTokens: number;
  /** 粗算 USD；无标价时仍给 token 数 */
  estUsd: number;
  label: string;
};

/** 粗算：chars / 1.2 → tokens；默认 $0.14 / 1M input（可调）。 */
export function estimateContextCost(
  charsUsed: number,
  usdPerMillionInput = 0.14
): CostEstimate {
  const estInputTokens = Math.max(0, Math.round(charsUsed / CHARS_PER_TOKEN));
  const estUsd = (estInputTokens / 1_000_000) * usdPerMillionInput;
  const label =
    `估算约 ${estInputTokens.toLocaleString("en-US")} input tokens` +
    `（≈$${estUsd.toFixed(4)}，粗算）`;
  return { estInputTokens, estUsd, label };
}
