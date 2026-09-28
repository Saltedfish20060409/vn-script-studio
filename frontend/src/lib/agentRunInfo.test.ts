import { beforeEach, describe, expect, it } from "vitest";
import {
  compactContextUsage,
  compactRunInfo,
  readRunInfoOpen,
  writeRunInfoOpen,
} from "./agentRunInfo";

/** node 环境没有 localStorage，按需装一个最小实现。 */
function stubStorage() {
  const map = new Map<string, string>();
  (globalThis as unknown as { localStorage: Storage }).localStorage = {
    getItem: (k: string) => (map.has(k) ? (map.get(k) as string) : null),
    setItem: (k: string, v: string) => void map.set(k, String(v)),
    removeItem: (k: string) => void map.delete(k),
    clear: () => map.clear(),
    key: (i: number) => Array.from(map.keys())[i] ?? null,
    get length() {
      return map.size;
    },
  } as Storage;
}

beforeEach(() => {
  stubStorage();
});

describe("compactContextUsage", () => {
  it("平时只留用量，把上限收起来", () => {
    expect(
      compactContextUsage({ text: "本次上下文 13,578 字（上限 48,000）" })
    ).toBe("语境 13,578 字");
  });

  it("有资料没装下时原样保留（告警不能被折叠掉）", () => {
    expect(
      compactContextUsage({
        text: "本次上下文 46,000 字（上限 48,000）",
        truncated: true,
      })
    ).toBe("本次上下文 46,000 字（上限 48,000） · 有资料没装下");
  });

  it("接近上限时也说上限", () => {
    expect(
      compactContextUsage({
        text: "本次上下文 40,000 字（上限 48,000）",
        nearLimit: true,
      })
    ).toBe("本次上下文 40,000 字（上限 48,000） · 接近上限");
  });

  it("没有上限、或格式不是预期时都不瞎猜", () => {
    expect(compactContextUsage({ text: "本次上下文 3,200 字" })).toBe("语境 3,200 字");
    expect(compactContextUsage({ text: "（不知道读了多少）" })).toBe("（不知道读了多少）");
    expect(compactContextUsage({ text: "" })).toBe("");
  });
});

describe("compactRunInfo", () => {
  it("压缩成一行：任务/结果/工艺档保留，参考清单只留项数", () => {
    const line = compactRunInfo({
      taskName: "讨论",
      resultBit: "仅讨论未改工程",
      craftShort: "工艺关",
      refCount: 11,
      contextText: "本次上下文 13,578 字（上限 48,000）",
      evidenceCount: 4,
    });
    expect(line).toBe("讨论 · 仅讨论未改工程 · 工艺关 · 参考 11 项 · 语境 13,578 字 · 依据 4 项");
    expect(line).not.toContain("作品信息");
    expect(line).not.toContain("48,000");
  });

  it("告警类短标签照样出现", () => {
    const line = compactRunInfo({
      taskName: "续写",
      gateShort: "写后闸⚠",
      excludedCount: 2,
    });
    expect(line).toContain("写后闸⚠");
    expect(line).toContain("不带 2 项");
  });

  it("没有 0 项这种噪音；全空时不渲染", () => {
    expect(compactRunInfo({ refCount: 0, evidenceCount: 0, excludedCount: 0 })).toBe("");
  });
});

describe("折叠偏好落盘", () => {
  it("默认收起", () => {
    expect(readRunInfoOpen()).toBe(false);
  });

  it("展开后记得住", () => {
    writeRunInfoOpen(true);
    expect(readRunInfoOpen()).toBe(true);
    writeRunInfoOpen(false);
    expect(readRunInfoOpen()).toBe(false);
  });

  it("没有 localStorage 也不炸（隐私模式）", () => {
    delete (globalThis as unknown as { localStorage?: Storage }).localStorage;
    expect(readRunInfoOpen()).toBe(false);
    expect(() => writeRunInfoOpen(true)).not.toThrow();
  });
});
