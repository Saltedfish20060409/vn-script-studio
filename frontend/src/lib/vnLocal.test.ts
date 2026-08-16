/**
 * vnLocal 项目归一化单元测试
 *
 * 覆盖 normalizeProject 的字段补齐与默认值、lore/bible.world 镜像、
 * emptyProject 空工程、projectFromPlainText 纯文本导入（空行分段/CRLF）。
 */
import { describe, it, expect } from "vitest";
import type { MapStyleId } from "../types/vn";
import { normalizeProject, emptyProject, projectFromPlainText } from "./vnLocal";

describe("normalizeProject：默认值补齐", () => {
  it("空输入生成完整工程骨架", () => {
    const p = normalizeProject({});
    expect(p.id).toMatch(/^proj-/);
    expect(p.title).toBe("未命名剧本");
    expect(p.characters).toEqual([]);
    expect(p.locations).toEqual([]);
    expect(p.mapStyle).toBe("default");
    expect(p.mapStrokes).toEqual([]);
    expect(p.timeline).toEqual([]);
    expect(p.variables).toEqual([]);
    expect(p.sprites).toEqual([]);
    expect(p.snapshots).toEqual([]);
    expect(p.characterLinks).toEqual([]);
    expect(p.customMapElements).toEqual([]);
    expect(p.locationLinks).toEqual([]);
  });

  it("无章节时生成默认第一章（含 start label）", () => {
    const p = normalizeProject({});
    expect(p.chapters).toHaveLength(1);
    expect(p.chapters[0]).toMatchObject({ id: "ch1", title: "第一章" });
    expect(p.chapters[0].blocks).toEqual([
      { type: "label", id: "start", name: "start" },
    ]);
  });

  it("chapters 为空数组同样回退默认章节", () => {
    const p = normalizeProject({ chapters: [] });
    expect(p.chapters).toHaveLength(1);
    expect(p.chapters[0].id).toBe("ch1");
  });

  it("显式 title / id 被保留", () => {
    const p = normalizeProject({ id: "p9", title: "我的故事" });
    expect(p.id).toBe("p9");
    expect(p.title).toBe("我的故事");
  });

  it("bible 各字段默认空字符串", () => {
    const p = normalizeProject({});
    expect(p.bible).toEqual({
      world: "",
      background: "",
      outline: "",
      themes: "",
      notes: "",
    });
  });

  it("旧字段 lore 镜像到 bible.world 与 lore", () => {
    const p = normalizeProject({ lore: "旧世界观" });
    expect(p.lore).toBe("旧世界观");
    expect(p.bible!.world).toBe("旧世界观");
    expect(p.bible!.background).toBe("");
  });

  it("bible.world 优先于旧字段 lore", () => {
    const p = normalizeProject({ lore: "旧世界观", bible: { world: "新世界观" } });
    expect(p.bible!.world).toBe("新世界观");
    expect(p.lore).toBe("新世界观");
  });

  it("未知 mapStyle 归一化为 default", () => {
    const p = normalizeProject({ mapStyle: "gothic" as MapStyleId });
    expect(p.mapStyle).toBe("default");
  });

  it("传入的 characters / locations 被保留", () => {
    const p = normalizeProject({
      characters: [{ id: "lx", defineName: "linxia", displayName: "林夏" }],
      locations: [{ id: "l1", name: "车站" }],
    });
    expect(p.characters).toHaveLength(1);
    expect(p.characters[0].defineName).toBe("linxia");
    expect(p.locations).toHaveLength(1);
    expect(p.locations![0].name).toBe("车站");
  });

  it("显式章节原样保留", () => {
    const ch = {
      id: "c2",
      title: "终章",
      blocks: [{ type: "narration", text: "结束" } as const],
    };
    const p = normalizeProject({ chapters: [ch] });
    expect(p.chapters).toEqual([ch]);
  });

  it("updatedAt 为可解析的 ISO 字符串", () => {
    const p = normalizeProject({});
    expect(typeof p.updatedAt).toBe("string");
    expect(new Date(p.updatedAt).getTime()).not.toBeNaN();
  });
});

describe("emptyProject：空工程", () => {
  it("按给定标题创建含默认章节的空工程", () => {
    const p = emptyProject("新剧本");
    expect(p.title).toBe("新剧本");
    expect(p.id).toMatch(/^proj-/);
    expect(p.chapters).toHaveLength(1);
    expect(p.chapters[0].blocks[0]).toEqual({
      type: "label",
      id: "start",
      name: "start",
    });
    expect(p.characters).toEqual([]);
  });
});

describe("projectFromPlainText：纯文本导入", () => {
  it("按空行分段生成 narration 块", () => {
    const p = projectFromPlainText("导入", "第一段。\n\n第二段。");
    expect(p.title).toBe("导入");
    const blocks = p.chapters[0].blocks;
    expect(blocks).toHaveLength(3); // start label + 2 段
    expect(blocks[0]).toEqual({ type: "label", id: "start", name: "start" });
    expect(blocks[1]).toEqual({ type: "narration", text: "第一段。" });
    expect(blocks[2]).toEqual({ type: "narration", text: "第二段。" });
  });

  it("单段文本生成一个 narration 块", () => {
    const p = projectFromPlainText("t", "只有一段");
    const blocks = p.chapters[0].blocks;
    expect(blocks).toHaveLength(2);
    expect(blocks[1]).toEqual({ type: "narration", text: "只有一段" });
  });

  it("空文本生成单个空 narration 块", () => {
    const p = projectFromPlainText("t", "");
    const blocks = p.chapters[0].blocks;
    expect(blocks).toHaveLength(2);
    expect(blocks[1]).toEqual({ type: "narration", text: "" });
  });

  it("CRLF 与 LF 分段结果一致", () => {
    const crlf = projectFromPlainText("t", "A\r\n\r\nB");
    const lf = projectFromPlainText("t", "A\n\nB");
    expect(crlf.chapters[0].blocks).toEqual(lf.chapters[0].blocks);
  });

  it("导入结果仍经过 normalize（含默认 mapStyle）", () => {
    const p = projectFromPlainText("t", "A");
    expect(p.mapStyle).toBe("default");
    expect(p.id).toMatch(/^proj-/);
  });
});
