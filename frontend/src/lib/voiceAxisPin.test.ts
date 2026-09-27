/**
 * 定口吻的方向标签：**勾了标签不等于这一轮要用标签**。
 *
 * 钉的是用户报的那个 bug：勾过一两次标签之后，三组方向永远是那三个。
 * 根因不是模型，是主按钮和「按标签重开」调同一个函数、且都无条件发标签，
 * 而后端收到 3 个 pinned 轴就会命令模型"勿改名"。
 */
import { describe, expect, it } from "vitest";

import type { VoiceAxisTag } from "../api/voice";
import {
  MAX_PINNED_TAGS,
  axisTagsForGeneration,
  pinnedTagLabels,
  pinnedTagsNote,
  tagSelectionHint,
} from "./voiceAxisPin";

const POOL: VoiceAxisTag[] = [
  { id: "cold_short", label: "冷短回避", hint: "更冷、短句" },
  { id: "cynical", label: "愤世讽刺", hint: "冷嘲世情" },
  { id: "loyal_blunt", label: "忠直硬梆", hint: "不会绕弯" },
];

describe("axisTagsForGeneration", () => {
  it("主按钮不钉标签：勾了也不发（这正是方向被永久钉死的根因）", () => {
    expect(
      axisTagsForGeneration("preference", false, ["cold_short", "cynical"])
    ).toBeUndefined();
    expect(axisTagsForGeneration("interview", false, ["cold_short"])).toBeUndefined();
  });

  it("只有「按标签重开」才把勾选发出去", () => {
    expect(
      axisTagsForGeneration("preference", true, ["cold_short", "cynical"])
    ).toEqual(["cold_short", "cynical"]);
    expect(axisTagsForGeneration("interview", true, ["cynical"])).toEqual(["cynical"]);
  });

  it("长场次 / 手写金句不用轴：就算按了带标签的按钮也不发", () => {
    expect(axisTagsForGeneration("scene", true, ["cold_short"])).toBeUndefined();
    expect(axisTagsForGeneration("manual", true, ["cold_short"])).toBeUndefined();
  });

  it("最多 3 个（与界面勾选上限、后端 axes_from_tag_ids 一致）", () => {
    const four = ["a", "b", "c", "d"];
    expect(axisTagsForGeneration("preference", true, four)).toEqual(["a", "b", "c"]);
    expect(MAX_PINNED_TAGS).toBe(3);
  });

  it("一个都没勾时，按标签重开发 undefined 而不是空数组", () => {
    // 两者后端等价，但省略字段更能表达"这一轮不涉及标签"
    expect(axisTagsForGeneration("preference", true, [])).toBeUndefined();
  });
});

describe("pinnedTagLabels", () => {
  it("把 id 翻成界面上的标签名", () => {
    expect(pinnedTagLabels(["cold_short", "cynical"], POOL)).toEqual([
      "冷短回避",
      "愤世讽刺",
    ]);
  });

  it("查不到的 id 原样返回，不吞掉证据", () => {
    expect(pinnedTagLabels(["已下线标签"], POOL)).toEqual(["已下线标签"]);
  });

  it("空 / 缺省返回空数组", () => {
    expect(pinnedTagLabels(undefined, POOL)).toEqual([]);
    expect(pinnedTagLabels([], POOL)).toEqual([]);
  });
});

describe("pinnedTagsNote", () => {
  it("钉了标签就说清是钉的、并给出怎么换", () => {
    const note = pinnedTagsNote(["cold_short", "cynical"], POOL);
    expect(note).toContain("冷短回避、愤世讽刺");
    expect(note).toContain("由你勾的标签钉住");
    expect(note).toContain("生成三组");
  });

  it("没钉就不显示任何东西", () => {
    expect(pinnedTagsNote(undefined, POOL)).toBe("");
    expect(pinnedTagsNote([], POOL)).toBe("");
  });
});

describe("tagSelectionHint", () => {
  it("勾了但本轮没用上 → 说明为什么（修复后新出现的困惑状态）", () => {
    const hint = tagSelectionHint(["cold_short", "cynical"], undefined);
    expect(hint).toContain("2 个方向标签");
    expect(hint).toContain("按标签重开");
  });

  it("没勾就不显示", () => {
    expect(tagSelectionHint([], undefined)).toBe("");
  });

  it("已经钉过标签时不重复说一遍（那时显示 pinnedTagsNote）", () => {
    expect(tagSelectionHint(["cold_short"], ["cold_short"])).toBe("");
  });
});
