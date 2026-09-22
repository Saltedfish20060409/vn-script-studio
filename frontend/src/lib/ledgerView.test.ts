import { describe, expect, it } from "vitest";
import {
  buildChapterRows,
  foreshadowRows,
  foreshadowSummary,
  groupCharacterStates,
  isChapterPending,
  isForeshadowOpen,
  summarizeLedger,
} from "./ledgerView";
import type { VnProject } from "../types/vn";

function project(over: Partial<VnProject> = {}): VnProject {
  return {
    id: "p1",
    title: "测试",
    characters: [],
    chapters: [
      { id: "ch1", title: "第一章", blocks: [] },
      { id: "ch2", title: "第二章", blocks: [] },
    ],
    chapterIndex: [
      {
        chapterId: "ch1",
        title: "第一章",
        hash: "h1",
        synopsis: "开场",
        speakers: ["绫"],
        openHook: "雨夜",
        closeHook: "她回头",
      },
    ],
    writingLedger: {
      chapterFacts: [
        { chapterId: "ch1", title: "第一章", facts: ["开场"], keyQuotes: ["绫: 你来了"] },
      ],
      characterStates: [
        { id: "s1", chapterId: "ch1", chapterTitle: "第一章", characterName: "绫", emotion: "平静" },
        { id: "s2", chapterId: "ch2", chapterTitle: "第二章", characterName: "绫", emotion: "激动" },
      ],
      foreshadows: [
        { id: "f1", hook: "她回头", plantedChapter: "ch1", status: "open" },
        { id: "f2", hook: "旧照片", plantedChapter: "ch2", status: "paid" },
      ],
      events: [{ id: "e1", chapterId: "ch1", summary: "第一章入库" }],
      updatedAt: "2026-09-14T00:00:00Z",
    },
    updatedAt: "2026-09-14T00:00:00Z",
    ...over,
  } as VnProject;
}

describe("buildChapterRows", () => {
  it("chapterIndex 为主序，正文兜底补齐未索引章节", () => {
    const rows = buildChapterRows(project());
    expect(rows.map((r) => r.entry.chapterId)).toEqual(["ch1", "ch2"]);
    // ch1 有账本事实 → 已入库；ch2 只有正文兜底 → 待入库
    expect(rows[0].fact?.chapterId).toBe("ch1");
    expect(isChapterPending(rows[0])).toBe(false);
    expect(rows[1].fact).toBeUndefined();
    expect(isChapterPending(rows[1])).toBe(true);
  });

  it("统计每章的角色状态条数与未回收钩子数", () => {
    const rows = buildChapterRows(project());
    expect(rows[0].states).toHaveLength(1);
    expect(rows[1].states).toHaveLength(1);
    expect(rows[0].openForeshadows).toBe(1); // f1 open，植于 ch1
    expect(rows[1].openForeshadows).toBe(0); // f2 已回收
  });

  it("没有 chapterIndex 时也不会丢章节", () => {
    const rows = buildChapterRows(project({ chapterIndex: [] }));
    expect(rows.map((r) => r.entry.title)).toEqual(["第一章", "第二章"]);
  });

  it("账本为空时全是待入库，不崩", () => {
    const rows = buildChapterRows(project({ writingLedger: {} }));
    expect(rows).toHaveLength(2);
    expect(rows.every(isChapterPending)).toBe(true);
  });
});

describe("groupCharacterStates", () => {
  it("按角色聚合并把记录多的排前面", () => {
    const groups = groupCharacterStates(project());
    expect(groups).toHaveLength(1);
    expect(groups[0][0]).toBe("绫");
    // 顺序保持"时间顺序"：最后一条是最近状态
    expect(groups[0][1].map((s) => s.emotion)).toEqual(["平静", "激动"]);
  });

  it("没有名字时用 id 或占位名兜底", () => {
    const groups = groupCharacterStates(
      project({
        writingLedger: { characterStates: [{ characterId: "c9", emotion: "疑惑" }] },
      })
    );
    expect(groups[0][0]).toBe("c9");
  });
});

describe("summarizeLedger", () => {
  it("给出概览数字（含未回收/已回收伏笔）", () => {
    const s = summarizeLedger(project());
    expect(s).toMatchObject({
      chapters: 2,
      digested: 1,
      states: 2,
      openForeshadows: 1,
      paidForeshadows: 1,
      updatedAt: "2026-09-14T00:00:00Z",
    });
  });
});

describe("isForeshadowOpen", () => {
  it("只有 paid 才算已回收", () => {
    expect(isForeshadowOpen({ status: "open" })).toBe(true);
    expect(isForeshadowOpen({})).toBe(true);
    expect(isForeshadowOpen({ status: "paid" })).toBe(false);
  });
});

// ---------------------------------------------------------------------------
// 伏笔闭环：埋了多久 / 回收于第几章
// ---------------------------------------------------------------------------

function fiveChapters(ledger: Partial<VnProject["writingLedger"]> = {}): VnProject {
  return {
    id: "p5",
    title: "五章项目",
    updatedAt: "2026-09-22T00:00:00Z",
    characters: [],
    chapters: [1, 2, 3, 4, 5].map((i) => ({ id: `ch${i}`, title: `第${i}章`, blocks: [] })),
    writingLedger: ledger,
  } as unknown as VnProject;
}

describe("伏笔闭环（埋了多久 / 回收于第几章）", () => {
  it("未回收：算出从埋点到现在隔了几章", () => {
    const p = fiveChapters({
      foreshadows: [{ id: "f1", hook: "红伞", plantedChapter: "ch1", status: "open" }],
    });
    const rows = foreshadowRows(p);
    expect(rows).toHaveLength(1);
    expect(rows[0].ageChapters).toBe(4); // ch1 → ch5
    expect(rows[0].plantedLabel).toBe("第1章");
    expect(rows[0].paidLabel).toBe("");
  });

  it("已回收：算出回收于哪一章、以及埋了几章", () => {
    const p = fiveChapters({
      foreshadows: [
        { id: "f1", hook: "红伞", plantedChapter: "ch1", paidInChapter: "ch4", status: "paid" },
      ],
    });
    const rows = foreshadowRows(p);
    expect(rows[0].paidLabel).toBe("第4章");
    expect(rows[0].ageChapters).toBe(3);
  });

  it("缺章节信息时不崩，只是算不出年龄", () => {
    const p = fiveChapters({
      foreshadows: [{ id: "f1", hook: "x", plantedChapter: "gone", status: "open" }],
    });
    p.chapters = [];
    expect(foreshadowRows(p)[0].ageChapters).toBeNull();
  });

  it("排序：未回收在前，埋得久的更靠前", () => {
    const p = fiveChapters({
      foreshadows: [
        { id: "paid", hook: "已收", plantedChapter: "ch1", paidInChapter: "ch2", status: "paid" },
        { id: "fresh", hook: "新埋", plantedChapter: "ch5", status: "open" },
        { id: "old", hook: "老埋", plantedChapter: "ch1", status: "open" },
      ],
    });
    expect(foreshadowRows(p).map((r) => r.id)).toEqual(["old", "fresh", "paid"]);
  });

  it("一句话概括会点出「埋了 5 章以上」的条数", () => {
    const p = fiveChapters({
      foreshadows: [
        { id: "a", hook: "老", plantedChapter: "ch1", status: "open" },
        { id: "b", hook: "新", plantedChapter: "ch5", status: "open" },
        { id: "c", hook: "收", plantedChapter: "ch2", paidInChapter: "ch3", status: "paid" },
      ],
    });
    // 再来一章，让 ch1 那条真的隔了 5 章（ch1 → ch6）
    p.chapters = [
      ...p.chapters,
      { id: "ch6", title: "第6章", blocks: [] },
    ] as VnProject["chapters"];

    const s = foreshadowSummary(foreshadowRows(p));
    expect(s).toContain("未回收 2");
    expect(s).toContain("1 条埋了 5 章以上");
  });

  it("全部回收时不喊「未回收」", () => {
    const p = fiveChapters({
      foreshadows: [
        { id: "a", hook: "x", plantedChapter: "ch1", paidInChapter: "ch2", status: "paid" },
      ],
    });
    expect(foreshadowSummary(foreshadowRows(p))).toContain("全部已回收");
  });
});
