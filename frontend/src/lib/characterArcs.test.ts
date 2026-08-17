import { describe, expect, it } from "vitest";
import type { VnProject } from "../types/vn";
import { computeCharacterArcs } from "./characterArcs";

const dialog = (characterId: string, text: string) => ({
  type: "dialogue" as const,
  characterId,
  text,
});

function makeProject(): VnProject {
  return {
    id: "p1",
    title: "测试",
    updatedAt: "2025-01-01T00:00:00.000Z",
    characters: [
      { id: "a", defineName: "alice", displayName: "爱丽丝", color: "#f00" },
      { id: "b", defineName: "bob", displayName: "鲍勃", color: "#0f0" },
      { id: "c", defineName: "carl", displayName: "卡尔" },
    ],
    chapters: [
      {
        id: "ch1",
        title: "第一章",
        blocks: [dialog("a", "你好"), dialog("b", "嗨"), dialog("a", "再见")],
      },
      {
        id: "ch2",
        title: "第二章",
        blocks: [
          dialog("a", "又见面了"),
          { type: "menu", id: "m", choices: [{ text: "x", blocks: [dialog("b", "菜单里的话")] }] },
        ],
      },
      {
        id: "ch3",
        title: "第三章",
        blocks: [
          { type: "narration", text: "爱丽丝独自离开" },
          dialog("c", "卡尔登场"),
        ],
      },
    ],
    timeline: [
      {
        id: "t1",
        title: "爱丽丝的告别",
        when: "第三章",
        summary: "爱丽丝离开城市",
        order: 1,
        chapterRef: "ch3",
      },
      {
        id: "t2",
        title: "无关事件",
        when: "第一章",
        summary: "天气不错",
        order: 0,
      },
    ],
  };
}

describe("computeCharacterArcs", () => {
  it("counts dialogue lines per chapter and totals", () => {
    const r = computeCharacterArcs(makeProject());
    const alice = r.characters.find((c) => c.id === "a")!;
    const bob = r.characters.find((c) => c.id === "b")!;
    const carl = r.characters.find((c) => c.id === "c")!;
    expect(alice.totalLines).toBe(3);
    expect(bob.totalLines).toBe(2); // 1 direct + 1 in menu inline blocks
    expect(carl.totalLines).toBe(1);
    expect(alice.chapterSeries.map((p) => p.lines)).toEqual([2, 1, 0]);
    expect(r.maxLines).toBe(3);
  });

  it("sorts characters by total lines descending", () => {
    const r = computeCharacterArcs(makeProject());
    expect(r.characters[0].id).toBe("a");
    expect(r.characters[2].id).toBe("c");
  });

  it("tracks first/last seen and gaps", () => {
    const r = computeCharacterArcs(makeProject());
    const alice = r.characters.find((c) => c.id === "a")!;
    const carl = r.characters.find((c) => c.id === "c")!;
    expect(alice.firstSeenIndex).toBe(0);
    expect(alice.lastSeenIndex).toBe(1);
    expect(alice.gapChapters).toBe(1); // ch3 silent
    expect(carl.firstSeenIndex).toBe(2);
    expect(carl.lastSeenIndex).toBe(2);
    expect(carl.gapChapters).toBe(0);
  });

  it("links timeline events that mention the character", () => {
    const r = computeCharacterArcs(makeProject());
    const alice = r.characters.find((c) => c.id === "a")!;
    expect(alice.timelineEvents).toHaveLength(1);
    expect(alice.timelineEvents[0].title).toBe("爱丽丝的告别");
    const bob = r.characters.find((c) => c.id === "b")!;
    expect(bob.timelineEvents).toHaveLength(0);
  });

  it("handles a character that never speaks", () => {
    const p = makeProject();
    p.characters.push({ id: "ghost", defineName: "ghost", displayName: "幽灵" });
    const r = computeCharacterArcs(p);
    const ghost = r.characters.find((c) => c.id === "ghost")!;
    expect(ghost.totalLines).toBe(0);
    expect(ghost.firstSeenIndex).toBe(-1);
    expect(ghost.lastSeenIndex).toBe(-1);
    expect(ghost.activeChapters).toBe(0);
  });

  it("empty project returns empty arcs", () => {
    const p: VnProject = {
      id: "e",
      title: "空",
      updatedAt: "2025-01-01T00:00:00.000Z",
      characters: [],
      chapters: [],
    };
    const r = computeCharacterArcs(p);
    expect(r.characters).toEqual([]);
    expect(r.maxLines).toBe(1);
  });
});
