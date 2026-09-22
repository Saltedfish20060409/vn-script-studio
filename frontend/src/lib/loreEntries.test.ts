import { describe, expect, it } from "vitest";
import {
  draftFromImport,
  draftsToImports,
  importToEntries,
  keywordsToText,
  loreLinkLabel,
  loreLinkOptions,
  newLoreEntry,
  parseKeywords,
  parseLoreImport,
  pruneLoreLinks,
  suggestKeywords,
  toggleKeyword,
  toggleLoreLink,
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

// ---------------------------------------------------------------------------
// 触发词推荐：让作者不必理解「触发词」是什么
// ---------------------------------------------------------------------------

describe("suggestKeywords", () => {
  it("标题本身就是第一个候选（提问最容易直接叫出名字）", () => {
    expect(suggestKeywords("夺魂案")[0]).toBe("夺魂案");
  });

  it("标题去后缀给出简称：青云门 → 青云", () => {
    const got = suggestKeywords("青云门", "东域正道之首。");
    expect(got).toContain("青云门");
    expect(got).toContain("青云");
  });

  it("把正文里书名号 / 引号里的专名也算上", () => {
    const got = suggestKeywords("封印", "封印与《镜湖祭典》有关，源自「百年前之乱」。");
    expect(got).toContain("镜湖祭典");
    expect(got).toContain("百年前之乱");
  });

  it("不推明显不是叫法的词：正文里的普通句子不进候选", () => {
    const got = suggestKeywords("铁律", "任何人不得提及先帝，违者逐出宗门。");
    expect(got).not.toContain("任何人不得提及先帝");
    expect(got.every((k) => k.length <= 12)).toBe(true);
  });

  it("去重、限量、保持优先级顺序", () => {
    const got = suggestKeywords("青云门", "青云门在青云山。青云门掌门玄真。", 3);
    expect(got.length).toBeLessThanOrEqual(3);
    expect(new Set(got).size).toBe(got.length);
    expect(got[0]).toBe("青云门");
  });

  it("只有标题也能给出候选（不依赖正文）", () => {
    expect(suggestKeywords("太虚宗", "")).toEqual(["太虚宗", "太虚"]);
  });

  it("空标题空正文 → 不给噪声", () => {
    expect(suggestKeywords("", "")).toEqual([]);
  });
});

describe("draftFromImport / draftsToImports", () => {
  it("默认勾选，并把解析出的关键词与推荐词合并去重", () => {
    const d = draftFromImport({ title: "青云门", body: "东域正道之首。", keywords: ["掌门"] });
    expect(d.include).toBe(true);
    expect(d.keywords).toContain("掌门");
    expect(d.keywords).toContain("青云门");
    expect(new Set(d.keywords).size).toBe(d.keywords.length);
    expect(d.suggested).toContain("青云");
  });

  it("取消勾选的条目不会被导入", () => {
    const a = draftFromImport({ title: "甲", body: "", keywords: [] });
    const b = { ...draftFromImport({ title: "乙", body: "", keywords: [] }), include: false };
    expect(draftsToImports([a, b]).map((x) => x.title)).toEqual(["甲"]);
  });

  it("标题被改空的不导入（避免出现无名条目）", () => {
    const a = { ...draftFromImport({ title: "甲", body: "", keywords: [] }), title: "   " };
    expect(draftsToImports([a])).toEqual([]);
  });

  it("触发词里的空白项被清掉", () => {
    const d = { ...draftFromImport({ title: "甲", body: "", keywords: [] }), keywords: ["甲", " ", ""] };
    expect(draftsToImports([d])[0].keywords).toEqual(["甲"]);
  });
});

describe("toggleKeyword", () => {
  it("点一下加上，再点一下去掉", () => {
    expect(toggleKeyword(["甲"], "乙")).toEqual(["甲", "乙"]);
    expect(toggleKeyword(["甲", "乙"], "乙")).toEqual(["甲"]);
  });
});

// ---------------------------------------------------------------------------
// 实体链接（条目 → 角色 / 地点 / 章节）
// ---------------------------------------------------------------------------

describe("loreLinkOptions", () => {
  const project = {
    characters: [{ id: "linxia", displayName: "林夏" }],
    locations: [
      { id: "loc1", name: "旧站台" },
      { id: "", name: "坏数据" },
    ],
    chapters: [{ id: "ch1", title: "第一章 站台" }],
  };

  it("把角色/地点/章节都列成可选项，并带分组名", () => {
    const opts = loreLinkOptions(project);
    expect(opts.map((o) => `${o.group}:${o.label}`)).toEqual([
      "角色:林夏",
      "地点:旧站台",
      "章节:第一章 站台",
    ]);
  });

  it("缺 id 的脏数据不会变成选项（否则会关联到不存在的东西）", () => {
    expect(loreLinkOptions(project).some((o) => o.toId === "")).toBe(false);
  });

  it("空项目返回空数组", () => {
    expect(loreLinkOptions({})).toEqual([]);
  });
});

describe("toggleLoreLink / loreLinkLabel / pruneLoreLinks", () => {
  const options = [
    { toType: "character" as const, toId: "linxia", label: "林夏", group: "角色" },
    { toType: "chapter" as const, toId: "ch1", label: "第一章", group: "章节" },
  ];

  it("点一下加上，再点一下去掉", () => {
    const one = toggleLoreLink(undefined, { toType: "character", toId: "linxia" });
    expect(one).toEqual([{ toType: "character", toId: "linxia" }]);
    expect(toggleLoreLink(one, { toType: "character", toId: "linxia" })).toEqual([]);
  });

  it("显示名优先用实体名，找不到就退回 id（不留空白）", () => {
    expect(loreLinkLabel({ toType: "character", toId: "linxia" }, options)).toBe("林夏");
    expect(loreLinkLabel({ toType: "character", toId: "ghost" }, options)).toBe("ghost");
  });

  it("prune 掉指向已删实体的边", () => {
    const links = [
      { toType: "character" as const, toId: "linxia" },
      { toType: "character" as const, toId: "ghost" },
    ];
    expect(pruneLoreLinks(links, options)).toEqual([{ toType: "character", toId: "linxia" }]);
  });
});
