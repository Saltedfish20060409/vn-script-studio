import { describe, expect, it } from "vitest";
import type { SceneChapter } from "../types/vn";
import { chapterWithRecap, insertRecapIntoProse } from "./recap";

const chapter: SceneChapter = {
  id: "c1",
  title: "夏之一",
  blocks: [{ type: "label", id: "start", name: "start" }],
  prose: "他推开门。",
};

describe("前情提要插入正文", () => {
  it("插到开头（卷首回述的常规用法）", () => {
    expect(insertRecapIntoProse("他推开门。", "上卷讲了什么。", "prepend")).toBe(
      "上卷讲了什么。\n\n他推开门。"
    );
  });

  it("插到结尾", () => {
    expect(insertRecapIntoProse("他推开门。", "补记。", "append")).toBe(
      "他推开门。\n\n补记。"
    );
  });

  it("正文为空时直接就是回述", () => {
    expect(insertRecapIntoProse("", "上卷讲了什么。", "prepend")).toBe("上卷讲了什么。");
    expect(insertRecapIntoProse(undefined, "上卷讲了什么。", "append")).toBe("上卷讲了什么。");
    expect(insertRecapIntoProse("   \n ", "上卷讲了什么。", "prepend")).toBe("上卷讲了什么。");
  });

  it("空回述不改正文（避免插进一串空行）", () => {
    expect(insertRecapIntoProse("他推开门。", "   ", "prepend")).toBe("他推开门。");
  });

  it("只动 prose，不碰 blocks（VN 脚本一行都不动）", () => {
    const next = chapterWithRecap(chapter, "上卷讲了什么。");
    expect(next.prose).toBe("上卷讲了什么。\n\n他推开门。");
    expect(next.blocks).toEqual(chapter.blocks);
    expect(next.title).toBe(chapter.title);
    expect(next.id).toBe(chapter.id);
  });
});
