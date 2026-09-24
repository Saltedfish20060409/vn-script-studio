import { describe, expect, it } from "vitest";
import { chapterBrief, submissionPreflight, type ChapterBrief } from "./submissionPreflight";

function ch(title: string, words: number, published = false): ChapterBrief {
  return {
    id: title,
    title,
    words,
    hasText: words > 0,
    published,
  };
}

const BASE = {
  title: "钟声与失物招领处",
  genre: "轻小说 / 校园悬疑",
  logline: "转学第三天，我听见了停了三年的大钟。",
};

describe("chapterBrief", () => {
  it("正文优先（有 prose 就不数脚本块）", () => {
    const brief = chapterBrief({
      id: "c1",
      title: "第一章",
      prose: "雨停了。",
      blocks: [{ type: "narration", text: "雨停了。雨停了。雨停了。" }],
    });
    expect(brief.words).toBe(3);
    expect(brief.hasText).toBe(true);
  });

  it("没有正文的空章 hasText=false", () => {
    const brief = chapterBrief({ id: "c2", title: "第二章", prose: "", blocks: [] });
    expect(brief.hasText).toBe(false);
    expect(brief.words).toBe(0);
  });

  it("没有标题时给占位标题（导出文件名不能是空的）", () => {
    expect(chapterBrief({ id: "c3", title: "", prose: "字。" }).title).toBe("（无标题）");
  });
});

describe("submissionPreflight 阻断项", () => {
  it("引号不配对是唯一会破坏阅读的阻断项", () => {
    const r = submissionPreflight({
      ...BASE,
      chapters: [ch("第一章", 3000)],
      quoteUnbalancedCount: 2,
    });
    expect(r.okToSubmit).toBe(false);
    expect(r.blockers).toBe(1);
    expect(r.checks.find((c) => c.id === "quote-unbalanced")?.detail).toContain("吞");
  });

  it("没有任何章节也是阻断项", () => {
    const r = submissionPreflight({ ...BASE, chapters: [] });
    expect(r.okToSubmit).toBe(false);
    expect(r.checks.some((c) => c.id === "no-chapters")).toBe(true);
  });

  it("只是提醒的问题不阻断（空章、重复标题、字数不均都只是 warn）", () => {
    const r = submissionPreflight({
      ...BASE,
      chapters: [ch("第一章", 3000), ch("第一章", 0), ch("第三章", 120)],
    });
    expect(r.blockers).toBe(0);
    expect(r.okToSubmit).toBe(true);
    expect(r.warnings).toBeGreaterThanOrEqual(2);
  });
});

describe("submissionPreflight 提醒项", () => {
  it("空章要逐条列出来", () => {
    const r = submissionPreflight({
      ...BASE,
      chapters: [ch("第一章", 3000), ch("第二章", 0)],
    });
    const empty = r.checks.find((c) => c.id === "empty-chapters");
    expect(empty?.detail).toContain("第二章");
  });

  it("重复标题会被指出来", () => {
    const r = submissionPreflight({
      ...BASE,
      chapters: [ch("第一章", 3000), ch("第一章", 2800)],
    });
    expect(r.checks.find((c) => c.id === "duplicate-titles")?.title).toContain("第一章");
  });

  it("短章按作者自己的单章目标算（没设目标时用 500 字地板）", () => {
    const withGoal = submissionPreflight({
      ...BASE,
      chapters: [ch("第一章", 1200)],
      chapterGoal: 3000,
    });
    expect(withGoal.checks.find((c) => c.id === "short-chapters")?.detail).toContain("3000");

    const noGoal = submissionPreflight({ ...BASE, chapters: [ch("第一章", 1200)] });
    expect(noGoal.checks.some((c) => c.id === "short-chapters")).toBe(false);
  });

  it("元信息没填会提醒（但不阻断：投稿信息页写「未填」而已）", () => {
    const r = submissionPreflight({ title: "只有标题", chapters: [ch("第一章", 3000)] });
    const meta = r.checks.find((c) => c.id === "missing-meta");
    expect(meta?.level).toBe("info");
    expect(meta?.title).toContain("题材");
    expect(meta?.title).toContain("一句话简介");
    expect(r.okToSubmit).toBe(true);
  });

  it("没有标题是 warn（文件名与信息页都会变占位符）", () => {
    const r = submissionPreflight({ title: "  ", chapters: [ch("第一章", 3000)] });
    expect(r.checks.find((c) => c.id === "no-title")?.level).toBe("warn");
  });

  it("有存稿没发只提醒确认范围，不影响导出", () => {
    const r = submissionPreflight({
      ...BASE,
      chapters: [ch("第一章", 3000), ch("第二章", 2800, false)],
    });
    const drafts = r.checks.find((c) => c.id === "unpublished");
    expect(drafts?.detail).toContain("不受发布状态影响");
    expect(r.okToSubmit).toBe(true);
  });

  it("总规模永远给一条（作者要据此核对投稿方要求的字数）", () => {
    const r = submissionPreflight({ ...BASE, chapters: [ch("第一章", 3000), ch("第二章", 2000)] });
    const scale = r.checks.find((c) => c.id === "scale");
    expect(scale?.title).toContain("2 章");
    expect(scale?.detail).toContain("投稿信息页");
    expect(r.totalWords).toBe(5000);
  });

  it("干净的稿子：没有阻断项，只剩规模这一条 info", () => {
    const r = submissionPreflight({
      ...BASE,
      chapters: [
        { id: "c1", title: "第一章", words: 3000, hasText: true, published: true },
        { id: "c2", title: "第二章", words: 3200, hasText: true, published: true },
      ],
      auditErrorCount: 0,
      quoteUnbalancedCount: 0,
    });
    expect(r.blockers).toBe(0);
    expect(r.warnings).toBe(0);
    expect(r.checks.map((c) => c.id)).toEqual(["scale"]);
  });

  it("体检有错误级问题但没细说引号时，给一条 warn 指向体检面板", () => {
    const r = submissionPreflight({
      ...BASE,
      chapters: [ch("第一章", 3000)],
      auditErrorCount: 3,
      quoteUnbalancedCount: 0,
    });
    expect(r.checks.find((c) => c.id === "audit-errors")?.level).toBe("warn");
  });
});
