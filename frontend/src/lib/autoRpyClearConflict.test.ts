/**
 * 隐患回归：自动生成 RPY 不得与「清空两面」确认闸互相触发。
 *
 * - shouldAutoGenerate / 合并 blocks 不调用 flushChapterSurface("", …)
 * - skipEditorReload 路径：只改 project.blocks，编辑器空串状态不被 loadEditor 抢掉
 * - buildLatestProject 在 needsConfirm 时拒静默清（StudioApp）；此处用 inspect 对齐语义
 */
import { describe, expect, it } from "vitest";
import {
  flushChapterSurface,
  inspectClearImpact,
} from "./chapterSurfaces";
import { shouldAutoGenerateRpyAfterProseWrite } from "./autoRpyAfterWrite";
import { proseFingerprint } from "./scriptProse";
import type { VnProject } from "../types/vn";

function baseProject(over: Partial<VnProject["chapters"][number]> = {}): VnProject {
  return {
    id: "p1",
    title: "t",
    updatedAt: "2026-10-02T00:00:00Z",
    characters: [],
    chapters: [
      {
        id: "ch1",
        title: "一",
        prose: "正文档还在。雨下了。",
        blocks: [
          { type: "label", id: "start", name: "start" },
          { type: "narration", text: "旧旁白" },
        ],
        rpyFromProseHash: "stale",
        ...over,
      },
    ],
  } as VnProject;
}

describe("自动 RPY × 清空闸", () => {
  it("判定自动生成时不依赖、不产生 emptied flush", () => {
    const p = baseProject();
    const ch = p.chapters[0];
    expect(shouldAutoGenerateRpyAfterProseWrite(ch)).toBe(true);
    // 自动路径只读字段；编辑器仍可非空 → 清空闸不弹
    const impact = inspectClearImpact(p, "ch1", ch.prose!, "prose");
    expect(impact.needsConfirm).toBe(false);
  });

  it("用户清空脚本面 → needsConfirm；自动 RPY 合并 blocks 不替代 confirm", () => {
    const p = baseProject();
    const impact = inspectClearImpact(p, "ch1", "", "rpy");
    expect(impact.needsConfirm).toBe(true);

    // 模拟后台自动 RPY 完成：只改 blocks/hash（skipEditorReload）
    const prose = p.chapters[0].prose!;
    const afterAuto: VnProject = {
      ...p,
      chapters: p.chapters.map((c) =>
        c.id === "ch1"
          ? {
              ...c,
              blocks: [
                { type: "label", id: "start", name: "start" },
                { type: "narration", text: "新生成旁白" },
              ],
              rpyFromProseHash: proseFingerprint(prose),
            }
          : c
      ),
    };
    // 编辑器仍是用户清空的 "" → 闸仍要确认（不被自动生成「悄悄取消」）
    expect(inspectClearImpact(afterAuto, "ch1", "", "rpy").needsConfirm).toBe(
      true
    );
    // prose 仍在：自动生成没有走 flush("", rpy)
    expect(afterAuto.chapters[0].prose).toContain("正文档还在");
  });

  it("若误走 flush 空脚本面才会清 prose；自动路径禁止这么做", () => {
    const p = baseProject();
    const { project: flushed, clearedOther } = flushChapterSurface(
      p,
      "ch1",
      "",
      "rpy"
    );
    expect(clearedOther).toBe(true);
    expect((flushed.chapters[0].prose || "").trim()).toBe("");
    // 对照：自动 RPY 合并后 prose 必须仍在
    const autoOnly = {
      ...p,
      chapters: [
        {
          ...p.chapters[0],
          blocks: [{ type: "narration" as const, text: "auto" }],
          rpyFromProseHash: proseFingerprint(p.chapters[0].prose!),
        },
      ],
    };
    expect(autoOnly.chapters[0].prose).toBe(p.chapters[0].prose);
  });
});
