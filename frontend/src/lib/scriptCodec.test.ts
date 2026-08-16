/**
 * scriptCodec 编解码单元测试
 *
 * 覆盖 blocksToEditable / editableToBlocks / blockTextRange：
 * 文本 ⇄ blocks 双向编解码，涵盖 label/scene/show/hide/dialogue/
 * narration/menu/jump/return/comment/raw 全部块类型，以及
 * CRLF 归一化、字符 defineName 映射、越界索引等边界情况。
 */
import { describe, it, expect } from "vitest";
import type { Character, ScriptBlock } from "../types/vn";
import { blocksToEditable, editableToBlocks, blockTextRange } from "./scriptCodec";

describe("editableToBlocks：各块类型解析", () => {
  it("解析 label 块（id 与 name 相同）", () => {
    const blocks = editableToBlocks("label start:");
    expect(blocks).toHaveLength(1);
    expect(blocks[0]).toEqual({
      type: "label",
      id: "start",
      name: "start",
    });
  });

  it("解析带 transition 的 scene 块", () => {
    const blocks = editableToBlocks("scene bg station with fade");
    expect(blocks[0]).toEqual({
      type: "scene",
      image: "bg station",
      transition: "fade",
    });
  });

  it("解析不带 transition 的 scene 块（transition 为 undefined）", () => {
    const blocks = editableToBlocks("scene bg park");
    expect(blocks[0]).toEqual({
      type: "scene",
      image: "bg park",
      transition: undefined,
    });
  });

  it("解析带站位 at 的 show 块", () => {
    const blocks = editableToBlocks("show linxia at center");
    expect(blocks[0]).toEqual({
      type: "show",
      image: "linxia",
      at: "center",
    });
  });

  it("解析 hide 块", () => {
    const blocks = editableToBlocks("hide linxia");
    expect(blocks[0]).toEqual({ type: "hide", image: "linxia" });
  });

  it("解析 dialogue 块（角色名 + 引号文本）", () => {
    const blocks = editableToBlocks('lx "我们走吧"');
    expect(blocks[0]).toEqual({
      type: "dialogue",
      characterId: "lx",
      text: "我们走吧",
    });
  });

  it("解析 narration 块（仅引号文本）", () => {
    const blocks = editableToBlocks('"雨停了。"');
    expect(blocks[0]).toEqual({ type: "narration", text: "雨停了。" });
  });

  it("解析 jump 块", () => {
    const blocks = editableToBlocks("jump next_scene");
    expect(blocks[0]).toEqual({ type: "jump", target: "next_scene" });
  });

  it("解析 return 块", () => {
    const blocks = editableToBlocks("return");
    expect(blocks[0]).toEqual({ type: "return" });
  });

  it("解析 comment 块并去除 # 前缀与首尾空白", () => {
    const blocks = editableToBlocks("  # 这里是注释  ");
    expect(blocks[0]).toEqual({ type: "comment", text: "这里是注释" });
  });

  it("无法识别的行降级为 raw 块并保留原行内容", () => {
    const code = "define e = Character('艾琳')";
    const blocks = editableToBlocks(code);
    expect(blocks[0]).toEqual({ type: "raw", code });
  });

  it("解析带 prompt 与跳转选项的 menu 块", () => {
    const text = [
      "menu m1:",
      '  "怎么办？"',
      '  "答应":',
      "    jump yes",
      '  "拒绝":',
      "    jump no",
    ].join("\n");
    const blocks = editableToBlocks(text);
    expect(blocks[0]).toEqual({
      type: "menu",
      id: "m1",
      prompt: "怎么办？",
      choices: [
        { text: "答应", jump: "yes" },
        { text: "拒绝", jump: "no" },
      ],
    });
  });

  it("menu 无 prompt 时 prompt 为 undefined", () => {
    const text = ["menu m2:", '  "走":', "    jump a"].join("\n");
    const blocks = editableToBlocks(text);
    const menu = blocks[0];
    expect(menu.type).toBe("menu");
    if (menu.type === "menu") {
      expect(menu.prompt).toBeUndefined();
      expect(menu.choices).toEqual([{ text: "走", jump: "a" }]);
    }
  });

  it("menu 选项缺 jump 时解析为 undefined", () => {
    const blocks = editableToBlocks(["menu m3:", '  "停留":'].join("\n"));
    const menu = blocks[0];
    if (menu.type === "menu") {
      expect(menu.choices).toEqual([{ text: "停留", jump: undefined }]);
    }
  });

  it("空文本与纯空白文本回退为默认 start label", () => {
    expect(editableToBlocks("")).toEqual([
      { type: "label", id: "start", name: "start" },
    ]);
    expect(editableToBlocks("   \n  \n ")).toEqual([
      { type: "label", id: "start", name: "start" },
    ]);
  });

  it("跳过空白行，仅保留有效块", () => {
    const blocks = editableToBlocks('label a:\n\n\n"旁白"');
    expect(blocks).toEqual([
      { type: "label", id: "a", name: "a" },
      { type: "narration", text: "旁白" },
    ]);
  });

  it("CRLF 行尾与 LF 解析结果一致", () => {
    const lf = editableToBlocks('label a:\r\nlx "hi"');
    const crlf = editableToBlocks('label a:\nlx "hi"');
    expect(lf).toEqual(crlf);
    expect(lf).toHaveLength(2);
  });
});

describe("blocksToEditable：块序列 → 文本", () => {
  const chars: Character[] = [{ id: "lx", defineName: "linxia", displayName: "林夏" }];

  it("dialogue 优先使用角色 defineName，找不到时回退 characterId", () => {
    const text = blocksToEditable(
      [
        { type: "dialogue", characterId: "lx", text: "你好" },
        { type: "dialogue", characterId: "someone", text: "喂" },
      ],
      chars
    );
    expect(text).toBe('linxia "你好"\nsomeone "喂"');
  });

  it("menu 块序列化为带缩进的 prompt 与选项", () => {
    const text = blocksToEditable(
      [
        {
          type: "menu",
          id: "m1",
          prompt: "选吧",
          choices: [{ text: "A", jump: "a" }, { text: "B" }],
        },
      ],
      []
    );
    expect(text).toBe(
      ["menu m1:", '  "选吧"', '  "A":', "    jump a", '  "B":', "    jump start"].join(
        "\n"
      )
    );
  });

  it("无 prompt 的 menu 不输出空 prompt 行", () => {
    const text = blocksToEditable(
      [{ type: "menu", id: "m2", choices: [{ text: "A", jump: "a" }] }],
      []
    );
    expect(text).toBe(["menu m2:", '  "A":', "    jump a"].join("\n"));
  });

  it("scene 无 transition 时输出不带 with 子句", () => {
    const text = blocksToEditable([{ type: "scene", image: "bg park" }], []);
    expect(text).toBe("scene bg park");
  });
});

describe("完整双向编解码 roundtrip", () => {
  const blocks: ScriptBlock[] = [
    { type: "label", id: "start", name: "start" },
    { type: "scene", image: "bg station", transition: "fade" },
    { type: "show", image: "linxia", at: "center" },
    { type: "hide", image: "linxia" },
    { type: "narration", text: "雨停了。" },
    { type: "dialogue", characterId: "lx", text: "我们走吧" },
    { type: "jump", target: "next" },
    { type: "return" },
    { type: "comment", text: "这里是注释" },
    { type: "raw", code: "define e = Character('艾琳')" },
    {
      type: "menu",
      id: "m1",
      prompt: "怎么办？",
      choices: [
        { text: "答应", jump: "yes" },
        { text: "拒绝", jump: "no" },
      ],
    },
  ];

  it("blocks → editable → blocks 完全一致", () => {
    const editable = blocksToEditable(blocks, []);
    expect(editableToBlocks(editable)).toEqual(blocks);
  });

  it("roundtrip 输出的块数量与原始一致", () => {
    const editable = blocksToEditable(blocks, []);
    const parsed = editableToBlocks(editable);
    expect(parsed).toHaveLength(blocks.length);
  });
});

describe("blockTextRange：块在可编辑文本中的字符区间", () => {
  const blocks: ScriptBlock[] = [
    { type: "label", id: "start", name: "start" },
    { type: "dialogue", characterId: "lx", text: "hi" },
  ];

  it("首个块的区间从 0 开始", () => {
    expect(blockTextRange(blocks, [], 0)).toEqual({ start: 0, end: 12 });
  });

  it("后续块 start 为前一块 end + 1（换行符）", () => {
    // "label start:" 长度 12，第 2 块文本 'lx "hi"' 长度 7
    expect(blockTextRange(blocks, [], 1)).toEqual({ start: 13, end: 20 });
  });

  it("区间与整段文本长度吻合", () => {
    const full = blocksToEditable(blocks, []);
    const range = blockTextRange(blocks, [], 1);
    expect(full.length).toBe(range!.end);
    expect(full.slice(range!.start, range!.end)).toBe('lx "hi"');
  });

  it("角色 defineName 会改变对应块区间长度", () => {
    const chars: Character[] = [
      { id: "lx", defineName: "linxia", displayName: "林夏" },
    ];
    const range = blockTextRange(blocks, chars, 1);
    // 'linxia "hi"' 长度 11 → start 13, end 24
    expect(range).toEqual({ start: 13, end: 24 });
  });

  it("越界索引返回 null", () => {
    expect(blockTextRange(blocks, [], -1)).toBeNull();
    expect(blockTextRange(blocks, [], 2)).toBeNull();
    expect(blockTextRange([], [], 0)).toBeNull();
  });
});
