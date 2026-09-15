import { describe, expect, it } from "vitest";
import type { LocalizationEntry } from "../api/projects";
import {
  groupByChapter,
  hasUntranslated,
  nextUntranslated,
  progressFor,
} from "./localizationView";

function entry(over: Partial<LocalizationEntry>): LocalizationEntry {
  return {
    key: "k",
    chapterId: "ch1",
    kind: "dialogue",
    source: "原文",
    sourceHash: "h",
    targets: {},
    status: {},
    ...over,
  };
}

const ENTRIES: LocalizationEntry[] = [
  entry({ key: "ch1#0", chapterId: "ch1", targets: { en: "Hello" } }),
  entry({ key: "ch1#1", chapterId: "ch1", targets: {} }),
  entry({ key: "ch2#0", chapterId: "ch2", targets: { en: "Bye" } }),
];

describe("progressFor", () => {
  it("统计已填数量与百分比（空白不算已翻）", () => {
    expect(progressFor(ENTRIES, "en")).toEqual({ done: 2, total: 3, pct: 67 });
    expect(progressFor([entry({ targets: { en: "   " } })], "en")).toEqual({
      done: 0,
      total: 1,
      pct: 0,
    });
    expect(progressFor([], "en")).toEqual({ done: 0, total: 0, pct: 0 });
  });
});

describe("groupByChapter", () => {
  it("按剧本章节顺序分组，并用章节标题而不是内部 id", () => {
    const groups = groupByChapter(ENTRIES, [
      { id: "ch2", title: "第二章" },
      { id: "ch1", title: "第一章" },
    ], "en");
    expect(groups.map((g) => g.title)).toEqual(["第二章", "第一章"]);
    expect(groups[0].total).toBe(1);
    expect(groups[1].translated).toBe(1);
  });

  it("章节没有标题时退回 id，不显示空标题", () => {
    const groups = groupByChapter([entry({ chapterId: "chX" })], [{ id: "chX" }], "en");
    expect(groups[0].title).toBe("chX");
  });

  it("条目指向已不存在的章节时放到最后，不丢条目", () => {
    const groups = groupByChapter(
      [entry({ key: "ghost", chapterId: "gone" })],
      [{ id: "ch1", title: "第一章" }],
      "en"
    );
    expect(groups.map((g) => g.chapterId)).toEqual(["gone"]);
    expect(groups[0].total).toBe(1);
  });
});

describe("nextUntranslated / hasUntranslated", () => {
  it("给出第一条未翻的条目", () => {
    expect(nextUntranslated(ENTRIES, "en")?.key).toBe("ch1#1");
    expect(nextUntranslated(ENTRIES, "ja")?.key).toBe("ch1#0");
  });

  it("全部翻完返回 null", () => {
    const all = ENTRIES.map((e) => ({ ...e, targets: { en: "x" } }));
    expect(nextUntranslated(all, "en")).toBeNull();
    expect(hasUntranslated(all, "en")).toBe(false);
  });
});
