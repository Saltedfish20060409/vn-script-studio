import { describe, expect, it } from "vitest";
import { flushChapterSurface } from "./chapterSurfaces";
import type { VnProject } from "../types/vn";

function project(chapter: Partial<VnProject["chapters"][number]>): VnProject {
  return {
    id: "p1",
    title: "t",
    logline: "",
    genre: "",
    chapters: [
      {
        id: "ch1",
        title: "第一章",
        blocks: [],
        prose: "",
        ...chapter,
      },
    ],
    characters: [],
  } as unknown as VnProject;
}

const rpyText = [{ type: "narration" as const, text: "旧脚本里的旁白。" }];

describe("一章的文本存在哪一面（prose / blocks）", () => {
  it("正文档里清空 → 脚本档那一面也清（否则旧稿会从回落里复活）", () => {
    // 线上事故的形状：正文其实存在 blocks 里，作者在正文档里把它删了。
    // 旧实现只写 prose（本来就空）→ 本地 JSON 没变化 → 连保存都不发 →
    // 服务端 chapter_plain 又从 blocks 回落 → 模型接着"已删除"的原文写。
    const before = project({ prose: "", blocks: rpyText });
    const { project: after, clearedOther } = flushChapterSurface(before, "ch1", "", "prose");

    const ch = after.chapters[0];
    expect(ch.prose).toBe("");
    expect(ch.blocks).toEqual([]);
    expect(ch.rpyFromProseHash).toBeUndefined();
    expect(clearedOther).toBe(true);
    // 真变了才可能被保存：JSON 必须与清理前不同
    expect(JSON.stringify(ch)).not.toBe(JSON.stringify(before.chapters[0]));
  });

  it("清空正文档时，派生标记也要清掉（不然 stale 判断还认它）", () => {
    const before = project({ prose: "正文。", blocks: rpyText, rpyFromProseHash: "abc" });
    const { project: after } = flushChapterSurface(before, "ch1", "   \n", "prose");
    expect(after.chapters[0].prose).toBe("");
    expect(after.chapters[0].blocks).toEqual([]);
    expect(after.chapters[0].rpyFromProseHash).toBeUndefined();
  });

  it("本来就空的章节：清空不制造变化（免得自动保存发一次空 PUT）", () => {
    const before = project({ prose: "", blocks: [{ type: "label", id: "start", name: "start" }] });
    const { project: after, clearedOther } = flushChapterSurface(before, "ch1", "", "prose");
    expect(after.chapters[0]).toBe(before.chapters[0]);
    expect(clearedOther).toBe(false);
  });

  it("脚本档里清空 → 正文档那一面也清", () => {
    const before = project({ prose: "正文档里的正文。", blocks: [] });
    const { project: after, clearedOther } = flushChapterSurface(before, "ch1", "", "rpy");
    const ch = after.chapters[0];
    expect(ch.prose).toBe("");
    // 清空后的 blocks 回到"新建章节"形态：只剩 label start，没有文本
    expect(ch.blocks.every((b) => b.type !== "narration" && b.type !== "dialogue")).toBe(true);
    expect(clearedOther).toBe(true);
  });

  it("非空编辑只动当前档：两档并行维护的用法不受影响", () => {
    const before = project({ prose: "旧正文。", blocks: rpyText });
    const { project: after, clearedOther } = flushChapterSurface(before, "ch1", "新正文。", "prose");
    expect(after.chapters[0].prose).toBe("新正文。");
    expect(after.chapters[0].blocks).toEqual(rpyText);
    expect(clearedOther).toBe(false);

    const rpy = flushChapterSurface(before, "ch1", "旁白：「改过的脚本。」", "rpy");
    expect(rpy.project.chapters[0].prose).toBe("旧正文。");
    expect(rpy.project.chapters[0].blocks.some((b) => b.type === "raw" || b.type === "narration")).toBe(
      true
    );
  });

  it("只动被编辑的那一章", () => {
    const before = project({ prose: "甲。" });
    before.chapters.push({
      id: "ch2",
      title: "第二章",
      blocks: [{ type: "narration", text: "乙。" }],
      prose: "",
    });
    const { project: after } = flushChapterSurface(before, "ch2", "", "prose");
    expect(after.chapters[0].prose).toBe("甲。");
    expect(after.chapters[1].blocks).toEqual([]);
  });
});
