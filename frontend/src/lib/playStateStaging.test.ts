import { describe, expect, it } from "vitest";
import type { ScriptBlock } from "../types/vn";
import { advance, PLAY_START, pickIfBranch, visibleChoices } from "./playState";

const label = (name: string): ScriptBlock => ({ type: "label", id: name, name });
const narr = (text: string): ScriptBlock => ({ type: "narration", text });
const music = (file: string): ScriptBlock => ({ type: "music", action: "play", file });
const wait = (seconds: number): ScriptBlock => ({ type: "wait", seconds });
const setVar = (key: string, value: number): ScriptBlock => ({
  type: "set",
  key,
  op: "+=",
  value,
});

describe("演出指令（瞬时块）在推进时被收集", () => {
  it("音乐/变量等不产生停顿，但要按顺序回收", () => {
    const blocks: ScriptBlock[] = [
      music("bgm/rain.ogg"),
      setVar("affection", 1),
      { type: "camera", zoom: 1.2 },
      narr("A"),
    ];
    const out = advance(PLAY_START, blocks);
    expect(out.ended).toBe(false);
    expect(out.state.index).toBe(3); // 落在旁白上
    expect(out.executed.map((b) => b.type)).toEqual(["music", "set", "camera"]);
  });

  it("wait 是会产生停顿的一步（播放器据此自动继续）", () => {
    const blocks: ScriptBlock[] = [narr("A"), wait(1.5), narr("B")];
    const first = advance(PLAY_START, blocks);
    expect(first.state.index).toBe(0);
    const second = advance(first.state, blocks);
    expect(second.state.index).toBe(1); // 停在 wait 上
    const third = advance(second.state, blocks);
    expect(third.state.index).toBe(2);
  });
});

describe("线性 jump 必须被跟随（旧版会跳过，导致演出不该出现的正文）", () => {
  const blocks: ScriptBlock[] = [
    label("start"), // 0
    narr("你选择了留下"), // 1
    { type: "jump", target: "end" }, // 2
    narr("这段不该演"), // 3
    label("end"), // 4
    narr("结局"), // 5
  ];
  const labelIndex = new Map([
    ["start", 0],
    ["end", 4],
  ]);

  it("从 jump 跳到目标 label 之后的第一条可见内容", () => {
    const out = advance({ ...PLAY_START, index: 1 }, blocks, {}, labelIndex);
    expect(out.jumped).toBe(true);
    expect(out.state.index).toBe(5); // 「结局」，而不是 3
  });

  it("跳转途中经过的瞬时指令也会被收集", () => {
    const withAudio: ScriptBlock[] = [
      narr("A"), // 0
      { type: "jump", target: "end" }, // 1
      narr("不该演"), // 2
      label("end"), // 3
      music("bgm/final.ogg"), // 4
      narr("结局"), // 5
    ];
    const out = advance({ ...PLAY_START, index: 0 }, withAudio, {}, new Map([["end", 3]]));
    expect(out.state.index).toBe(5);
    expect(out.executed).toEqual([music("bgm/final.ogg")]);
  });

  it("jump 目标不存在时跳过它继续往下，不崩", () => {
    const out = advance({ ...PLAY_START, index: 1 }, blocks, {}, new Map([["start", 0]]));
    expect(out.state.index).toBe(3);
    expect(out.jumped).toBe(false);
  });
});

describe("条件分支 if", () => {
  const blocks: ScriptBlock[] = [
    narr("开场"), // 0
    {
      type: "if",
      branches: [
        { condition: "affection >= 3", blocks: [narr("她笑了。")] },
        { condition: "affection >= 1", blocks: [narr("她点点头。")] },
        { blocks: [narr("她别过头。")] },
      ],
    }, // 1
    narr("继续"), // 2
  ];

  it("按变量选分支，演完后回到 if 之后", () => {
    const hi = advance({ ...PLAY_START, index: 0 }, blocks, {
      variables: { affection: 5 },
    });
    expect(hi.state.stack).toHaveLength(1);
    expect(hi.state.stack[0][0]).toEqual(narr("她笑了。"));

    const next = advance(hi.state, blocks, { variables: { affection: 5 } });
    // 分支只有一句 → 演完直接回到 if 之后的「继续」
    expect(next.state.stack).toHaveLength(0);
    expect(next.state.index).toBe(2);
  });

  it("走 else 分支", () => {
    const out = advance({ ...PLAY_START, index: 0 }, blocks, {
      variables: { affection: 0 },
    });
    expect(out.state.stack[0][0]).toEqual(narr("她别过头。"));
  });

  it("条件写错的分支按不成立处理（不会静默走进去）", () => {
    const broken: ScriptBlock[] = [
      { type: "if", branches: [{ condition: "affection >=> 3", blocks: [narr("不该进")] }] },
      narr("之后"),
    ];
    const out = advance(PLAY_START, broken, { variables: { affection: 5 } });
    expect(out.state.index).toBe(1);
    expect(out.state.stack).toHaveLength(0);
  });

  it("pickIfBranch 顺序匹配，空条件是兜底", () => {
    const ifBlock: ScriptBlock = {
      type: "if",
      branches: [
        { condition: "a >= 2", blocks: [narr("1")] },
        { condition: "a >= 1", blocks: [narr("2")] },
        { blocks: [narr("else")] },
      ],
    };
    expect(pickIfBranch(ifBlock, { a: 2 })?.blocks[0]).toEqual(narr("1"));
    expect(pickIfBranch(ifBlock, { a: 1 })?.blocks[0]).toEqual(narr("2"));
    expect(pickIfBranch(ifBlock, { a: 0 })?.blocks[0]).toEqual(narr("else"));
    expect(pickIfBranch(narr("x"), {})).toBeNull();
  });

  it("嵌套 if 也能进出", () => {
    const nested: ScriptBlock[] = [
      {
        type: "if",
        branches: [
          {
            condition: "a >= 1",
            blocks: [
              narr("外层"),
              { type: "if", branches: [{ condition: "b >= 1", blocks: [narr("内层")] }] },
            ],
          },
        ],
      },
      narr("收尾"),
    ];
    const step1 = advance(PLAY_START, nested, { variables: { a: 1, b: 1 } });
    expect(step1.state.stack[0][0]).toEqual(narr("外层"));
    const step2 = advance(step1.state, nested, { variables: { a: 1, b: 1 } });
    expect(step2.state.stack).toHaveLength(2);
    const step3 = advance(step2.state, nested, { variables: { a: 1, b: 1 } });
    expect(step3.state.index).toBe(1);
    expect(step3.state.stack).toHaveLength(0);
  });
});

describe("条件选项过滤", () => {
  it("只显示条件成立的选项", () => {
    const choices = [
      { text: "接受她的伞", condition: "affection >= 2" },
      { text: "谢绝" },
      { text: "提起往事", condition: "flag" },
    ];
    expect(visibleChoices(choices, { affection: 2, flag: false }).map((c) => c.text)).toEqual([
      "接受她的伞",
      "谢绝",
    ]);
    expect(visibleChoices(choices, { affection: 0, flag: true }).map((c) => c.text)).toEqual([
      "谢绝",
      "提起往事",
    ]);
    // 条件写错的选项不显示（导出侧也会显式注释掉）
    expect(visibleChoices([{ text: "坏", condition: "a >=> 1" }], { a: 9 })).toHaveLength(0);
  });
});

describe("死循环检测", () => {
  it("自跳转会被判为 looped 而不是无限推进", () => {
    const blocks: ScriptBlock[] = [
      label("start"), // 0
      { type: "jump", target: "start" }, // 1
    ];
    const out = advance(PLAY_START, blocks, {}, new Map([["start", 0]]));
    expect(out.looped).toBe(true);
    expect(out.ended).toBe(true);
  });
});
