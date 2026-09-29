import { describe, expect, it } from "vitest";
import type { PlanPreview } from "./agentPlan";
import {
  planForFactsScan,
  planForFinalize,
  planForLedgerDigest,
  planForPipeline,
  planForSettingsIngest,
} from "./agentPlan";

/** 卡片上的全部可见文字拼成一串，方便按关键词断言（UI 渲染的是 title + lines + note）。 */
function flat(p: PlanPreview): string {
  return [p.title, ...p.lines, p.note ?? ""].join("\n");
}

const DIRTY = /undefined|NaN|null/;

/** 表格用：一堆边界输入下都要读得通、都不能出现脏值。 */
const CASES: Array<[string, () => PlanPreview]> = [
  ["写入设定页（无附件）", () => planForSettingsIngest([])],
  [
    "写入设定页（附件缺字数）",
    () =>
      planForSettingsIngest([
        { filename: "草稿.md" },
        { filename: "", chars: Number.NaN },
      ]),
  ],
  [
    "写入设定页（显式空栏）",
    () => planForSettingsIngest([], { bibleSections: [], characterCount: 0 }),
  ],
  ["事实扫描（无附件）", () => planForFactsScan([])],
  [
    "事实扫描（整本 + 附件）",
    () => planForFactsScan([{ filename: "大纲.txt", chars: 3200 }], { full: true }),
  ],
  ["自动写作（空交代）", () => planForPipeline("")],
  [
    "自动写作（关声线 + 0 轮）",
    () => planForPipeline("   ", { voiceCheck: false, maxReviseRounds: 0 }),
  ],
  [
    "自动写作（异常轮次）",
    () => planForPipeline("续写", { maxReviseRounds: Number.NaN }),
  ],
  ["定稿", () => planForFinalize()],
  ["账本入库", () => planForLedgerDigest({ chapterTitle: "  " })],
];

describe("范围：附件与章节", () => {
  it("附件逐条列出文件名与字数", () => {
    const p = planForSettingsIngest([
      { filename: "设定.md", chars: 1200 },
      { filename: "人物小传.txt", chars: 38 },
    ]);
    expect(p.lines).toContain("附件 设定.md（1,200 字）");
    expect(p.lines).toContain("附件 人物小传.txt（38 字）");
  });

  it("附件缺 chars 时只留文件名，不打印 undefined / NaN", () => {
    const p = planForSettingsIngest([
      { filename: "草稿.md" },
      { filename: "异常.md", chars: Number.NaN },
    ]);
    expect(p.lines).toContain("附件 草稿.md");
    expect(p.lines).toContain("附件 异常.md");
    expect(flat(p)).not.toMatch(DIRTY);
  });

  it("没有附件时也读得通（说清只按消息里的资料来）", () => {
    const ingest = planForSettingsIngest([]);
    expect(ingest.lines.some((l) => l.includes("没有附件"))).toBe(true);
    const scan = planForFactsScan([]);
    expect(scan.lines.some((l) => l.includes("没有附件"))).toBe(true);
  });

  it("章名缺失/空白时退回「当前章」，给了就用章名", () => {
    expect(planForPipeline("续写").lines).toContain("目标章节：当前章");
    expect(planForPipeline("续写", { chapterTitle: "   " }).lines).toContain(
      "目标章节：当前章"
    );
    expect(planForPipeline("续写", { chapterTitle: "第三章 雨天" }).lines).toContain(
      "目标章节：第三章 雨天"
    );
    expect(planForFinalize({}).lines).toContain("目标章节：当前章");
    expect(planForFinalize({ chapterTitle: "尾声" }).lines).toContain("目标章节：尾声");
    expect(planForLedgerDigest().lines).toContain("目标章节：当前章");
  });
});

describe("写入设定页", () => {
  it("说出默认那五栏", () => {
    const p = planForSettingsIngest([{ filename: "设定.md", chars: 900 }]);
    const line = p.lines.find((l) => l.includes("设定页")) ?? "";
    for (const s of ["世界观", "背景", "大纲", "主题", "备忘"])
      expect(line).toContain(s);
  });

  it("调用方指定了栏就按指定的说", () => {
    const p = planForSettingsIngest([], { bibleSections: ["世界观", "角色关系"] });
    const line = p.lines.find((l) => l.includes("设定页")) ?? "";
    expect(line).toContain("世界观");
    expect(line).toContain("角色关系");
    expect(line).not.toContain("备忘");
  });

  it("角色卡是目标之一：给了数量说数量，没给就不编数字", () => {
    expect(planForSettingsIngest([], { characterCount: 3 }).lines).toContain(
      "角色卡：涉及 3 个角色"
    );
    const noCount = planForSettingsIngest([]);
    expect(noCount.lines.some((l) => l.startsWith("角色卡："))).toBe(true);
    expect(flat(noCount)).not.toMatch(/\d+ 个角色/);
  });

  it("不承诺结果（没有「会新增 5 条」这类许愿）", () => {
    const p = planForSettingsIngest([{ filename: "设定.md", chars: 900 }], {
      characterCount: 2,
    });
    expect(flat(p)).not.toMatch(/会新增|会写得更|更精彩/);
  });
});

describe("事实扫描：只进待审，不直写关系", () => {
  it("候选去处是待审列表，且要逐条接受才写", () => {
    const p = planForFactsScan([{ filename: "人物.md", chars: 640 }]);
    expect(flat(p)).toContain("待审");
    expect(flat(p)).toContain("接受");
    // 不能出现"直接把关系写进去"这种说法
    expect(flat(p)).not.toMatch(/直接写(入|进)(角色)?关系/);
  });

  it("full 说整本，否则说当前章/章名", () => {
    expect(flat(planForFactsScan([], { full: true }))).toContain("整本");
    expect(flat(planForFactsScan([], {}))).toContain("范围：当前章");
    expect(flat(planForFactsScan([], { chapterTitle: "第一章" }))).toContain(
      "范围：第一章"
    );
  });

  it("有附件时说清它只是临时粘贴源", () => {
    const p = planForFactsScan([{ filename: "聊天记录.txt", chars: 2400 }]);
    expect(flat(p)).toContain("粘贴");
    expect(p.lines).toContain("附件 聊天记录.txt（2,400 字）");
  });
});

describe("自动写作", () => {
  it("四个阶段都说出来", () => {
    const line =
      planForPipeline("写一场告白").lines.find((l) => l.includes("流程")) ?? "";
    for (const s of ["规划", "起草", "检查", "修正"]) expect(line).toContain(s);
  });

  it("轮次预算：默认 2、可改、0 时说清不自动改", () => {
    expect(planForPipeline("续写").lines).toContain("修正上限：最多 2 轮");
    expect(planForPipeline("续写", { maxReviseRounds: 5 }).lines).toContain(
      "修正上限：最多 5 轮"
    );
    expect(flat(planForPipeline("续写", { maxReviseRounds: 0 }))).toContain("0 轮");
  });

  it("声线检查默认开、可以关", () => {
    expect(planForPipeline("续写").lines).toContain("声线检查：开");
    expect(planForPipeline("续写", { voiceCheck: true }).lines).toContain(
      "声线检查：开"
    );
    expect(planForPipeline("续写", { voiceCheck: false }).lines).toContain(
      "声线检查：关"
    );
  });

  it("落章是有条件的：通过才写、不通过就不写", () => {
    const p = planForPipeline("把第二场改成雨夜");
    expect(flat(p)).toContain("写入本章正文");
    expect(flat(p)).toMatch(/不通过就不写|未通过/);
    expect(p.lines.some((l) => l.includes("把第二场改成雨夜"))).toBe(true);
  });

  it("交代很长时压成一行，不把卡片撑爆", () => {
    const p = planForPipeline(
      "请把这一场戏改成雨夜，两个人的对白要更克制一些，结尾留一个钩子"
    );
    const line = p.lines[0] ?? "";
    expect(line.startsWith("你的要求：")).toBe(true);
    expect(line.length).toBeLessThanOrEqual(40);
    expect(line.endsWith("…")).toBe(true);
  });
});

describe("定稿", () => {
  it("说清检查失败就什么都不写", () => {
    const p = planForFinalize({ chapterTitle: "第七章" });
    expect(flat(p)).toContain("检查未通过则什么都不写");
    expect(p.lines.some((l) => l.includes("账本"))).toBe(true);
  });

  it("先检查、通过才写正文并归档账本（顺序在文案里能看出来）", () => {
    const p = planForFinalize();
    const check = p.lines.findIndex((l) => l.includes("自动检查"));
    const write = p.lines.findIndex((l) => l.includes("写入本章正文"));
    expect(check).toBeGreaterThanOrEqual(0);
    expect(write).toBeGreaterThan(check);
  });
});

describe("账本入库", () => {
  it("明说正文不受影响", () => {
    const p = planForLedgerDigest({ chapterTitle: "第九章" });
    expect(flat(p)).toContain("正文不受影响");
    expect(flat(p)).not.toContain("写入本章正文");
    expect(p.lines.some((l) => l.includes("账本"))).toBe(true);
  });
});

describe("统一的确认前提", () => {
  it("每张卡片都写明确认前没写、确认后才写", () => {
    for (const [name, build] of CASES) {
      const note = build().note ?? "";
      expect(`${name}:${note}`).toContain("确认前");
      expect(`${name}:${note}`).toMatch(/不会改动工程|不改动工程/);
      expect(`${name}:${note}`).toContain("确认后");
    }
  });

  it("标题统一带「待确认」，正文没有感叹号、没有 markdown 表格", () => {
    for (const [name, build] of CASES) {
      const p = build();
      expect(`${name}:${p.title}`).toContain("待确认");
      expect(flat(p)).not.toContain("!");
      expect(flat(p)).not.toContain("|");
      expect(flat(p)).not.toContain("！");
    }
  });
});

describe("表格：任何输入都不出 undefined / NaN / null，行都是短句", () => {
  it.each(CASES)("%s", (_name, build) => {
    const p = build();
    expect(p.title.trim().length).toBeGreaterThan(0);
    expect(p.lines.length).toBeGreaterThan(0);
    for (const line of p.lines) {
      expect(line.trim().length).toBeGreaterThan(0);
      expect(line).not.toMatch(DIRTY);
    }
    expect(flat(p)).not.toMatch(DIRTY);
  });

  it("不带附件时每行都在 40 字以内（卡片按项目符号渲染，长了会被截断）", () => {
    const plans = [
      planForSettingsIngest([]),
      planForFactsScan([]),
      planForFactsScan([], { full: true }),
      planForPipeline("续写"),
      planForPipeline("续写", { maxReviseRounds: 0, voiceCheck: false }),
      planForFinalize(),
      planForLedgerDigest(),
    ];
    for (const p of plans) {
      for (const line of p.lines) expect(line.length).toBeLessThanOrEqual(40);
      expect((p.note ?? "").length).toBeLessThanOrEqual(40);
    }
  });
});
