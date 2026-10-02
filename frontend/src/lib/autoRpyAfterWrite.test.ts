import { describe, expect, it } from "vitest";
import {
  isAutoRpyAfterProseWriteEnabled,
  setAutoRpyAfterProseWriteEnabled,
} from "./autoRpyFlag";
import {
  shouldAutoGenerateRpyAfterProseWrite,
  autoRpyNotNeededMessage,
} from "./autoRpyAfterWrite";
import { proseFingerprint, rpyIsStale } from "./scriptProse";

function memStorage(init: Record<string, string> = {}) {
  const map = new Map(Object.entries(init));
  return {
    getItem: (k: string) => (map.has(k) ? map.get(k)! : null),
    setItem: (k: string, v: string) => {
      map.set(k, v);
    },
  };
}

describe("autoRpyFlag", () => {
  it("默认开", () => {
    expect(isAutoRpyAfterProseWriteEnabled(memStorage())).toBe(true);
  });

  it("可关掉", () => {
    const s = memStorage();
    setAutoRpyAfterProseWriteEnabled(false, s);
    expect(isAutoRpyAfterProseWriteEnabled(s)).toBe(false);
  });
});

describe("shouldAutoGenerateRpyAfterProseWrite", () => {
  it("空 prose → false", () => {
    expect(
      shouldAutoGenerateRpyAfterProseWrite({
        id: "c",
        title: "t",
        prose: "",
        blocks: [{ type: "narration", text: "旧" }],
        rpyFromProseHash: "x",
      })
    ).toBe(false);
  });

  it("纯 LN：无 hash → false（永不自动）", () => {
    expect(
      shouldAutoGenerateRpyAfterProseWrite({
        id: "c",
        title: "t",
        prose: "雨下了。",
        blocks: [{ type: "label", id: "start", name: "start" }],
      })
    ).toBe(false);
    expect(autoRpyNotNeededMessage()).toMatch(/根据剧本生成/);
  });

  it("有脚本正文但无 hash → false（须手动建立基线）", () => {
    expect(
      shouldAutoGenerateRpyAfterProseWrite({
        id: "c",
        title: "t",
        prose: "雨下了。",
        blocks: [{ type: "narration", text: "旧旁白" }],
      })
    ).toBe(false);
  });

  it("曾手动生成：hash 过期 → true；指纹一致 → false", () => {
    const prose = "新正文变了。";
    expect(
      shouldAutoGenerateRpyAfterProseWrite({
        id: "c",
        title: "t",
        prose,
        blocks: [{ type: "narration", text: "旧旁白" }],
        rpyFromProseHash: "stale-hash",
      })
    ).toBe(true);
    expect(
      shouldAutoGenerateRpyAfterProseWrite({
        id: "c",
        title: "t",
        prose,
        blocks: [{ type: "narration", text: "旧旁白" }],
        rpyFromProseHash: proseFingerprint(prose),
      })
    ).toBe(false);
  });
});

describe("脚本待更新标记（rpyIsStale）", () => {
  it("失败后 hash 仍 stale → 切章/刷新后仍可识别", () => {
    const prose = "正文档。";
    const ch = {
      id: "c",
      title: "t",
      prose,
      blocks: [{ type: "narration" as const, text: "旧" }],
      rpyFromProseHash: "failed-old-hash",
    };
    expect(rpyIsStale(ch)).toBe(true);
    // 成功生成后指纹对齐 → 标记消失
    ch.rpyFromProseHash = proseFingerprint(prose);
    expect(rpyIsStale(ch)).toBe(false);
  });
});

describe("自动 RPY 与清空闸正交", () => {
  it("shouldAutoGenerate 不调用 flush / 不产生 needsConfirm 语义", () => {
    const ch = {
      id: "c",
      title: "t",
      prose: "正文档。",
      blocks: [{ type: "narration" as const, text: "旁白" }],
      rpyFromProseHash: "old",
    };
    expect(shouldAutoGenerateRpyAfterProseWrite(ch)).toBe(true);
    expect(ch.prose).toBe("正文档。");
  });
});
