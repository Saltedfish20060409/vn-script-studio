/**
 * 改章方向：「什么时候问、用什么方向」这条规则。
 *
 * 为什么专门测它（用户反馈原话）："那三种方向很多时候并不符合我想改的，更多时候看 Agent
 * 理解"。所以这次把**用自己的话说**提成主路径，并让"作者说的话"优先于记着的旧方向。
 * 下面每一条都对应一个真实会踩的坑。
 */
import { describe, expect, it } from "vitest";

import {
  FOLLOW_NOTE_MODE,
  getChapterRevisePrefs,
  resolveRevisePlan,
  type ChapterRevisePrefs,
} from "./chapterRevisePrefs";

function prefs(p: ChapterRevisePrefs = {}): ChapterRevisePrefs {
  return p;
}

describe("resolveRevisePlan —— 要不要问", () => {
  it("没表态过、话里也没点方向 → 问一次（保留既有行为）", () => {
    expect(resolveRevisePlan({ prefs: prefs() }).openPicker).toBe(true);
  });

  it("话里已点明方向（如「人味」）→ 不问，用他点的那个", () => {
    const plan = resolveRevisePlan({ modeFromSpeech: "human_warmth", prefs: prefs() });
    expect(plan.openPicker).toBe(false);
    expect(plan.mode).toBe("human_warmth");
  });

  it("调用方已决定不问（「再润」走 polish 分支）→ 不问", () => {
    const plan = resolveRevisePlan({ skipModePicker: true, prefs: prefs() });
    expect(plan.openPicker).toBe(false);
  });

  it("勾过「以后直接照我说的改」→ 不再问", () => {
    const plan = resolveRevisePlan({ prefs: prefs({ askMode: false }) });
    expect(plan.openPicker).toBe(false);
  });

  it("上次选过固定方向、但没勾不再问 → 仍然问（确认一次是有意保留的）", () => {
    const plan = resolveRevisePlan({ prefs: prefs({ mode: "light_touch" }) });
    expect(plan.openPicker).toBe(true);
  });
});

describe("resolveRevisePlan —— 用什么方向", () => {
  it("弹窗里「就照我说的改」→ follow_note（不注入固定方向）", () => {
    const plan = resolveRevisePlan({
      customNote: "把后面那段展开重写，别动前面的雨夜戏",
      prefs: prefs(),
    });
    expect(plan.openPicker).toBe(false);
    expect(plan.mode).toBe(FOLLOW_NOTE_MODE);
  });

  it("**关键**：勾了不再问时，不能被记着的旧方向压住作者这次说的话", () => {
    // 上次他选过「加强人味」，这次想改的完全不是那回事——若沿用旧方向，
    // 提示词里那条「回炉指引」就会跟他自己的说明打架
    const plan = resolveRevisePlan({ prefs: prefs({ mode: "human_warmth", askMode: false }) });
    expect(plan.mode).toBe(FOLLOW_NOTE_MODE);
  });

  it("但话里明确点过方向时，仍然以他点的为准（优先级最高）", () => {
    const plan = resolveRevisePlan({
      modeFromSpeech: "cut_lecture",
      prefs: prefs({ mode: "human_warmth", askMode: false }),
    });
    expect(plan.mode).toBe("cut_lecture");
  });

  it("自定义说明为空串时不算「用自己的话」", () => {
    const plan = resolveRevisePlan({ customNote: "   ", skipModePicker: true, prefs: prefs() });
    expect(plan.mode).toBe("human_warmth");
  });
});

describe("prefs 存取", () => {
  it("askMode 能存能读（未设置 = 还没表态过）", () => {
    // node 环境没有 localStorage：这个用例只钉类型与默认值语义
    expect(getChapterRevisePrefs("p", "c").askMode).toBeUndefined();
  });
});
