/**
 * mapOccurrences 地点出现扫描单元测试
 *
 * 覆盖 normalizeSceneKey 键归一化、findLocationOccurrences 的
 * scene/text 命中与章节过滤、primaryEvidence 优先级、
 * buildPlaceNeedles 去重与排序、tokenizeScriptLine 分词、
 * placeTokenAtOffset 光标偏移命中（含边界）。
 */
import { describe, it, expect } from "vitest";
import type { Location, SceneChapter } from "../types/vn";
import {
  normalizeSceneKey,
  findLocationOccurrences,
  primaryEvidence,
  buildPlaceNeedles,
  tokenizeScriptLine,
  placeTokenAtOffset,
} from "./mapOccurrences";

describe("normalizeSceneKey：键归一化", () => {
  it("去除首尾空白、转小写、折叠连续空白", () => {
    expect(normalizeSceneKey("  BG  Station_Night ")).toBe(
      "bg station_night"
    );
  });

  it("空串与纯空白返回空串", () => {
    expect(normalizeSceneKey("")).toBe("");
    expect(normalizeSceneKey("   ")).toBe("");
  });
});

describe("findLocationOccurrences：章节命中", () => {
  const loc: Location = {
    id: "l1",
    name: "车站",
    imageTag: "bg station",
    tags: ["车站"],
  };
  const chapters: SceneChapter[] = [
    {
      id: "c1",
      title: "第一章",
      blocks: [
        { type: "scene", image: "bg station" },
        { type: "dialogue", characterId: "lx", text: "我们到了车站" },
        { type: "narration", text: "雨还在下" },
      ],
    },
    { id: "c2", title: "第二章", blocks: [{ type: "jump", target: "x" }] },
  ];

  it("scene 块按 imageTag 命中 kind=scene", () => {
    const occ = findLocationOccurrences(loc, chapters);
    expect(occ).toHaveLength(1);
    expect(occ[0].chapterId).toBe("c1");
    expect(occ[0].chapterTitle).toBe("第一章");
    expect(occ[0].hits[0]).toEqual({
      blockIndex: 0,
      kind: "scene",
      evidence: "scene bg station",
    });
  });

  it("对话/旁白按名称或 tag 命中 kind=text", () => {
    const occ = findLocationOccurrences(loc, chapters);
    expect(occ[0].hits[1]).toMatchObject({
      blockIndex: 1,
      kind: "text",
    });
    expect(occ[0].hits[1].evidence).toContain("我们到了车站");
  });

  it("无命中的章节被整体跳过", () => {
    const occ = findLocationOccurrences(loc, chapters);
    expect(occ.map((o) => o.chapterId)).toEqual(["c1"]);
  });

  it("scene imageTag 匹配不区分大小写", () => {
    const upper: Location = { ...loc, imageTag: "BG STATION" };
    const occ = findLocationOccurrences(upper, chapters);
    expect(occ[0].hits[0].kind).toBe("scene");
  });

  it("仅名称命中（无 imageTag）也能找到 text 命中", () => {
    const nameOnly: Location = { id: "l2", name: "咖啡馆" };
    const chs: SceneChapter[] = [
      {
        id: "c1",
        title: "第一章",
        blocks: [{ type: "dialogue", characterId: "a", text: "我们去咖啡馆吧" }],
      },
    ];
    const occ = findLocationOccurrences(nameOnly, chs);
    expect(occ).toHaveLength(1);
    expect(occ[0].hits[0]).toMatchObject({ kind: "text", blockIndex: 0 });
  });

  it("tag 别名也能命中", () => {
    const tagged: Location = { id: "l3", name: "站台", tags: ["月台"] };
    const chs: SceneChapter[] = [
      {
        id: "c1",
        title: "第一章",
        blocks: [{ type: "narration", text: "他们在月台告别" }],
      },
    ];
    const occ = findLocationOccurrences(tagged, chs);
    expect(occ[0].hits).toHaveLength(1);
    expect(occ[0].hits[0].kind).toBe("text");
  });

  it("地点无 imageTag 且无可用名称时返回空数组", () => {
    const empty: Location = { id: "l4", name: "" };
    expect(findLocationOccurrences(empty, chapters)).toEqual([]);
  });

  it("章节无 title 时回退使用 chapterId", () => {
    const chs: SceneChapter[] = [
      {
        id: "c9",
        title: "",
        blocks: [{ type: "scene", image: "bg station" }],
      },
    ];
    const occ = findLocationOccurrences(loc, chs);
    expect(occ[0].chapterTitle).toBe("c9");
  });
});

describe("primaryEvidence：首选证据", () => {
  it("优先 scene 命中，其次首个 text 命中", () => {
    const occ = {
      chapterId: "c1",
      chapterTitle: "第一章",
      hits: [
        { blockIndex: 2, kind: "text" as const, evidence: "a" },
        { blockIndex: 0, kind: "scene" as const, evidence: "b" },
      ],
    };
    expect(primaryEvidence(occ)).toEqual({
      blockIndex: 0,
      kind: "scene",
      evidence: "b",
    });
  });

  it("只有 text 命中时取第一个", () => {
    const occ = {
      chapterId: "c1",
      chapterTitle: "第一章",
      hits: [
        { blockIndex: 1, kind: "text" as const, evidence: "x" },
        { blockIndex: 3, kind: "text" as const, evidence: "y" },
      ],
    };
    expect(primaryEvidence(occ)).toMatchObject({ evidence: "x" });
  });
});

describe("buildPlaceNeedles：高亮针构建", () => {
  it("同名地点去重（保留首个 locationId）", () => {
    const locs: Location[] = [
      { id: "a", name: "车站" },
      { id: "b", name: "车站" },
    ];
    const needles = buildPlaceNeedles(locs);
    expect(needles).toHaveLength(1);
    expect(needles[0]).toEqual({ text: "车站", locationId: "a" });
  });

  it("按文本长度降序排列（长针优先）", () => {
    const locs: Location[] = [
      { id: "a", name: "车站" },
      { id: "c", name: "旧车站", imageTag: "bg station" },
    ];
    const texts = buildPlaceNeedles(locs).map((n) => n.text);
    expect(texts).toEqual(["bg station", "station", "旧车站", "车站"]);
  });

  it("imageTag 的 bg 前缀剥离后单独成针", () => {
    const locs: Location[] = [{ id: "c", name: "X", imageTag: "bg station" }];
    const needles = buildPlaceNeedles(locs);
    expect(needles.map((n) => n.text)).toEqual(["bg station", "station"]);
  });
});

describe("tokenizeScriptLine：地点分词", () => {
  const needles = [
    { text: "旧车站", locationId: "c" },
    { text: "车站", locationId: "a" },
  ];

  it("长针优先匹配，输出交错 text/place 片段", () => {
    const tokens = tokenizeScriptLine("我们到旧车站了，车站见", needles);
    expect(tokens).toEqual([
      { type: "text", value: "我们到" },
      { type: "place", value: "旧车站", locationId: "c" },
      { type: "text", value: "了，" },
      { type: "place", value: "车站", locationId: "a" },
      { type: "text", value: "见" },
    ]);
  });

  it("空行返回空文本 token", () => {
    expect(tokenizeScriptLine("", needles)).toEqual([
      { type: "text", value: "" },
    ]);
  });

  it("无针时整行作为一个 text token", () => {
    expect(tokenizeScriptLine("没有地点", [])).toEqual([
      { type: "text", value: "没有地点" },
    ]);
  });
});

describe("placeTokenAtOffset：偏移命中", () => {
  const needles = [{ text: "旧车站", locationId: "c" }];
  const text = "我们到旧车站了"; // 旧车站 位于 3..6

  it("偏移落在地点内部 → 返回 place token", () => {
    expect(placeTokenAtOffset(text, needles, 4)).toEqual({
      type: "place",
      value: "旧车站",
      locationId: "c",
    });
  });

  it("偏移在地点起始处 → 命中", () => {
    expect(placeTokenAtOffset(text, needles, 3)).toMatchObject({
      type: "place",
      value: "旧车站",
    });
  });

  it("偏移在地点尾部边界（col === next）→ 不命中", () => {
    expect(placeTokenAtOffset(text, needles, 6)).toBeNull();
  });

  it("偏移在文本前部 → null", () => {
    expect(placeTokenAtOffset(text, needles, 0)).toBeNull();
  });

  it("越界偏移被钳制到文本长度后按尾部边界处理 → null", () => {
    expect(placeTokenAtOffset(text, needles, 999)).toBeNull();
    expect(placeTokenAtOffset(text, needles, -5)).toBeNull();
  });

  it("多行文本按行定位偏移", () => {
    const multi = "第一行\n我们到旧车站了";
    expect(placeTokenAtOffset(multi, needles, 4 + 1 + 4)).toEqual({
      type: "place",
      value: "旧车站",
      locationId: "c",
    });
  });
});
