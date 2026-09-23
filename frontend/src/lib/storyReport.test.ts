import { describe, expect, it } from "vitest";
import type { AdaptivePlanOut, StoryMetricsOut } from "../api/projects";
import {
  ADAPTIVE_EXPORT_NOTE,
  adaptiveCandidateRows,
  arcDirection,
  arcDirectionText,
  counterRef,
  declaredMismatchGroups,
  declaredMismatchRows,
  declaredMismatchSummary,
  EMOTION_INFERENCE_NOTE,
  emotionArcRows,
  emotionBreakRows,
  emotionChapterRows,
  foreshadowView,
  openHookRows,
  preludeView,
  recipeRows,
  summarizeAdaptivePlan,
  summarizeStoryMetrics,
  tendencyCounterRows,
} from "./storyReport";

/** 视图里绝不能出现的东西：NaN / undefined 被当成文案渲染出去。 */
function expectNoBadTokens(view: unknown) {
  const text = JSON.stringify(view);
  expect(text).not.toContain("NaN");
  expect(text).not.toContain("undefined");
  expect(text).not.toContain(":null");
}

/** 有些视图里 null 是**语义**（例如"还没有伏笔"时的 percent），只查 NaN / undefined。 */
function expectNoNaN(view: unknown) {
  const text = JSON.stringify(view);
  expect(text).not.toContain("NaN");
  expect(text).not.toContain("undefined");
}

describe("伏笔回收率（null 不是 0%）", () => {
  it("resolutionRate 为 null 时说「还没有记录任何伏笔」，绝不显示 0%", () => {
    const view = foreshadowView({
      foreshadow: { total: 0, paid: 0, open: 0, resolutionRate: null, chapters: 3 },
    });
    expect(view.hasRate).toBe(false);
    expect(view.percent).toBeNull();
    expect(view.headline).toContain("还没有记录任何伏笔");
    expect(view.headline).not.toContain("0%");
    expect(view.headline).not.toContain("回收率");
    expect(view.detail).toContain("不等于回收率 0%");
    expect(view.tone).toBe("muted");
    expect(view.notes).toEqual([]);
    expectNoNaN(view);
  });

  it("有伏笔时给百分比 + 已回收 N/M + 最老的钩子挂了多久", () => {
    const view = foreshadowView({
      foreshadow: {
        total: 5,
        paid: 2,
        open: 3,
        resolutionRate: 0.4,
        chapters: 12,
        oldestOpenChapters: 9,
      },
    });
    expect(view.hasRate).toBe(true);
    expect(view.percent).toBe(40);
    expect(view.headline).toBe("伏笔回收率 40%：已回收 2/5");
    expect(view.detail).toContain("还有 3 条没回收");
    expect(view.detail).toContain("最老的一条埋了 9 章还没收");
    expect(view.detail).toContain("全书 12 章");
    expect(view.tone).toBe("watch");
    expectNoNaN(view);
  });

  it("回收率过半就是「没问题」那一档（与后端 findings 的 0.5 门槛同口径）", () => {
    const view = foreshadowView({
      foreshadow: {
        total: 4,
        paid: 3,
        open: 1,
        resolutionRate: 0.75,
        oldestOpenChapters: 2,
      },
    });
    expect(view.percent).toBe(75);
    expect(view.tone).toBe("ok");
  });

  it("total 为 0 但后端给了回收率（字段对不上）时如实说明，仍按「还没有伏笔」显示", () => {
    const view = foreshadowView({ foreshadow: { total: 0, resolutionRate: 0.5 } });
    expect(view.hasRate).toBe(false);
    expect(view.percent).toBeNull();
    expect(view.notes.join("")).toContain("对不上");
    expectNoNaN(view);
  });

  it("后端没给 resolutionRate 时按 paid/total 现算，并说明是现算的", () => {
    const view = foreshadowView({ foreshadow: { total: 4, paid: 1, open: 3 } });
    expect(view.percent).toBe(25);
    expect(view.notes.join("")).toContain("没有给出 resolutionRate");
    expect(view.notes.join("")).toContain("现算");
  });

  it("回收率与 paid/total 对不上时以回传值为准并说明", () => {
    const view = foreshadowView({
      foreshadow: { total: 10, paid: 5, open: 5, resolutionRate: 0.9 },
    });
    expect(view.percent).toBe(90);
    expect(view.notes.join("")).toContain("界面显示后端给的那个数");
  });

  it("回收率超出 0–1 时夹住显示并说明", () => {
    const view = foreshadowView({
      foreshadow: { total: 2, paid: 2, open: 0, resolutionRate: 1.4 },
    });
    expect(view.percent).toBe(100);
    expect(view.notes.join("")).toContain("不在 0–1 之间");
    expectNoNaN(view);
  });

  it("整个字段缺失 / 类型异常都不抛，也不显示 NaN", () => {
    expect(foreshadowView(null).hasRate).toBe(false);
    expect(foreshadowView({}).headline).toContain("还没有记录任何伏笔");
    const broken = foreshadowView({
      foreshadow: {
        total: "5",
        paid: Number.NaN,
        open: null,
        resolutionRate: "0.5",
      } as never,
    });
    expect(broken.hasRate).toBe(false);
    expect(broken.total).toBe(0);
    expectNoNaN(broken);
  });
});

describe("未回收钩子列表", () => {
  const input = {
    foreshadow: {
      openHooks: [
        {
          hook: "旧照片上的人",
          plantedChapter: "ch5",
          plantedChapterTitle: "第五章",
          chaptersOpen: 4,
        },
        {
          hook: "红伞的来历",
          plantedChapter: "ch2",
          plantedChapterTitle: "第二章",
          chaptersOpen: 9,
        },
        { hook: "", plantedChapter: "ch9", plantedChapterTitle: "", chaptersOpen: 1 },
      ],
    },
  };

  it("按章龄降序，带 hook 文案 + 埋点章 + 挂了多久", () => {
    const rows = openHookRows(input);
    expect(rows.map((r) => r.chaptersOpen)).toEqual([9, 4, 1]);
    expect(rows[0].hook).toBe("红伞的来历");
    expect(rows[0].chapter).toBe("第二章");
    expect(rows[0].ageText).toContain("已经挂了 9 章");
  });

  it("章节标题缺失时退回 chapterId；hook 文案缺失时不留空白", () => {
    const rows = openHookRows(input, { ch9: "第九章 空抽屉" });
    const last = rows[2];
    expect(last.hook).toBe("（未命名的伏笔）");
    expect(last.chapter).toBe("第九章 空抽屉");
    expectNoBadTokens(rows);
  });

  it("章龄为 0 的钩子说的是「还没跨过整章」，不是「挂了 0 章」", () => {
    const rows = openHookRows({
      foreshadow: { openHooks: [{ hook: "刚埋的", chaptersOpen: 0 }] },
    });
    expect(rows[0].chaptersOpen).toBe(0);
    expect(rows[0].ageText).toContain("还没跨过整章");
    expect(rows[0].chapter).toBe("");
  });

  it("章龄相同时按章节稳定排序；空输入返回空数组", () => {
    const rows = openHookRows({
      foreshadow: {
        openHooks: [
          { hook: "b", plantedChapter: "ch9", chaptersOpen: 3 },
          { hook: "a", plantedChapter: "ch1", chaptersOpen: 3 },
        ],
      },
    });
    expect(rows.map((r) => r.plantedChapter)).toEqual(["ch1", "ch9"]);
    expect(openHookRows(null)).toEqual([]);
    expect(openHookRows({ foreshadow: { openHooks: null } })).toEqual([]);
  });
});

describe("情感弧线（逐角色）", () => {
  const input = {
    emotionArcs: {
      characters: [
        { character: "凛", start: "低落", end: "激动", delta: 5 },
        { character: "澪", start: "平静", end: "平静", delta: 0 },
      ],
      flatArcs: [{ character: "澪", start: "平静", end: "平静", delta: 0 }],
    },
  };

  it("每个角色都给出「从哪儿走到哪儿」+ 刻度差", () => {
    const rows = emotionArcRows(input);
    expect(rows[0].character).toBe("凛");
    expect(rows[0].text).toBe("从「低落」走到「激动」（往上走 5 格）");
    expect(rows[0].flat).toBe(false);
    expect(rows[0].flatNote).toBe("");
  });

  it("flatArcs 里的角色标成「平」，并给出为什么值得看一眼", () => {
    const rows = emotionArcRows(input);
    const flat = rows[1];
    expect(flat.flat).toBe(true);
    expect(flat.text).toBe("全篇都停在「平静」");
    expect(flat.flatNote).toContain("值得看一眼");
  });

  it("只出现在 flatArcs 里的角色也会出成一行（不静默丢掉）", () => {
    const rows = emotionArcRows({
      emotionArcs: {
        characters: [],
        flatArcs: [{ character: "透", start: "平静", end: "平静", delta: 0 }],
      },
    });
    expect(rows.map((r) => r.character)).toEqual(["透"]);
    expect(rows[0].flat).toBe(true);
  });

  it("情绪词缺失时说「没推断出来」，不留空白；方向判定覆盖上下与没动", () => {
    const rows = emotionArcRows({ emotionArcs: { characters: [{ character: "凛" }] } });
    expect(rows[0].from).toBe("（没推断出情绪）");
    expect(arcDirection(3)).toBe("up");
    expect(arcDirection(-3)).toBe("down");
    expect(arcDirection(0)).toBe("flat");
    expect(arcDirection(Number.NaN)).toBe("flat");
    expect(arcDirectionText(-2)).toBe("往下走");
    expectNoBadTokens(rows);
  });

  it("空输入不抛异常", () => {
    expect(emotionArcRows(null)).toEqual([]);
    expect(emotionArcRows({})).toEqual([]);
  });
});

describe("逐章情绪走向与断裂", () => {
  const input = {
    emotionArcBreaks: {
      rows: [
        {
          characterId: "c1",
          character: "凛",
          chapterId: "ch4",
          chapterTitle: "第四章 骤雨",
          chapterIndex: 3,
          start: "激动",
          end: "平静",
          delta: -4,
          lines: 12,
          evidence: ["我说了别管我。", "算了。"],
        },
        {
          characterId: "c1",
          character: "凛",
          chapterId: "ch2",
          chapterTitle: "第二章 雨夜",
          chapterIndex: 1,
          start: "低落",
          end: "担忧",
          delta: 2,
          lines: 9,
          evidence: [],
        },
      ],
      breaks: [
        {
          character: "凛",
          chapterId: "ch4",
          chapterTitle: "第四章 骤雨",
          issue: "emotion_arc_break",
          overallDelta: 5,
          chapterDelta: -4,
          actual: "激动 → 平静",
          message:
            "「凛」全篇情绪是往上走的，但在第四章 骤雨 这一章却从 激动 掉到 平静",
        },
      ],
    },
  };

  it("逐章行带上章节标题、句数与证据句（没有证据句时如实说明）", () => {
    const rows = emotionChapterRows(input);
    const ch4 = rows.find((r) => r.chapterId === "ch4");
    expect(ch4?.chapter).toBe("第四章 骤雨");
    expect(ch4?.lines).toBe(12);
    expect(ch4?.text).toBe("激动 → 平静（往下走 4 格）");
    expect(ch4?.evidenceText).toContain("我说了别管我。");
    const ch2 = rows.find((r) => r.chapterId === "ch2");
    expect(ch2?.evidenceText).toContain("没有给出证据句");
  });

  it("与全篇走向相反的那一章排在最前面并被标成断裂", () => {
    const rows = emotionChapterRows(input);
    expect(rows[0].chapterId).toBe("ch4");
    expect(rows[0].broken).toBe(true);
    expect(rows[1].broken).toBe(false);
  });

  it("章节标题缺失时退回 chapterId / 传入的标题表", () => {
    const rows = emotionChapterRows(
      { emotionArcBreaks: { rows: [{ character: "凛", chapterId: "ch7", delta: 3 }] } },
      { ch7: "第七章 回声" }
    );
    expect(rows[0].chapter).toBe("第七章 回声");
    const noTitle = emotionChapterRows({
      emotionArcBreaks: { rows: [{ character: "凛", chapterId: "ch7", delta: 3 }] },
    });
    expect(noTitle[0].chapter).toBe("ch7");
    expectNoBadTokens(noTitle);
  });

  it("断裂行并排给出全篇与这一章的走向（必须能看出是哪一章）", () => {
    const rows = emotionBreakRows(input);
    expect(rows).toHaveLength(1);
    expect(rows[0].chapter).toBe("第四章 骤雨");
    expect(rows[0].comparison).toContain("全篇「往上走」");
    expect(rows[0].comparison).toContain("第四章 骤雨 这一章却是「往下走」");
    expect(rows[0].comparison).toContain("激动 → 平静");
    expect(rows[0].message).toContain("往上走");
  });

  it("章节未知 / actual 缺失时不留空白", () => {
    const rows = emotionBreakRows({
      emotionArcBreaks: {
        breaks: [{ character: "澪", overallDelta: 3, chapterDelta: -3 }],
      },
    });
    expect(rows[0].chapter).toBe("");
    expect(rows[0].comparison).toContain("（章节未知）");
    expect(rows[0].actual).not.toBe("");
    expectNoBadTokens(rows);
  });

  it("空输入返回空数组", () => {
    expect(emotionChapterRows(null)).toEqual([]);
    expect(emotionBreakRows(undefined)).toEqual([]);
  });
});

describe("与节拍表声明的对账（单独一段，区分两类不一致）", () => {
  const input = {
    declaredArcMismatches: [
      {
        character: "凛",
        issue: "arc_reversed",
        declared: "平静 → 激动",
        actual: "激动 → 平静",
        message: "实际却是反的",
      },
      {
        character: "澪",
        issue: "arc_flat",
        declared: "平静 → 愉悦",
        actual: "平静 → 平静",
        message: "弧线可能没写出来",
      },
      { character: "透", issue: "brand_new", declared: "", actual: "", message: "" },
    ],
  };

  it("arc_flat 与 arc_reversed 各有自己的中文说法与处理建议", () => {
    const rows = declaredMismatchRows(input);
    const reversed = rows.find((r) => r.issue === "arc_reversed");
    const flat = rows.find((r) => r.issue === "arc_flat");
    expect(reversed?.issueLabel).toBe("方向和声明相反");
    expect(reversed?.hint).toContain("有意");
    expect(flat?.issueLabel).toBe("声明有变化、实际没变");
    expect(flat?.hint).toContain("推断");
    expect(reversed?.declared).toBe("平静 → 激动");
    expect(reversed?.actual).toBe("激动 → 平静");
  });

  it("未知类别归到「其它」并保留后端原话（不静默丢掉）", () => {
    const rows = declaredMismatchRows(input);
    const other = rows.find((r) => r.issue === "other");
    expect(other?.issueLabel).toBe("其它对账不一致");
    expect(other?.declared).toBe("（后端没给声明值）");
    expect(other?.message).toBe("与节拍表声明不一致。");
    expectNoBadTokens(rows);
  });

  it("分组顺序是「方向相反」优先，空组不出现", () => {
    const groups = declaredMismatchGroups(input);
    expect(groups.map((g) => g.issue)).toEqual(["arc_reversed", "arc_flat", "other"]);
    expect(groups[0].rows).toHaveLength(1);
    expect(declaredMismatchGroups({ declaredArcMismatches: [] })).toEqual([]);
    expect(declaredMismatchGroups(null)).toEqual([]);
  });

  it("总述点名各类各有几处；没有对账时说「一致」而不是「没发现问题」", () => {
    expect(declaredMismatchSummary(input)).toBe(
      "与节拍表声明对不上 3 处：1 处方向和声明相反、1 处声明有变化、实际没变、1 处其它对账不一致。"
    );
    expect(declaredMismatchSummary(null)).toContain("一致");
  });
});

describe("自适应：计数器清单与条件示例", () => {
  it("变量 key → persistent 引用（前缀不能省，否则存档之间各自独立）", () => {
    const rows = tendencyCounterRows({
      courage: "reader_tendency_courage",
      affection: "reader_tendency_affection",
    });
    expect(rows.map((r) => r.variableKey)).toEqual(["affection", "courage"]);
    expect(rows[0].ref).toBe("persistent.reader_tendency_affection");
    expect(rows[0].note).toContain("跨存档");
  });

  it("计数器名缺失 / 已带前缀 / 空对象都不出现空引用", () => {
    expect(counterRef("reader_tendency_x")).toBe("persistent.reader_tendency_x");
    expect(counterRef("persistent.reader_tendency_x")).toBe(
      "persistent.reader_tendency_x"
    );
    expect(counterRef("")).toBe("");
    const rows = tendencyCounterRows({ affection: "" });
    expect(rows[0].ref).toBe("");
    expect(rows[0].note).toContain("没给计数器名");
    expect(tendencyCounterRows(null)).toEqual([]);
    expect(tendencyCounterRows({ "": "reader_tendency_x" })).toEqual([]);
  });

  it("condition 原样给出（可直接照抄），并附上用法提示", () => {
    const rows = recipeRows({
      recipes: [
        {
          variableKey: "affection",
          counter: "persistent.reader_tendency_affection",
          condition: "persistent.reader_tendency_affection >= 3",
          meaning: "这个读者至少 3 次把好感往上涨。",
        },
      ],
    });
    expect(rows[0].condition).toBe("persistent.reader_tendency_affection >= 3");
    expect(rows[0].derived).toBe(false);
    expect(rows[0].note).toContain("粘进选项");
    expect(rows[0].meaning).toContain("3 次");
  });

  it("后端没给 condition 时按计数器 + 门槛现拼，并说明是现拼的", () => {
    const rows = recipeRows(
      {
        recipes: [
          { variableKey: "courage", counter: "persistent.reader_tendency_courage" },
        ],
      },
      { threshold: 5 }
    );
    expect(rows[0].condition).toBe("persistent.reader_tendency_courage >= 5");
    expect(rows[0].derived).toBe(true);
    expect(rows[0].note).toContain("现拼");
  });

  it("计数器名不带 persistent 前缀时补上（省掉前缀 = 普通变量，自适应等于没做）", () => {
    const rows = recipeRows({
      recipes: [
        {
          variableKey: "affection",
          counter: "reader_tendency_affection",
          condition: "",
        },
      ],
    });
    expect(rows[0].condition).toBe("persistent.reader_tendency_affection >= 3");
  });

  it("既没有条件也没有计数器时不编一个条件出来", () => {
    const rows = recipeRows({ recipes: [{ variableKey: "affection" }] });
    expect(rows[0].condition).toBe("");
    expect(rows[0].note).toContain("先跳过");
    expectNoBadTokens(rows);
  });

  it("候选菜单：哪个菜单、几个选项、为什么、怎么改", () => {
    const rows = adaptiveCandidateRows(
      {
        candidates: [
          {
            menuId: "menu_1",
            chapterId: "ch4",
            optionCount: 3,
            reason: "读者几乎总是选同一个选项",
            suggestion: "把它做成自适应",
          },
        ],
      },
      { ch4: "第四章 骤雨" }
    );
    expect(rows[0].title).toBe("第四章 骤雨 · menu_1（3 个选项）");
    expect(rows[0].reason).toContain("几乎总是");
    expect(rows[0].suggestion).toContain("自适应");
  });

  it("候选菜单缺字段时不留空白", () => {
    const rows = adaptiveCandidateRows({ candidates: [{}] });
    expect(rows[0].title).toContain("（章节未知）");
    expect(rows[0].reason).toContain("没给理由");
    expect(rows[0].suggestion).toContain("没给具体改法");
    expect(adaptiveCandidateRows(null)).toEqual([]);
    expectNoBadTokens(rows);
  });
});

describe("自适应：prelude 与导出开关", () => {
  it("prelude 为空串时讲清为什么空、下一步做什么", () => {
    const view = preludeView("");
    expect(view.empty).toBe(true);
    expect(view.text).toBe("");
    expect(view.headline).toContain("没有声明块要写");
    expect(view.emptyGuide).toContain("先在选项里改变量");
    expect(view.hint).toBe("");
    expectNoBadTokens(view);
  });

  it("prelude 缺失 / 全是空白也算空（不渲染空代码框）", () => {
    expect(preludeView(null).empty).toBe(true);
    expect(preludeView(undefined).empty).toBe(true);
    expect(preludeView("   \n  ").empty).toBe(true);
  });

  it("有 prelude 时说清它放哪里、为什么要有", () => {
    const view = preludeView("default persistent.reader_tendency_affection = 0");
    expect(view.empty).toBe(false);
    expect(view.text).toContain("default persistent.");
    expect(view.headline).toContain(".rpy 的开头");
    expect(view.hint).toContain("初值");
    expect(view.emptyGuide).toBe("");
  });

  it("导出开关的说明必须写出来（否则作者会以为导出就有了）", () => {
    expect(ADAPTIVE_EXPORT_NOTE).toContain("adaptive_reader=True");
    expect(ADAPTIVE_EXPORT_NOTE).toContain("默认不开");
    expect(ADAPTIVE_EXPORT_NOTE).toContain(".rpy");
  });

  it("情绪结论的推断口径必须写出来", () => {
    expect(EMOTION_INFERENCE_NOTE).toContain("关键词推断");
    expect(EMOTION_INFERENCE_NOTE).toContain("读错");
    expect(EMOTION_INFERENCE_NOTE).toContain("证据句");
  });
});

describe("总述", () => {
  it("故事层总述把伏笔 / 弧线 / 断裂 / 声明对账压成一句", () => {
    const summary = summarizeStoryMetrics({
      foreshadow: {
        total: 5,
        paid: 2,
        open: 3,
        resolutionRate: 0.4,
        oldestOpenChapters: 9,
      },
      emotionArcs: {
        characters: [
          { character: "凛", start: "低落", end: "激动", delta: 5 },
          { character: "澪", start: "平静", end: "平静", delta: 0 },
        ],
        flatArcs: [{ character: "澪", start: "平静", end: "平静", delta: 0 }],
      },
      emotionArcBreaks: {
        breaks: [
          {
            character: "凛",
            chapterId: "ch4",
            chapterTitle: "第四章",
            overallDelta: 5,
            chapterDelta: -4,
          },
        ],
      },
      declaredArcMismatches: [{ character: "凛", issue: "arc_reversed" }],
    });
    expect(summary.headline).toContain("伏笔 2/5 已回收（40%）");
    expect(summary.headline).toContain("3 条未回收，最老的挂了 9 章");
    expect(summary.headline).toContain("2 个角色有情感弧线（其中 1 个全篇没变化）");
    expect(summary.headline).toContain("1 处逐章走向与全篇相反");
    expect(summary.headline).toContain("与节拍表声明对不上 1 处");
    expectNoBadTokens(summary);
  });

  it("没有伏笔时总述不出现 0%，并说明弧线为什么一条都没有", () => {
    const summary = summarizeStoryMetrics({
      foreshadow: { total: 0, resolutionRate: null },
      emotionArcs: { characters: [] },
    });
    expect(summary.headline).toContain("还没有记录任何伏笔");
    expect(summary.headline).not.toContain("0%");
    expect(summary.notes.join("")).toContain("至少 2 句台词");
    expectNoBadTokens(summary);
  });

  it("自适应总述：几个计数器、几个候选，并在数量对不上时说清楚", () => {
    const view = summarizeAdaptivePlan({
      tendencyCounters: {
        affection: "reader_tendency_affection",
        courage: "reader_tendency_courage",
      },
      recipeThreshold: 3,
      recipes: [
        {
          variableKey: "affection",
          counter: "persistent.reader_tendency_affection",
          condition: "x >= 3",
        },
      ],
      candidates: [],
      prelude: "default persistent.reader_tendency_affection = 0",
    });
    expect(view.counters).toBe(2);
    expect(view.recipes).toBe(1);
    expect(view.hasPrelude).toBe(true);
    expect(view.headline).toContain("2 个变量");
    expect(view.notes.join("")).toContain("条件示例只有 1 条");
    expect(view.notes.join("")).toContain("门槛统一是 3 次");
    expect(view.notes.join("")).toContain("没有菜单被判为");
    expectNoBadTokens(view);
  });

  it("一个计数器都没有时总述直接说前提没满足", () => {
    const view = summarizeAdaptivePlan({ tendencyCounters: {}, prelude: "" });
    expect(view.counters).toBe(0);
    expect(view.hasPrelude).toBe(false);
    expect(view.headline).toContain("还没有可用的读者倾向计数器");
    expect(view.notes.join("")).toContain("某个选项会改变量");
    expect(summarizeAdaptivePlan(null).counters).toBe(0);
  });
});

describe("与后端响应形状对齐（整条翻译链路跑一遍）", () => {
  // 键名照 `core/story_metrics.analyze_story_metrics` 的返回写死：这里用的是
  // `api/projects` 的强类型，字段名一旦和后端对不上，typecheck 会先炸。
  const payload: StoryMetricsOut = {
    foreshadow: {
      total: 5,
      paid: 2,
      open: 3,
      resolutionRate: 0.4,
      chapters: 12,
      oldestOpenChapters: 9,
      openHooks: [
        {
          hook: "红伞的来历",
          plantedChapter: "ch2",
          plantedChapterTitle: "第二章 雨夜",
          chaptersOpen: 9,
        },
        {
          hook: "旧照片上的人",
          plantedChapter: "ch5",
          plantedChapterTitle: "第五章 抽屉",
          chaptersOpen: 4,
        },
      ],
      note: "伏笔状态由写作账本维护（保存章节时自动更新）；这里只做统计。",
    },
    emotionArcs: {
      characters: [
        { character: "凛", start: "低落", end: "激动", delta: 5 },
        { character: "澪", start: "平静", end: "平静", delta: 0 },
      ],
      flatArcs: [{ character: "澪", start: "平静", end: "平静", delta: 0 }],
      note: "情绪由台词关键词推断，不是语义判断。",
    },
    emotionArcBreaks: {
      rows: [
        {
          characterId: "c1",
          character: "凛",
          chapterId: "ch4",
          chapterTitle: "第四章 骤雨",
          chapterIndex: 3,
          start: "激动",
          end: "平静",
          delta: -4,
          lines: 12,
          evidence: ["我说了别管我。", "算了。"],
        },
      ],
      breaks: [
        {
          character: "凛",
          chapterId: "ch4",
          chapterTitle: "第四章 骤雨",
          issue: "emotion_arc_break",
          overallDelta: 5,
          chapterDelta: -4,
          actual: "激动 → 平静",
          message:
            "「凛」全篇情绪是往上走的，但在第四章 骤雨 这一章却从 激动 掉到 平静",
        },
      ],
    },
    declaredArcMismatches: [
      {
        character: "凛",
        issue: "arc_reversed",
        declared: "平静 → 激动",
        actual: "激动 → 平静",
        message: "节拍表声明「凛」的情绪往上走，实际却是反的",
      },
      {
        character: "澪",
        issue: "arc_flat",
        declared: "平静 → 愉悦",
        actual: "平静 → 平静",
        message:
          "节拍表声明「澪」这一场从 平静 走到 愉悦，但台词推断出来前后都是「平静」",
      },
    ],
    findings: [
      {
        severity: "warn",
        code: "foreshadow_low_resolution",
        message: "伏笔回收率偏低：2/5 已回收，最老的一条挂了 9 章",
        source: "story",
      },
      {
        severity: "info",
        code: "emotion_arc_flat",
        message: "「澪」全篇情绪推断为「平静」没有变化",
        source: "story",
      },
      {
        severity: "warn",
        code: "emotion_arc_break",
        message: "「凛」局部走向和全篇相反",
        source: "story",
        chapterId: "ch4",
        character: "凛",
      },
    ],
    counts: { error: 0, warn: 2, info: 1 },
  };

  const plan: AdaptivePlanOut = {
    tendencyCounters: {
      affection: "reader_tendency_affection",
      courage: "reader_tendency_courage",
    },
    recipeThreshold: 3,
    recipes: [
      {
        variableKey: "affection",
        counter: "persistent.reader_tendency_affection",
        condition: "persistent.reader_tendency_affection >= 3",
        meaning: "这个读者在之前的选项里至少有 3 次把「affection」往上涨。",
      },
      {
        variableKey: "courage",
        counter: "persistent.reader_tendency_courage",
        condition: "persistent.reader_tendency_courage >= 3",
        meaning: "这个读者在之前的选项里至少有 3 次把「courage」往上涨。",
      },
    ],
    candidates: [
      {
        menuId: "menu_1",
        chapterId: "ch4",
        optionCount: 3,
        reason: "所有选项后果完全相同（选哪个都一样）",
        suggestion: "把它做成自适应：让一侧按读者的历史倾向变化",
      },
    ],
    prelude:
      "# --- 读者倾向计数器（VN Script Studio 自动生成）---\ndefault persistent.reader_tendency_affection = 0",
    notes: [
      "计数器存在 persistent 里，跨存档保留：它描述的是「这个读者一贯怎么选」。",
      "导出时加 adaptive_reader=True 才会把计数语句写进 .rpy；默认不加，以免同一份剧本两次导出的产物不一样。",
      "试玩器仍按作者写死的条件演出，不模拟 persistent。",
    ],
  };

  it("伏笔 / 弧线 / 断裂 / 对账全部能读出来，且没有 NaN/undefined", () => {
    const view = foreshadowView(payload);
    expect(view.headline).toBe("伏笔回收率 40%：已回收 2/5");
    expect(openHookRows(payload).map((r) => r.chapter)).toEqual([
      "第二章 雨夜",
      "第五章 抽屉",
    ]);

    const arcs = emotionArcRows(payload);
    expect(arcs.map((r) => r.character)).toEqual(["凛", "澪"]);
    expect(arcs[1].flat).toBe(true);

    const chapters = emotionChapterRows(payload);
    expect(chapters[0].broken).toBe(true);
    expect(chapters[0].evidenceText).toContain("算了。");

    const breaks = emotionBreakRows(payload);
    expect(breaks[0].chapter).toBe("第四章 骤雨");
    expect(declaredMismatchGroups(payload).map((g) => g.issue)).toEqual([
      "arc_reversed",
      "arc_flat",
    ]);
    expectNoBadTokens([view, arcs, chapters, breaks]);
  });

  it("自适应方案：计数器 / 条件 / 候选 / prelude 都能读出来", () => {
    const counters = tendencyCounterRows(plan.tendencyCounters);
    expect(counters.map((r) => r.ref)).toEqual([
      "persistent.reader_tendency_affection",
      "persistent.reader_tendency_courage",
    ]);
    const recipes = recipeRows(plan, { threshold: plan.recipeThreshold });
    expect(recipes.map((r) => r.condition)).toEqual([
      "persistent.reader_tendency_affection >= 3",
      "persistent.reader_tendency_courage >= 3",
    ]);
    expect(recipes.every((r) => r.derived === false)).toBe(true);
    expect(adaptiveCandidateRows(plan)[0].title).toContain("menu_1");
    expect(preludeView(plan.prelude).empty).toBe(false);
    expect(summarizeAdaptivePlan(plan).counters).toBe(2);
    expectNoBadTokens({ counters, recipes, summary: summarizeAdaptivePlan(plan) });
  });

  it("后端字段整体缺失（旧版本 / 报错兜底）也不会渲染出 NaN，并说明缺了什么", () => {
    const empty = {} as StoryMetricsOut;
    const view = foreshadowView(empty);
    expect(view.hasRate).toBe(false);
    expect(view.headline).toContain("还没有记录任何伏笔");
    expect(openHookRows(empty)).toEqual([]);
    expect(emotionArcRows(empty)).toEqual([]);
    expect(emotionChapterRows(empty)).toEqual([]);
    expect(declaredMismatchRows(empty)).toEqual([]);
    expectNoNaN(view);

    const noPlan = {} as AdaptivePlanOut;
    expect(tendencyCounterRows(noPlan.tendencyCounters)).toEqual([]);
    expect(recipeRows(noPlan)).toEqual([]);
    expect(preludeView(noPlan.prelude).empty).toBe(true);
    expectNoNaN(summarizeAdaptivePlan(noPlan));
  });
});
