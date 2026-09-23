import { describe, expect, it } from "vitest";
import { copyForProject, genreOptions, resolveGenre } from "./genreCopy";

describe("resolveGenre 推断", () => {
  it("轻小说题材 → novel", () => {
    expect(resolveGenre({ genre: "轻小说 / 校园悬疑" })).toBe("novel");
  });

  it("网文 / 文学 / 小说类关键词 → novel", () => {
    for (const genre of ["网文", "都市异能小说", "网络文学", "长篇小说", "短篇集"]) {
      expect(resolveGenre({ genre }), genre).toBe("novel");
    }
  });

  it("视觉小说类题材保持 vn（默认不能变）", () => {
    for (const genre of ["日常 / 青春", "悬疑 / 都市", "视觉小说", ""]) {
      expect(resolveGenre({ genre }), genre).toBe("vn");
    }
  });

  it("「视觉小说」不会被「小说」两个字带偏（这句是第一版真实的误判）", () => {
    for (const genre of ["视觉小说", "视觉小说 / 恋爱", "文字冒险", "Galgame", "ADV"]) {
      expect(resolveGenre({ genre }), genre).toBe("vn");
    }
  });

  it("空工程 / 缺字段 → vn（老工程不受影响）", () => {
    expect(resolveGenre(null)).toBe("vn");
    expect(resolveGenre({})).toBe("vn");
    expect(resolveGenre({ genre: null })).toBe("vn");
  });

  it("显式选择优先于题材关键词", () => {
    expect(resolveGenre({ genre: "轻小说", writingGenre: "vn" })).toBe("vn");
    expect(resolveGenre({ genre: "日常 / 青春", writingGenre: "novel" })).toBe("novel");
  });

  it("显式值是 auto / 乱填 → 回到按题材推断", () => {
    expect(resolveGenre({ genre: "轻小说", writingGenre: "auto" })).toBe("novel");
    expect(resolveGenre({ genre: "轻小说", writingGenre: "whatever" })).toBe("novel");
  });

  it("大小写与空格无关", () => {
    expect(resolveGenre({ genre: " N O V E L 轻小说 " })).toBe("novel");
    expect(resolveGenre({ genre: "轻 小 说" })).toBe("novel");
    expect(resolveGenre({ genre: "轻小说", writingGenre: " NOVEL " })).toBe("novel");
  });
});

describe("copyForProject 用词", () => {
  it("小说作品用「正文 / 分卷 / 投稿」这套词", () => {
    const c = copyForProject({ genre: "轻小说 / 校园悬疑" });
    expect(c.work).toBe("小说");
    expect(c.writeTab).toBe("正文");
    expect(c.proseMode).toBe("正文");
    expect(c.library).toBe("作品库");
    expect(c.untitled).toBe("未命名作品");
    expect(c.appendScript).toBe("追加正文");
  });

  it("视觉小说作品保持原词（剧本 / 剧本库 / 未命名剧本）", () => {
    const c = copyForProject({ genre: "日常 / 青春" });
    expect(c.work).toBe("剧本");
    expect(c.writeTab).toBe("剧本");
    expect(c.library).toBe("剧本库");
    expect(c.untitled).toBe("未命名剧本");
    expect(c.appendScript).toBe("追加剧本");
  });

  it("两套词里没有空值，且关键字段确实不同（否则等于没切）", () => {
    const vn = copyForProject(null);
    const novel = copyForProject({ genre: "轻小说" });
    for (const c of [vn, novel]) {
      for (const [key, value] of Object.entries(c)) {
        expect(typeof value, `${c.genre}.${key}`).toBe("string");
        expect(String(value).trim().length, `${c.genre}.${key}`).toBeGreaterThan(0);
      }
    }
    expect(vn.writeTab).not.toBe(novel.writeTab);
    expect(vn.library).not.toBe(novel.library);
    expect(vn.appendScript).not.toBe(novel.appendScript);
  });

  it("小说那套词里不出现 VN 专有词（术语切换的意义就在这里）", () => {
    const novel = copyForProject({ genre: "轻小说" });
    const text = Object.values(novel).join("\n").toLowerCase();
    for (const jargon of ["ren'py", "renpy", "rpy", "menu", "label", "试玩", "立绘"]) {
      expect(text.includes(jargon), jargon).toBe(false);
    }
  });
});

describe("genreOptions", () => {
  it("给出三个选项，自动项写清楚会猜成什么", () => {
    const opts = genreOptions({ genre: "轻小说" });
    expect(opts.map((o) => o.value)).toEqual(["auto", "vn", "novel"]);
    expect(opts[0].hint).toContain("轻小说 / 网文");
  });

  it("没有小说关键词时，自动项说明会猜成视觉小说", () => {
    expect(genreOptions({ genre: "日常" })[0].hint).toContain("视觉小说");
  });

  it("每个选项都有 label 与 hint（设定页要能直接渲染）", () => {
    for (const o of genreOptions(null)) {
      expect(o.label.trim().length).toBeGreaterThan(0);
      expect(o.hint.trim().length).toBeGreaterThan(0);
    }
  });
});
