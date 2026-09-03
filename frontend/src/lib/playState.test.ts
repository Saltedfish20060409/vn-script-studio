import { describe, expect, it } from "vitest";
import type { ScriptBlock } from "../types/vn";
import {
  advance,
  choose,
  nextVisible,
  PLAY_START,
  scopeOf,
} from "./playState";

const label = (name: string): ScriptBlock => ({ type: "label", id: name, name });
const narr = (text: string): ScriptBlock => ({ type: "narration", text });
const dialog = (text: string): ScriptBlock => ({
  type: "dialogue",
  characterId: "c",
  text,
});

describe("playState", () => {
  it("menu 分支正文以 return 收尾时，走完分支即结束（不归零重播）", () => {
    const blocks: ScriptBlock[] = [
      narr("A"),
      {
        type: "menu",
        id: "m",
        choices: [
          {
            text: "接过伞沿",
            blocks: [dialog("谢谢。"), dialog("不用。"), { type: "return" }],
          },
        ],
      },
      { type: "return" },
    ];
    const menuIdx = 1;
    const { state } = choose(
      { ...PLAY_START, index: menuIdx },
      blocks,
      { blocks: [dialog("谢谢。"), dialog("不用。"), { type: "return" }] },
      new Map()
    );
    // 播放分支内的两句对白
    const s1 = advance(state, blocks);
    expect(s1.ended).toBe(false);
    const s2 = advance(s1.state, blocks);
    // 分支以 return 结束 → advance 直接 ended，而不是 index 归零
    expect(s2.ended).toBe(true);
    expect(s2.state.index).not.toBe(0);
  });

  it("分支无 return 且菜单后无可见内容时结束，不死循环回开头", () => {
    const blocks: ScriptBlock[] = [
      narr("A"),
      {
        type: "menu",
        id: "m",
        choices: [{ text: "x", blocks: [dialog("inner")] }],
      },
    ];
    const menuIdx = 1;
    const { state } = choose(
      { ...PLAY_START, index: menuIdx },
      blocks,
      { blocks: [dialog("inner")] },
      new Map()
    );
    // 播放分支内唯一对白后：栈空 + 菜单后无可见块 → 必须 ended，
    // 而不是回到 index 0 造成死循环。
    const fin = advance(state, blocks);
    expect(fin.ended).toBe(true);
  });

  it("advance skips invisible blocks (labels/comments) to the next visible", () => {
    const blocks = [label("start"), narr("A"), label("mid"), dialog("B")];
    // Start at the narration (index 1).
    const { state } = advance({ ...PLAY_START, index: 1 }, blocks);
    expect(state.index).toBe(3); // label at 2 skipped
  });

  it("advance ends the chapter after the last visible block", () => {
    const blocks = [narr("only")];
    const { ended } = advance(PLAY_START, blocks);
    expect(ended).toBe(true);
  });

  it("choose with jump seeks to the first visible after the label", () => {
    const blocks: ScriptBlock[] = [
      label("start"),
      narr("A"),
      label("end"),
      narr("B"),
      { type: "menu", id: "m", choices: [{ text: "x", jump: "end" }] },
    ];
    const menuIdx = 4;
    const { state } = choose(
      { ...PLAY_START, index: menuIdx },
      blocks,
      { jump: "end" },
      new Map([["end", 2]])
    );
    // label(2) 之后第一个可见块是 narr("B")(3)
    expect(state.index).toBe(3);
    expect(state.stack).toHaveLength(0);
  });

  it("choose with jump lands on the next VISIBLE block after the label", () => {
    // 真实场景：jump 目标是 label，UI 必须落在 label 之后第一个可见块，
    // 否则停在 label 上 → stage 空白页（用户反馈的 bug）。
    const blocks: ScriptBlock[] = [
      label("start"),
      narr("A"),
      { type: "menu", id: "m", choices: [{ text: "x", jump: "after" }] },
      label("after"), // label 本身不可见
      dialog("B"),    // 应落在这里
    ];
    const menuIdx = 2;
    const labelMap = new Map<string, number>([["after", 3]]);
    const { state, ended } = choose(
      { ...PLAY_START, index: menuIdx },
      blocks,
      { jump: "after" },
      labelMap
    );
    expect(ended).toBe(false);
    // 不能停在 label(3) 上 → 应自动跳到下一个可见块(4)
    expect(state.index).toBe(4);
  });

  it("choose with inline blocks enters them and resumes after the menu", () => {
    const blocks: ScriptBlock[] = [
      narr("A"),
      { type: "menu", id: "m", choices: [{ text: "x", blocks: [dialog("inner")] }] },
      narr("after"),
    ];
    const menuIdx = 1;
    const { state } = choose(
      { ...PLAY_START, index: menuIdx },
      blocks,
      { blocks: [dialog("inner")] },
      new Map()
    );
    expect(state.stack).toHaveLength(1);
    // Inline block visible at index 0 of the pushed scope.
    expect(scopeOf(state, blocks)[state.index]).toEqual(dialog("inner"));
    // Advancing past the inline block resumes after the menu (index 2).
    const { state: after } = advance(state, blocks);
    expect(after.index).toBe(2);
    expect(after.stack).toHaveLength(0);
  });

  it("nextVisible returns null past the end", () => {
    expect(nextVisible([label("a")], 0)).toBeNull();
    expect(nextVisible([narr("x")], 0)).toBe(0);
  });
});
