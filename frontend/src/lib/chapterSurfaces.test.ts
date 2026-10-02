import { describe, expect, it } from "vitest";
import {
  clearBothSurfacesConfirmBody,
  flushChapterSurface,
  inspectClearImpact,
} from "./chapterSurfaces";
import { blocksToProse } from "./scriptProse";
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
  it("P4.5：空 prose + 空编辑器 + 有 blocks → no-op（勿清脚本档）", () => {
    const before = project({ prose: "", blocks: rpyText });
    const { project: after, clearedOther } = flushChapterSurface(before, "ch1", "", "prose");
    expect(after.chapters[0]).toBe(before.chapters[0]);
    expect(clearedOther).toBe(false);
  });

  it("P4.5：空 prose + 编辑器 === scriptPreview → 不落盘", () => {
    const before = project({ prose: "", blocks: rpyText });
    const preview = blocksToProse(rpyText, []);
    const { project: after } = flushChapterSurface(before, "ch1", preview, "prose");
    expect(after.chapters[0].prose).toBe("");
    expect(after.chapters[0].blocks).toEqual(rpyText);
  });

  it("P4.5：空 prose + 自然语言 → 只写 prose，blocks 保留", () => {
    const before = project({ prose: "", blocks: rpyText });
    const { project: after } = flushChapterSurface(before, "ch1", "雨下了。", "prose");
    expect(after.chapters[0].prose).toBe("雨下了。");
    expect(after.chapters[0].blocks).toEqual(rpyText);
  });

  it("作者删光已有正文档 → 脚本档那一面也清（2026-10-01 事故规则）", () => {
    const before = project({ prose: "正文。", blocks: rpyText, rpyFromProseHash: "abc" });
    const { project: after, clearedOther } = flushChapterSurface(before, "ch1", "   \n", "prose");
    expect(after.chapters[0].prose).toBe("");
    expect(after.chapters[0].blocks).toEqual([]);
    expect(after.chapters[0].rpyFromProseHash).toBeUndefined();
    expect(clearedOther).toBe(true);
  });

  it("本来就空的章节：清空不制造变化", () => {
    const before = project({
      prose: "",
      blocks: [{ type: "label", id: "start", name: "start" }],
    });
    const { project: after, clearedOther } = flushChapterSurface(before, "ch1", "", "prose");
    expect(after.chapters[0]).toBe(before.chapters[0]);
    expect(clearedOther).toBe(false);
  });

  it("脚本档里清空 → 正文档那一面也清", () => {
    const before = project({ prose: "正文档里的正文。", blocks: [] });
    const { project: after, clearedOther } = flushChapterSurface(before, "ch1", "", "rpy");
    const ch = after.chapters[0];
    expect(ch.prose).toBe("");
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
    expect(
      rpy.project.chapters[0].blocks.some((b) => b.type === "raw" || b.type === "narration")
    ).toBe(true);
  });

  it("flag 关：空 prose 可把 preview 落盘（紧急回滚）", () => {
    const before = project({ prose: "", blocks: rpyText });
    const preview = blocksToProse(rpyText, []);
    const { project: after } = flushChapterSurface(before, "ch1", preview, "prose", {
      enforceProseEngineSyntaxReject: false,
    });
    expect(after.chapters[0].prose).toBe(preview);
  });

  it("只动被编辑的那一章（删光已有 prose 才清该章 blocks）", () => {
    const before = project({ prose: "甲。" });
    before.chapters.push({
      id: "ch2",
      title: "第二章",
      blocks: [{ type: "narration", text: "乙。" }],
      prose: "乙文。",
    });
    const { project: after } = flushChapterSurface(before, "ch2", "", "prose");
    expect(after.chapters[0].prose).toBe("甲。");
    expect(after.chapters[1].blocks).toEqual([]);
    expect(after.chapters[1].prose).toBe("");
  });
});

describe("清空 UX：inspectClearImpact 确认闸条件", () => {
  it("清 RPY 且 prose 非空 → needsConfirm + 字数", () => {
    const prose = "正文档里的正文，约略计数。";
    const before = project({ prose, blocks: rpyText });
    const impact = inspectClearImpact(before, "ch1", "", "rpy");
    expect(impact.needsConfirm).toBe(true);
    expect(impact.otherCharCount).toBe(prose.trim().length);
    expect(impact.otherSurfaceLabel).toBe("正文档");
    expect(impact.restoreText.length).toBeGreaterThan(0);
    expect(clearBothSurfacesConfirmBody(impact)).toContain(String(impact.otherCharCount));
  });

  it("确认 both → 两面清（与 flush 一致）", () => {
    const before = project({ prose: "正文。", blocks: rpyText, rpyFromProseHash: "abc" });
    const impact = inspectClearImpact(before, "ch1", "", "prose");
    expect(impact.needsConfirm).toBe(true);
    const { project: after, clearedOther } = flushChapterSurface(before, "ch1", "", "prose");
    expect(clearedOther).toBe(true);
    expect(after.chapters[0].prose).toBe("");
    expect(after.chapters[0].blocks).toEqual([]);
  });

  it("abort：不调用 flush → 工程不变", () => {
    const before = project({ prose: "正文。", blocks: rpyText });
    const impact = inspectClearImpact(before, "ch1", "", "prose");
    expect(impact.needsConfirm).toBe(true);
    // UI 取消路径：不调 flushChapterSurface
    expect(before.chapters[0].prose).toBe("正文。");
    expect(before.chapters[0].blocks).toEqual(rpyText);
    expect(impact.restoreText).toBe("正文。");
  });

  it("清正文档 + blocks 非空 → 对称 needsConfirm", () => {
    const before = project({ prose: "要删的正文档。", blocks: rpyText });
    const impact = inspectClearImpact(before, "ch1", "  \n", "prose");
    expect(impact.needsConfirm).toBe(true);
    expect(impact.otherCharCount).toBe(blocksToProse(rpyText, []).trim().length);
    expect(impact.currentSurfaceLabel).toBe("正文档");
    expect(impact.otherSurfaceLabel).toBe("脚本档");
  });

  it("回归：空 prose + 空编辑器 + 有 blocks → no-op、needsConfirm=false", () => {
    const before = project({ prose: "", blocks: rpyText });
    const impact = inspectClearImpact(before, "ch1", "", "prose");
    expect(impact.needsConfirm).toBe(false);
    expect(impact.otherCharCount).toBe(0);
    const { project: after, clearedOther } = flushChapterSurface(before, "ch1", "", "prose");
    expect(clearedOther).toBe(false);
    expect(after.chapters[0]).toBe(before.chapters[0]);
  });

  it("只清当前面且另一面本空 → 不弹确认", () => {
    const before = project({ prose: "只有正文档。", blocks: [] });
    const impact = inspectClearImpact(before, "ch1", "", "prose");
    expect(impact.needsConfirm).toBe(false);
    const { clearedOther } = flushChapterSurface(before, "ch1", "", "prose");
    expect(clearedOther).toBe(false);
  });

  it("Agent/buildLatest 第二道闸：needsConfirm 时不得静默 flush（由 UI await 确认）", () => {
    const before = project({ prose: "正文档。", blocks: rpyText });
    const impact = inspectClearImpact(before, "ch1", "", "prose");
    expect(impact.needsConfirm).toBe(true);
    // StudioApp.buildLatestProject：needsConfirm → 原样返回工程，禁止静默清两面
    // flushBeforeAgent 则先 await commitEditor（阻塞弹窗）再 buildLatest
    expect(before.chapters[0].prose).toBe("正文档。");
    expect(before.chapters[0].blocks).toEqual(rpyText);
  });
});
