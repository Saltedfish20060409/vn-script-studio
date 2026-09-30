/**
 * agentFlowMessage 单元测试
 *
 * 守的是一个"记录完整性"的约定：作者原话必须在对话记录里，且不能被系统标记挤掉、
 * 不能出现空段落或 undefined。这些用例对应线上那次排查（记录里只剩系统标记）。
 */
import { describe, it, expect } from "vitest";
import { attachmentLines, flowUserMessage } from "./agentFlowMessage";

describe("flowUserMessage：作者原话必须留在记录里", () => {
  it("原话在前、标记在后、附件行最后", () => {
    const msg = flowUserMessage(
      "【写入设定页】请根据附件更新故事设定与角色卡。",
      "按附件整理设定条目",
      ["设定.md（1200 字）"]
    );
    expect(msg).toBe(
      "按附件整理设定条目\n\n【写入设定页】请根据附件更新故事设定与角色卡。\n\n📎 设定.md（1200 字）"
    );
  });

  it("没有原话时不留空段落（按钮路径就是这样）", () => {
    const msg = flowUserMessage("【写入设定页】请根据附件更新故事设定与角色卡。", "", [
      "第一章_改写稿.docx（1907 字）",
    ]);
    expect(msg.startsWith("【写入设定页】")).toBe(true);
    expect(msg).not.toMatch(/^\n/);
    expect(msg).not.toContain("\n\n\n");
  });

  it("没有附件时不出现 📎 行", () => {
    expect(flowUserMessage("【定稿】请检查并写入本章。", "定稿")).toBe(
      "定稿\n\n【定稿】请检查并写入本章。"
    );
  });

  it("只有空白原话 = 没有原话", () => {
    expect(flowUserMessage("【文风体检】请检查当前章节草稿。", "   ")).toBe(
      "【文风体检】请检查当前章节草稿。"
    );
  });

  it("多个附件拼成一行，用顿号分隔", () => {
    const msg = flowUserMessage("【整理关系/时间线】", "整理进待审", [
      "a.md（10 字）",
      "b.txt（20 字）",
    ]);
    expect(msg).toBe(
      "整理进待审\n\n【整理关系/时间线】\n\n📎 a.md（10 字）、b.txt（20 字）"
    );
  });

  it("不会出现 undefined / null / NaN", () => {
    const cases = [
      flowUserMessage("【记】", undefined, undefined),
      flowUserMessage("【记】", "", []),
      flowUserMessage("【记】", "我说的话", ["无字数.docx"]),
    ];
    for (const c of cases) {
      expect(c).not.toMatch(/undefined|null|NaN/);
    }
  });
});

describe("attachmentLines", () => {
  it("优先用 chars，退回 text 长度", () => {
    expect(attachmentLines([{ filename: "a.md", chars: 12 }])).toEqual([
      "a.md（12 字）",
    ]);
    expect(attachmentLines([{ filename: "b.md", text: "12345" }])).toEqual([
      "b.md（5 字）",
    ]);
  });

  it("两个都没有时只写文件名，不写 NaN", () => {
    expect(attachmentLines([{ filename: "c.md" }])).toEqual(["c.md"]);
  });
});
