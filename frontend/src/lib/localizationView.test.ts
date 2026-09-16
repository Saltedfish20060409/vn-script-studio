import { describe, expect, it, vi } from "vitest";
import type { LocalizationEntry } from "../api/projects";
import {
  AUTO_L10N_MAX_CALLS,
  autoTranslateMessage,
  estimateTranslate,
  groupByChapter,
  hasUntranslated,
  humanTokens,
  nextUntranslated,
  progressFor,
  runAutoTranslate,
} from "./localizationView";

function entry(over: Partial<LocalizationEntry>): LocalizationEntry {
  return {
    key: "k",
    chapterId: "ch1",
    kind: "dialogue",
    source: "原文",
    sourceHash: "h",
    targets: {},
    status: {},
    ...over,
  };
}

const ENTRIES: LocalizationEntry[] = [
  entry({ key: "ch1#0", chapterId: "ch1", targets: { en: "Hello" } }),
  entry({ key: "ch1#1", chapterId: "ch1", targets: {} }),
  entry({ key: "ch2#0", chapterId: "ch2", targets: { en: "Bye" } }),
];

describe("progressFor", () => {
  it("统计已填数量与百分比（空白不算已翻）", () => {
    expect(progressFor(ENTRIES, "en")).toEqual({ done: 2, total: 3, pct: 67 });
    expect(progressFor([entry({ targets: { en: "   " } })], "en")).toEqual({
      done: 0,
      total: 1,
      pct: 0,
    });
    expect(progressFor([], "en")).toEqual({ done: 0, total: 0, pct: 0 });
  });
});

describe("groupByChapter", () => {
  it("按剧本章节顺序分组，并用章节标题而不是内部 id", () => {
    const groups = groupByChapter(ENTRIES, [
      { id: "ch2", title: "第二章" },
      { id: "ch1", title: "第一章" },
    ], "en");
    expect(groups.map((g) => g.title)).toEqual(["第二章", "第一章"]);
    expect(groups[0].total).toBe(1);
    expect(groups[1].translated).toBe(1);
  });

  it("章节没有标题时退回 id，不显示空标题", () => {
    const groups = groupByChapter([entry({ chapterId: "chX" })], [{ id: "chX" }], "en");
    expect(groups[0].title).toBe("chX");
  });

  it("条目指向已不存在的章节时放到最后，不丢条目", () => {
    const groups = groupByChapter(
      [entry({ key: "ghost", chapterId: "gone" })],
      [{ id: "ch1", title: "第一章" }],
      "en"
    );
    expect(groups.map((g) => g.chapterId)).toEqual(["gone"]);
    expect(groups[0].total).toBe(1);
  });
});

describe("nextUntranslated / hasUntranslated", () => {
  it("给出第一条未翻的条目", () => {
    expect(nextUntranslated(ENTRIES, "en")?.key).toBe("ch1#1");
    expect(nextUntranslated(ENTRIES, "ja")?.key).toBe("ch1#0");
  });

  it("全部翻完返回 null", () => {
    const all = ENTRIES.map((e) => ({ ...e, targets: { en: "x" } }));
    expect(nextUntranslated(all, "en")).toBeNull();
    expect(hasUntranslated(all, "en")).toBe(false);
  });
});

describe("runAutoTranslate", () => {
  it("一轮轮翻到没有剩余", async () => {
    let remaining = 60;
    const seen: number[] = [];
    const r = await runAutoTranslate({
      remaining,
      translateOnce: async () => {
        const applied = Math.min(25, remaining);
        remaining -= applied;
        return { applied, remaining };
      },
      onProgress: (p) => seen.push(p.remaining),
    });
    expect(r.stop).toBe("done");
    expect(r.calls).toBe(3);
    expect(r.applied).toBe(60);
    expect(r.remaining).toBe(0);
    expect(r.progressPct).toBe(100);
    expect(seen[seen.length - 1]).toBe(0);
  });

  it("没有待翻句子时一次请求都不发", async () => {
    const translateOnce = vi.fn();
    const r = await runAutoTranslate({ remaining: 0, translateOnce });
    expect(r.stop).toBe("done");
    expect(r.calls).toBe(0);
    expect(translateOnce).not.toHaveBeenCalled();
  });

  it("撞到 maxCalls 就停下，不会无限翻", async () => {
    let remaining = 100000;
    const r = await runAutoTranslate({
      remaining,
      maxCalls: 3,
      translateOnce: async () => {
        remaining -= 25;
        return { applied: 25, remaining };
      },
    });
    expect(r.stop).toBe("limit");
    expect(r.calls).toBe(3);
    expect(r.remaining).toBe(100000 - 75);
  });

  it("模型连着两轮没产出就停下（否则会一直转圈烧额度）", async () => {
    const translateOnce = vi.fn(async () => ({ applied: 0, remaining: 40 }));
    const r = await runAutoTranslate({ remaining: 40, translateOnce });
    expect(r.stop).toBe("stalled");
    expect(translateOnce).toHaveBeenCalledTimes(2);
  });

  it("中途失败时保留已经翻好的进度并带上原因", async () => {
    let remaining = 100;
    const r = await runAutoTranslate({
      remaining,
      translateOnce: async () => {
        if (remaining <= 50) throw new Error("翻译请求过于频繁");
        remaining -= 50;
        return { applied: 50, remaining };
      },
    });
    expect(r.stop).toBe("error");
    expect(r.applied).toBe(50);
    expect(r.remaining).toBe(50);
    expect(r.error).toBeInstanceOf(Error);
    expect(autoTranslateMessage(r)).toContain("翻译请求过于频繁");
  });

  it("用户可以随时叫停", async () => {
    let stop = false;
    let remaining = 100;
    const r = await runAutoTranslate({
      remaining,
      shouldStop: () => stop,
      translateOnce: async () => {
        remaining -= 25;
        stop = true;
        return { applied: 25, remaining };
      },
    });
    expect(r.stop).toBe("cancelled");
    expect(r.calls).toBe(1);
    expect(autoTranslateMessage(r)).toContain("还剩 75 句");
  });

  it("默认上限与后端限流（60 次/小时）留出余量", () => {
    expect(AUTO_L10N_MAX_CALLS).toBeLessThan(60);
    expect(AUTO_L10N_MAX_CALLS).toBeGreaterThan(0);
  });

  it("提示语把「全翻完」和「还需要继续」分清楚，并带上真实 token 消耗", () => {
    const done = autoTranslateMessage({
      calls: 2,
      applied: 30,
      remaining: 0,
      startedWith: 30,
      tokens: 3510,
      stop: "done",
      progressPct: 100,
    });
    expect(done).toContain("已经全部有译文");
    expect(done).toContain("3510 token");
    const limited = autoTranslateMessage({
      calls: AUTO_L10N_MAX_CALLS,
      applied: 1000,
      remaining: 13016,
      startedWith: 14016,
      tokens: 1_050_000,
      stop: "limit",
      progressPct: 7,
    });
    expect(limited).toContain("还剩 13016 句");
    expect(limited).toContain("105.0 万 token");
  });
});

describe("estimateTranslate / humanTokens", () => {
  it("按未翻句子的字数估算请求数与 token", () => {
    const entries = [
      entry({ key: "a", source: "一二三四五", targets: {} }),
      entry({ key: "b", source: "六七八九十", targets: {} }),
      entry({ key: "c", source: "已翻", targets: { en: "done" } }),
    ];
    const est = estimateTranslate(entries, "en");
    expect(est.sentences).toBe(2);
    expect(est.chars).toBe(10);
    expect(est.calls).toBe(1);
    // 2.95 token/字（输入 1.7 + 输出 1.25），与线上实测一致
    expect(est.totalTokens).toBe(30);
    expect(est.inputTokens).toBe(17);
    expect(est.outputTokens).toBe(13);
  });

  it("每轮句数决定请求次数（14016 句 / 每轮 50 句 = 281 次）", () => {
    const many = Array.from({ length: 14016 }, (_, i) =>
      entry({ key: `k${i}`, source: "二十七个字的一句旁白文本啊", targets: {} })
    );
    const est = estimateTranslate(many, "en");
    expect(est.sentences).toBe(14016);
    expect(est.calls).toBe(281);
  });

  it("全部翻完时估算是 0，不显示没用的数字", () => {
    const est = estimateTranslate([entry({ targets: { en: "x" } })], "en");
    expect(est).toMatchObject({ sentences: 0, chars: 0, calls: 0, totalTokens: 0 });
  });

  it("token 数量按万/千万收敛，别让用户数零", () => {
    expect(humanTokens(0)).toBe("0");
    expect(humanTokens(9999)).toBe("9999");
    expect(humanTokens(10_000)).toBe("1.0 万");
    expect(humanTokens(1_050_000)).toBe("105.0 万");
    expect(humanTokens(20_000_000)).toBe("2.0 千万");
  });
});
