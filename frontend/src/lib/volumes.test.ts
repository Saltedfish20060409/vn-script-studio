import { describe, expect, it } from "vitest";
import type { SceneChapter, Volume } from "../types/vn";
import { countBlocksWords, countChapterWords, countWords, formatWords } from "./wordCount";
import { diffProjectAgainst } from "./projectDiff";
import { normalizeProject } from "./vnLocal";
import {
  LOOSE_VOLUME_ID,
  addVolume,
  assignChapterToVolume,
  buildVolumeRows,
  chaptersInVolume,
  deleteVolume,
  moveVolume,
  normalizeVolumeId,
  renameVolume,
  volumeIdOfChapter,
} from "./volumes";

function chapter(
  id: string,
  title: string,
  opts: { prose?: string; volumeId?: string } = {}
): SceneChapter {
  return {
    id,
    title,
    blocks: [],
    prose: opts.prose ?? "",
    ...(opts.volumeId ? { volumeId: opts.volumeId } : {}),
  };
}

const V1: Volume = { id: "v1", title: "第一卷 春" };
const V2: Volume = { id: "v2", title: "第二卷 夏" };

describe("字数统计：prose 优先（与后端同一规则）", () => {
  it("汉字逐字、拉丁按词", () => {
    expect(countWords("雨落在站台上")).toBe(6);
    expect(countWords("hello world 42")).toBe(3);
    expect(countWords("")).toBe(0);
  });

  it("正文优先", () => {
    expect(countChapterWords(chapter("c1", "一", { prose: "一二三" }))).toBe(3);
  });

  it("正文为空（或只有空白）才回落到脚本 blocks", () => {
    const withBlankProse: SceneChapter = {
      id: "c1",
      title: "一",
      prose: "   \n ",
      blocks: [
        { type: "narration", text: "还是脚本" },
        { type: "dialogue", characterId: "x", text: "对白" },
      ],
    };
    expect(countChapterWords(withBlankProse)).toBe(6);
  });

  it("正文与由它生成的脚本同时存在时不重复计数", () => {
    const ch: SceneChapter = {
      id: "c1",
      title: "一",
      prose: "雨落在站台上。",
      blocks: [{ type: "narration", text: "雨落在站台上。" }],
    };
    expect(countChapterWords(ch)).toBe(6);
  });

  it("菜单选项也算字", () => {
    const blocks = [
      { type: "menu", choices: [{ text: "跟她走" }, { text: "留下来" }] },
    ] as SceneChapter["blocks"];
    expect(countBlocksWords(blocks)).toBe(6);
  });

  it("formatWords 到万就换单位", () => {
    expect(formatWords(999)).toBe("999");
    expect(formatWords(12345)).toBe("1.2万");
    expect(formatWords(123456)).toBe("12万");
  });
});

describe("保存链路：卷不能被静默丢掉（实际踩过的坑）", () => {
  it("normalizeProject 保留 volumes 与 chapter.volumeId", () => {
    const p = normalizeProject({
      id: "p1",
      title: "测试",
      chapters: [{ id: "c1", title: "一", blocks: [], prose: "", volumeId: "v1" }],
      volumes: [{ id: "v1", title: "第一卷" }],
    });
    // 前端 normalizeProject 是白名单式的：漏一个字段，updateActive 之后它就从状态里消失了
    expect(p.volumes).toEqual([{ id: "v1", title: "第一卷" }]);
    expect(p.chapters[0].volumeId).toBe("v1");
  });

  it("diff 认得 volumes 这一节（否则 scoped save 不会把它带上去）", () => {
    const base = normalizeProject({ id: "p1", title: "测试", chapters: [] });
    const next = normalizeProject({
      id: "p1",
      title: "测试",
      chapters: [],
      volumes: [{ id: "v1", title: "第一卷" }],
    });
    const diff = diffProjectAgainst(base, next);
    expect(diff.sections).toContain("volumes");
    expect(diff.hasChanges).toBe(true);
  });
});

describe("卷的分组", () => {
  const chapters = [
    chapter("c1", "一", { volumeId: "v1", prose: "一二三" }),
    chapter("c2", "二", { volumeId: "v1", prose: "四五六七" }),
    chapter("c3", "三", { volumeId: "v2", prose: "八" }),
    chapter("c4", "四", { prose: "九" }),
  ];

  it("按卷分组并算字数", () => {
    const rows = buildVolumeRows([V1, V2], chapters);
    expect(rows.map((r) => r.title)).toEqual(["第一卷 春", "第二卷 夏", "未分卷"]);
    expect(rows[0].chapters.map((c) => c.id)).toEqual(["c1", "c2"]);
    expect(rows[0].words).toBe(7);
    expect(rows[1].words).toBe(1);
    expect(rows[2].chapters.map((c) => c.id)).toEqual(["c4"]);
  });

  it("保留全局序号（章节条显示 01/02… 不因分卷而变）", () => {
    const rows = buildVolumeRows([V1, V2], chapters);
    expect(rows[0].globalIndexes).toEqual([0, 1]);
    expect(rows[1].globalIndexes).toEqual([2]);
    expect(rows[2].globalIndexes).toEqual([3]);
  });

  it("没有未分卷章节时不显示这一行", () => {
    const rows = buildVolumeRows([V1], [chapter("c1", "一", { volumeId: "v1" })]);
    expect(rows.map((r) => r.title)).toEqual(["第一卷 春"]);
  });

  it("没有卷时（老工程）只有一个「未分卷」行，章节条保持平铺", () => {
    const looseOnly = [chapter("c1", "一"), chapter("c2", "二")];
    const rows = buildVolumeRows(undefined, looseOnly);
    expect(rows).toHaveLength(1);
    expect(rows[0].id).toBe(LOOSE_VOLUME_ID);
    expect(rows[0].title).toBe("未分卷");
    expect(rows[0].globalIndexes).toEqual([0, 1]);
    expect(buildVolumeRows(undefined, [])).toEqual([]);
  });

  it("chaptersInVolume / volumeIdOfChapter 认得未分卷", () => {
    expect(chaptersInVolume(chapters, LOOSE_VOLUME_ID).map((c) => c.id)).toEqual(["c4"]);
    expect(volumeIdOfChapter(chapters, "c3")).toBe("v2");
    expect(volumeIdOfChapter(chapters, "c4")).toBe(LOOSE_VOLUME_ID);
    expect(normalizeVolumeId(undefined)).toBe("");
  });
});

describe("卷的增删改", () => {
  it("新建卷：空标题给默认名", () => {
    const { volumes, id } = addVolume([V1], "  ", "v2");
    expect(volumes.map((v) => v.title)).toEqual(["第一卷 春", "第2卷"]);
    expect(id).toBe("v2");
  });

  it("重命名：空白标题不改（避免卷名变空）", () => {
    expect(renameVolume([V1], "v1", "   ")[0].title).toBe("第一卷 春");
    expect(renameVolume([V1], "v1", " 卷一·春 ")[0].title).toBe("卷一·春");
  });

  it("上移/下移：越界不动", () => {
    expect(moveVolume([V1, V2], "v2", -1).map((v) => v.id)).toEqual(["v2", "v1"]);
    expect(moveVolume([V1, V2], "v1", -1).map((v) => v.id)).toEqual(["v1", "v2"]);
    expect(moveVolume([V1, V2], "v2", 1).map((v) => v.id)).toEqual(["v1", "v2"]);
  });

  it("删卷：卷没了，章节回到未分卷（不能留悬空归属）", () => {
    const chapters = [chapter("c1", "一", { volumeId: "v1" }), chapter("c2", "二")];
    const out = deleteVolume([V1, V2], chapters, "v1");
    expect(out.volumes.map((v) => v.id)).toEqual(["v2"]);
    expect(out.chapters[0].volumeId).toBeUndefined();
    expect(volumeIdOfChapter(out.chapters, "c1")).toBe(LOOSE_VOLUME_ID);
  });

  it("章节移入/移出某卷", () => {
    const chapters = [chapter("c1", "一")];
    const moved = assignChapterToVolume(chapters, "c1", "v2");
    expect(moved[0].volumeId).toBe("v2");
    const back = assignChapterToVolume(moved, "c1", LOOSE_VOLUME_ID);
    expect(back[0].volumeId).toBeUndefined();
  });
});
