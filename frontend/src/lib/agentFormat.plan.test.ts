/**
 * agentFormat：方案卡片逐条动作的测试。
 *
 * 守的是"点确认不能是盲签"：带正文的动作（append_script / replace_script）必须在卡片上
 * 露出正文开头与字数——线上那次整章写入，卡片只写「追加正文」，作者看不到一个字就得按确认。
 */
import { describe, it, expect } from "vitest";
import { describeActionList, planActionLines } from "./agentFormat";
import { copyForProject } from "./genreCopy";

const copy = copyForProject({ genre: "vn" } as never);

describe("planActionLines：带正文的动作要露出正文", () => {
  it("纯结构化动作只给标签", () => {
    const lines = planActionLines(
      [{ op: "update_character", ref: "linxia", patch: { voice: "克制" } } as never],
      copy
    );
    expect(lines).toHaveLength(1);
    expect(lines[0]).not.toContain("字）");
  });

  it("追加正文：标签 + 开头 + 字数", () => {
    const lines = planActionLines(
      [
        {
          op: "append_script",
          chapterRef: "ch1",
          text: "她望着你，比刚才久。",
        } as never,
      ],
      copy
    );
    expect(lines[0]).toContain("她望着你");
    expect(lines[0]).toContain("（10 字）");
  });

  it("长正文只取前 100 字并标省略号", () => {
    const long = "正文".repeat(300); // 600 字
    const lines = planActionLines(
      [{ op: "replace_script", text: long } as never],
      copy
    );
    expect(lines[0]).toContain("…");
    expect(lines[0]).toContain("（600 字）");
    // 预览行本身不该有 600 字那么长
    expect(lines[0].length).toBeLessThan(160);
  });

  it("换行被压平——卡片是一行一条，不能把正文原样灌进来", () => {
    const lines = planActionLines(
      [{ op: "append_script", text: "第一句。\n\n第二句。" } as never],
      copy
    );
    expect(lines[0]).not.toContain("\n");
    expect(lines[0]).toContain("第一句。 第二句。");
  });

  it("多项动作逐条对应（顺序与 describeActionList 一致）", () => {
    const actions = [
      { op: "append_script", text: "甲" },
      { op: "update_character", ref: "c1", patch: {} },
    ] as never[];
    const labels = describeActionList(actions, copy);
    const lines = planActionLines(actions, copy);
    expect(lines).toHaveLength(2);
    expect(lines[0].startsWith(labels[0])).toBe(true);
    expect(lines[1]).toBe(labels[1]);
  });

  it("没有 text 字段 / text 不是字符串时不会打印 undefined", () => {
    const lines = planActionLines(
      [
        { op: "append_script", text: "正文" },
        { op: "delete_chapter", ref: "ch2" },
      ] as never[],
      copy
    );
    for (const line of lines) {
      expect(line).not.toMatch(/undefined|null|NaN/);
    }
  });
});
