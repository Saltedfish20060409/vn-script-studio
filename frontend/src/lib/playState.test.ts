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

  it("choose with jump seeks to the label", () => {
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
    expect(state.index).toBe(2);
    expect(state.stack).toHaveLength(0);
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
