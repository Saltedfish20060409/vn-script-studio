import { describe, expect, it } from "vitest";
import {
  CHARS_PER_TOKEN,
  budgetCharsToTier,
  estimateContextCost,
  tierToBudgetChars,
} from "./contextBudgetTier";

describe("contextBudgetTier", () => {
  it("档位映射", () => {
    expect(tierToBudgetChars("standard")).toBe(128_000);
    expect(tierToBudgetChars("max")).toBe(0);
    expect(budgetCharsToTier(128_000)).toBe("standard");
    expect(budgetCharsToTier(0)).toBe("max");
  });

  it("成本估算用 1.2 字/token", () => {
    expect(CHARS_PER_TOKEN).toBe(1.2);
    const e = estimateContextCost(1200);
    expect(e.estInputTokens).toBe(1000);
    expect(e.label).toMatch(/估算/);
  });
});
