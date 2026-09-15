import { describe, expect, it } from "vitest";
import { isBenignNoise, shouldReloadForChunkError } from "./errorReporter";

describe("isBenignNoise", () => {
  it("过滤浏览器层面的 ResizeObserver 噪音（线上占比最大的一种）", () => {
    expect(
      isBenignNoise("ResizeObserver loop completed with undelivered notifications.")
    ).toBe(true);
    expect(isBenignNoise("ResizeObserver loop limit exceeded")).toBe(true);
  });

  it("真问题不能被吞掉", () => {
    expect(isBenignNoise("Failed to fetch dynamically imported module: x.js")).toBe(false);
    expect(isBenignNoise("Cannot read properties of undefined (reading 'chapters')")).toBe(
      false
    );
    expect(isBenignNoise("Script error.")).toBe(false);
    expect(isBenignNoise("")).toBe(false);
  });
});

describe("shouldReloadForChunkError", () => {
  const COOLDOWN = 60_000;

  it("从没刷过 → 允许刷", () => {
    expect(shouldReloadForChunkError(0, 1_000_000, COOLDOWN)).toBe(true);
  });

  it("冷却窗口内已经刷过 → 不再刷（防无限刷新）", () => {
    const now = 1_000_000;
    expect(shouldReloadForChunkError(now - 1_000, now, COOLDOWN)).toBe(false);
    expect(shouldReloadForChunkError(now - COOLDOWN + 1, now, COOLDOWN)).toBe(false);
  });

  it("超过冷却窗口 → 允许再刷一次（可能又发版了）", () => {
    const now = 1_000_000;
    expect(shouldReloadForChunkError(now - COOLDOWN, now, COOLDOWN)).toBe(true);
    expect(shouldReloadForChunkError(now - COOLDOWN * 10, now, COOLDOWN)).toBe(true);
  });

  it("脏数据（NaN / 负数）按'没刷过'处理，不要卡死用户", () => {
    expect(shouldReloadForChunkError(Number.NaN, 1_000_000, COOLDOWN)).toBe(true);
    expect(shouldReloadForChunkError(-5, 1_000_000, COOLDOWN)).toBe(true);
  });
});
