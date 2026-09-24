/**
 * 「这次它读了多少」的显示口径。
 *
 * 钉住两件事：
 * 1. **缺的字段不许编**：旧后端没有 budgetChars/truncated 时只显示已用量，
 *    不能显示"上限 0"或把"未知"当成"没被裁"；
 * 2. **被裁过要说人话 + 给动作**：作者看到的是"可以让它用工具取"，而不是一句技术名词。
 */
import { describe, expect, it } from "vitest";

import type { AgentContextMeta } from "../types/vn";
import { contextUsage } from "./contextUsage";

function meta(over: Partial<AgentContextMeta> = {}): AgentContextMeta {
  return { task: "continue", charsUsed: 12000, included: [], ...over };
}

describe("contextUsage", () => {
  it("有预算时同时给出用量与上限", () => {
    const out = contextUsage(meta({ charsUsed: 12480, budgetChars: 48000 }));
    expect(out.text).toBe("本次上下文 12,480 字（上限 48,000）");
    expect(out.truncated).toBe(false);
    expect(out.nearLimit).toBe(false);
    expect(out.hint).toBe("");
  });

  it("没有 budgetChars 时只说用量，不编上限", () => {
    const out = contextUsage(meta({ charsUsed: 3200 }));
    expect(out.text).toBe("本次上下文 3,200 字");
    expect(out.text).not.toContain("上限");
    expect(out.nearLimit).toBe(false);
  });

  it("完全没有用量数据时返回空串（界面上不显示这一行）", () => {
    expect(contextUsage(undefined).text).toBe("");
    expect(contextUsage({ task: "chat", charsUsed: -1, included: [] }).text).toBe("");
  });

  it("接近上限时给出提示，但不谎称被裁", () => {
    const out = contextUsage(meta({ charsUsed: 45000, budgetChars: 48000 }));
    expect(out.nearLimit).toBe(true);
    expect(out.truncated).toBe(false);
    expect(out.hint).toContain("接近上限");
    expect(out.hint).not.toContain("get_chapter");
  });

  it("被裁过时给出可执行的动作（用工具取回），并优先于「接近上限」的提示", () => {
    const out = contextUsage(meta({ charsUsed: 47000, budgetChars: 48000, truncated: true }));
    expect(out.truncated).toBe(true);
    expect(out.hint).toContain("get_chapter");
    expect(out.hint).toContain("没装下");
    expect(out.hint).not.toContain("接近上限");
  });

  it("预算为 0 或缺省视为未知", () => {
    expect(contextUsage(meta({ budgetChars: 0 })).text).toBe("本次上下文 12,000 字");
    expect(contextUsage(meta({ budgetChars: undefined })).nearLimit).toBe(false);
  });
});
