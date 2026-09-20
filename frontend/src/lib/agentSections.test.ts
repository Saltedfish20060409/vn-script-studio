import { describe, expect, it } from "vitest";
import {
  AGENT_SECTIONS,
  excludedSummary,
  loadExcludedSections,
  saveExcludedSections,
  toggleSection,
} from "./agentSections";

function fakeStorage(initial: Record<string, string> = {}) {
  const map = new Map(Object.entries(initial));
  return {
    getItem: (k: string) => map.get(k) ?? null,
    setItem: (k: string, v: string) => void map.set(k, v),
    dump: () => Object.fromEntries(map),
  };
}

describe("交给 AI 的资料开关", () => {
  it("key 与后端 EXCLUDABLE_SECTIONS 对齐（多一个少一个只会让那个勾失效，不会报错）", () => {
    const keys = AGENT_SECTIONS.map((s) => s.key);
    expect(keys).toEqual([
      "bible",
      "lore",
      "longMemory",
      "craft",
      "referenceDocs",
      "chatMemory",
      "index",
      "characters",
      "relations",
      "locations",
      "variables",
      "sprites",
      "otherChapters",
      "style",
    ]);
    for (const s of AGENT_SECTIONS) expect(s.label.length).toBeGreaterThan(1);
  });

  it("切换只影响这一项", () => {
    const next = toggleSection([], "bible");
    expect(next).toEqual(["bible"]);
    expect(toggleSection(next, "bible")).toEqual([]);
  });

  it("存本机并读回来", () => {
    const store = fakeStorage();
    saveExcludedSections(["bible", "lore"], store);
    expect(loadExcludedSections(store)).toEqual(["bible", "lore"]);
  });

  it("坏数据 / 非数组 → 空（不炸）", () => {
    expect(loadExcludedSections(fakeStorage({ "vnss-agent-exclude-v1": "{不是 JSON" }))).toEqual([]);
    expect(
      loadExcludedSections(fakeStorage({ "vnss-agent-exclude-v1": JSON.stringify({ a: 1 }) }))
    ).toEqual([]);
    expect(
      loadExcludedSections(
        fakeStorage({ "vnss-agent-exclude-v1": JSON.stringify(["bible", 42, null]) })
      )
    ).toEqual(["bible"]);
  });

  it("storage 不可用时不抛", () => {
    expect(loadExcludedSections(null)).toEqual([]);
    expect(() => saveExcludedSections(["x"], null)).not.toThrow();
  });

  it("摘要文案", () => {
    expect(excludedSummary([])).toBe("");
    expect(excludedSummary(["a", "b"])).toContain("2");
  });
});
