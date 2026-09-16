import { describe, expect, it } from "vitest";
import {
  importToEntries,
  keywordsToText,
  newLoreEntry,
  parseKeywords,
  parseLoreImport,
} from "./loreEntries";

describe("parseKeywords / keywordsToText", () => {
  it("顿号、逗号、空格都能当分隔符，且去重去空", () => {
    expect(parseKeywords("青云、太虚， 掌门 青云")).toEqual(["青云", "太虚", "掌门"]);
    expect(parseKeywords("   ")).toEqual([]);
    expect(keywordsToText(["a", "b"])).toBe("a、b");
    expect(keywordsToText()).toBe("");
  });
});

describe("parseLoreImport", () => {
  it("按 markdown 标题切条目", () => {
    const got = parseLoreImport("# 青云门\n东域正道之首。\n\n## 太虚宗\n专研神魂。");
    expect(got.map((e) => e.title)).toEqual(["青云门", "太虚宗"]);
    expect(got[0].body).toBe("东域正道之首。");
  });

  it("没有标题时按空行分段，首行当标题", () => {
    const got = parseLoreImport("灵脉\n大陆灵气来自九条主灵脉。\n\n影阁\n不收钱只收情报。");
    expect(got.map((e) => e.title)).toEqual(["灵脉", "影阁"]);
    expect(got[1].body).toBe("不收钱只收情报。");
  });

  it("识别「关键词：」行并把它从正文里摘出来", () => {
    const got = parseLoreImport("北境灵脉衰退\n关键词：地气枯了、灵气不够\n近三十年灵气逐年稀薄。");
    expect(got[0].keywords).toEqual(["地气枯了", "灵气不够"]);
    expect(got[0].body).toBe("近三十年灵气逐年稀薄。");
  });

  it("多行正文保持换行，不丢内容", () => {
    const got = parseLoreImport("夺魂案\n第一段。\n第二段。");
    expect(got[0].body).toBe("第一段。\n第二段。");
  });

  it("空输入 / 只有空行 → 没有条目", () => {
    expect(parseLoreImport("")).toEqual([]);
    expect(parseLoreImport("\n\n   \n")).toEqual([]);
  });

  it("【标题】这种写法也认（从 Word 贴过来的常见格式）", () => {
    const got = parseLoreImport("【镜湖禁制】\n水下可见环形纹路。");
    expect(got[0].title).toBe("镜湖禁制");
  });
});

describe("importToEntries", () => {
  it("同名的自动加序号，不覆盖已有条目", () => {
    const existing = [newLoreEntry({ title: "青云门" })];
    const got = importToEntries(
      [
        { title: "青云门", body: "新的", keywords: [] },
        { title: "太虚宗", body: "x", keywords: [] },
      ],
      existing
    );
    expect(got.map((e) => e.title)).toEqual(["青云门 (2)", "太虚宗"]);
  });

  it("生成的 id 互不相同", () => {
    const got = importToEntries([
      { title: "a", body: "", keywords: [] },
      { title: "b", body: "", keywords: [] },
    ]);
    expect(new Set(got.map((e) => e.id)).size).toBe(2);
  });
});

describe("newLoreEntry", () => {
  it("默认字段齐全（缺 keywords 会让后端检索拿不到触发词）", () => {
    const e = newLoreEntry();
    expect(e.id).toBeTruthy();
    expect(e.title).toBe("");
    expect(e.body).toBe("");
    expect(e.keywords).toEqual([]);
  });
});
