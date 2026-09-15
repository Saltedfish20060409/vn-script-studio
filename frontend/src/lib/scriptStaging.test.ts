import { describe, expect, it } from "vitest";
import type { ScriptBlock } from "../types/vn";
import { blocksToEditable, editableToBlocks } from "./scriptCodec";

/** 新增语法（演出指令 / 变量 / 条件）的往返与解析测试。 */

function roundtrip(blocks: ScriptBlock[]): ScriptBlock[] {
  return editableToBlocks(blocksToEditable(blocks, []));
}

describe("演出指令：解析与往返", () => {
  it("play/stop music 带淡入淡出", () => {
    const blocks: ScriptBlock[] = [
      { type: "music", action: "play", file: "bgm/rain.ogg", fade: 2 },
      { type: "music", action: "stop", fade: 3 },
    ];
    const text = blocksToEditable(blocks, []);
    expect(text).toBe("play music bgm/rain.ogg fadein 2\nstop music fadeout 3");
    expect(roundtrip(blocks)).toEqual(blocks);
  });

  it("play/stop sound 与音量", () => {
    const blocks: ScriptBlock[] = [
      { type: "sound", action: "play", file: "sfx/door.mp3", volume: 0.6 },
      { type: "sound", action: "stop" },
    ];
    expect(blocksToEditable(blocks, [])).toBe(
      "play sound sfx/door.mp3 volume 0.6\nstop sound"
    );
    expect(roundtrip(blocks)).toEqual(blocks);
  });

  it("voice 播放与停止", () => {
    const blocks: ScriptBlock[] = [
      { type: "voice", action: "play", file: "voice/y01.ogg" },
      { type: "dialogue", characterId: "yuki", text: "你来了。" },
      { type: "voice", action: "stop" },
    ];
    const text = blocksToEditable(blocks, []);
    expect(text).toContain("voice voice/y01.ogg");
    expect(text).toContain("stop voice");
    expect(roundtrip(blocks)).toEqual(blocks);
  });

  it("wait 带与不带秒数", () => {
    expect(blocksToEditable([{ type: "wait", seconds: 1.5 }], [])).toBe("wait 1.5");
    expect(blocksToEditable([{ type: "wait" }], [])).toBe("wait");
    expect(roundtrip([{ type: "wait", seconds: 2 }])).toEqual([
      { type: "wait", seconds: 2 },
    ]);
  });

  it("camera 支持 zoom/x/y 与具名 transform", () => {
    expect(blocksToEditable([{ type: "camera", zoom: 1.2, x: 30 }], [])).toBe(
      "camera zoom 1.2 x 30"
    );
    expect(blocksToEditable([{ type: "camera", at: "my_cam" }], [])).toBe(
      "camera at my_cam"
    );
    expect(roundtrip([{ type: "camera", zoom: 1.2, x: 30, y: -10 }])).toEqual([
      { type: "camera", zoom: 1.2, x: 30, y: -10 },
    ]);
  });

  it("effect 带可选时长", () => {
    expect(blocksToEditable([{ type: "effect", kind: "shake" }], [])).toBe(
      "effect shake"
    );
    expect(roundtrip([{ type: "effect", kind: "flash_white", duration: 0.4 }])).toEqual([
      { type: "effect", kind: "flash_white", duration: 0.4 },
    ]);
  });
});

describe("变量与条件：解析与往返", () => {
  it("set 的三种运算符与字面量类型", () => {
    expect(blocksToEditable([{ type: "set", key: "affection", op: "+=", value: 1 }], [])).toBe(
      "set affection += 1"
    );
    expect(blocksToEditable([{ type: "set", key: "flag", op: "=", value: true }], [])).toBe(
      "set flag = true"
    );
    expect(
      blocksToEditable([{ type: "set", key: "who", op: "=", value: "由纪" }], [])
    ).toBe('set who = "由纪"');
    expect(roundtrip([{ type: "set", key: "n", op: "-=", value: 2 }])).toEqual([
      { type: "set", key: "n", op: "-=", value: 2 },
    ]);
  });

  it("if / elif / else 结构与嵌套正文往返一致", () => {
    const blocks: ScriptBlock[] = [
      {
        type: "if",
        branches: [
          {
            condition: "affection >= 3",
            blocks: [{ type: "narration", text: "她笑了。" }],
          },
          {
            condition: "affection >= 1",
            blocks: [{ type: "narration", text: "她点点头。" }],
          },
          { blocks: [{ type: "narration", text: "她别过头。" }] },
        ],
      },
    ];
    const text = blocksToEditable(blocks, []);
    expect(text).toContain("if affection >= 3:");
    expect(text).toContain("elif affection >= 1:");
    expect(text).toContain("else:");
    expect(text).toContain("    她笑了。".replace("她笑了。", '"她笑了。"'));
    expect(roundtrip(blocks)).toEqual(blocks);
  });

  it("if 分支里可以嵌 menu（缩进递归）", () => {
    const blocks: ScriptBlock[] = [
      {
        type: "if",
        branches: [
          {
            condition: "flag",
            blocks: [
              {
                type: "menu",
                id: "menu",
                choices: [{ text: "好", jump: "end" }],
              },
            ],
          },
        ],
      },
    ];
    expect(roundtrip(blocks)).toEqual(blocks);
  });

  it("menu 选项条件往返一致", () => {
    const blocks: ScriptBlock[] = [
      {
        type: "menu",
        id: "menu",
        choices: [
          { text: "接受她的伞", condition: "affection >= 2", jump: "end" },
          { text: "谢绝", jump: "end" },
        ],
      },
    ];
    const text = blocksToEditable(blocks, []);
    expect(text).toContain('"接受她的伞" if affection >= 2:');
    expect(roundtrip(blocks)).toEqual(blocks);
  });

  it("没有配对 if 的 else 不会吞内容", () => {
    const blocks = editableToBlocks("else:\n    孤儿内容");
    expect(blocks.some((b) => b.type === "raw")).toBe(true);
  });
});

describe("新语法不破坏既有行为", () => {
  it("未知行仍然降级为 raw（保留手写 Ren'Py 的能力）", () => {
    const blocks = editableToBlocks("$ renpy.pause(1)\nscene bg x");
    // raw 保留原始行（含缩进），不会被误解析成新语法
    expect(blocks[0]).toEqual({ type: "raw", code: "$ renpy.pause(1)" });
    expect(blocks[1].type).toBe("scene");
  });

  it("演出指令不会把相邻对白吞掉", () => {
    const blocks = editableToBlocks(
      'play music bgm/a.ogg\n"旁白一句话。"\nyuki "台词。"\nwait 1'
    );
    expect(blocks.map((b) => b.type)).toEqual([
      "music",
      "narration",
      "dialogue",
      "wait",
    ]);
  });
});
