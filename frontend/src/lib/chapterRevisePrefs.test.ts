/**
 * 改章方向：**不再弹窗拦人**，话里点过方向就用那个，否则照作者的说明改。
 *
 * 用户反馈原话（两轮）："那三种方向很多时候并不符合我想改的，更多时候看 Agent 理解"、
 * "为什么不能不弹窗直接回答呢？我感觉这个弹窗很多余"。所以：
 * - 方向选择器不再自动弹，改成按需打开（说「选个方向」）；
 * - 三档固定方向仍然可用——但靠**话里说**（「轻润」「只去说明书」「人味」），
 *   由 `agentIntent` 识别，不需要弹窗；
 * - `prefs.mode` 降级为"记录"，**不再参与判断**（否则又把作者钉回某个固定方向）。
 */
import { describe, expect, it } from "vitest";

import {
  FOLLOW_NOTE_MODE,
  getChapterRevisePrefs,
  prefsToNoteSuffix,
  resolveReviseMode,
} from "./chapterRevisePrefs";

describe("resolveReviseMode", () => {
  it("话里没点方向 → follow_note（照作者自己的说明改）", () => {
    expect(resolveReviseMode()).toBe(FOLLOW_NOTE_MODE);
  });

  it("话里点过方向 → 用他点的那个（「轻润」「只去说明书」「人味」都走这条路）", () => {
    expect(resolveReviseMode("light_touch")).toBe("light_touch");
    expect(resolveReviseMode("cut_lecture")).toBe("cut_lecture");
    expect(resolveReviseMode("human_warmth")).toBe("human_warmth");
  });

  it("作者在方向面板里挑了「就照我说的改」→ 仍是 follow_note", () => {
    expect(resolveReviseMode(FOLLOW_NOTE_MODE)).toBe(FOLLOW_NOTE_MODE);
  });

  it("**不再回落 human_warmth**：没点方向时必须把话语权交给作者的说明", () => {
    // 旧行为是 `prefs.mode || "human_warmth"`，会把"加强人味"那套指引无条件塞给模型，
    // 跟作者真正想改的东西打架——那正是"三选一不太有用"的根因。
    expect(resolveReviseMode()).not.toBe("human_warmth");
  });
});

describe("prefs 里记着的方向不再影响判断", () => {
  it("上次点过 cut_lecture，这次没点方向 → 仍按作者的说明改（不是 cut_lecture）", () => {
    // 纯函数已经不接受 prefs，所以这里直接从"记录"那一侧钉住语义：
    // 记录只是记录，取值不参与 resolveReviseMode
    expect(resolveReviseMode()).toBe(FOLLOW_NOTE_MODE);
    const recorded = { mode: "cut_lecture" as const };
    expect(recorded.mode).toBe("cut_lecture"); // 记录还在……
    expect(resolveReviseMode(undefined)).toBe(FOLLOW_NOTE_MODE); // ……但不影响这次
  });

  it("【本章偏好】后缀里不带 mode，免得旧方向从提示词另一头溜进去", () => {
    const suffix = prefsToNoteSuffix({
      mode: "cut_lecture",
      lockedNames: ["林夏"],
      preferKeepOriginal: true,
      notes: ["别动雨夜那段"],
    });
    expect(suffix).toContain("林夏");
    expect(suffix).toContain("别动雨夜那段");
    expect(suffix).not.toContain("cut_lecture");
    expect(suffix).not.toContain("只去说明书");
  });
});

describe("prefs 读写", () => {
  it("node 环境没有 localStorage 也不炸（读取回落空对象）", () => {
    expect(getChapterRevisePrefs("p", "c")).toEqual({});
  });
});
