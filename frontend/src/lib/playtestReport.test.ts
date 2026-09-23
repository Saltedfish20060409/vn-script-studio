import { describe, expect, it } from "vitest";
import {
  coverageView,
  endingsView,
  formatShare,
  funnelView,
  menuView,
  OPTION_COPY_NOTE,
  optionLabel,
  optionRows,
  sampleView,
  TELEMETRY_PRIVACY_NOTE,
  telemetrySwitchCopy,
} from "./playtestReport";

const chapterName = (id: string) => (id ? `《${id}》` : "");

describe("占比与选项标签", () => {
  it("占比格式化成百分比，缺失/非法显示破折号而不是 NaN", () => {
    expect(formatShare(0.235)).toBe("23.5%");
    expect(formatShare(0)).toBe("0.0%");
    expect(formatShare(1)).toBe("100.0%");
    expect(formatShare(undefined)).toBe("—");
    expect(formatShare(null)).toBe("—");
    expect(formatShare(Number.NaN)).toBe("—");
  });

  it("选项只能说「第 N 个选项」（文案不在遥测里）", () => {
    expect(optionLabel(0)).toBe("第 1 个选项");
    expect(optionLabel(2)).toBe("第 3 个选项");
    expect(optionLabel(-1)).toBe("序号缺失的选项");
    expect(optionLabel(undefined)).toBe("序号缺失的选项");
    expect(OPTION_COPY_NOTE).toContain("第 N 个选项");
    expect(OPTION_COPY_NOTE).toContain("编辑器");
  });
});

describe("选项占比视图", () => {
  it("列出每个选项，并从没人选的选项标 warn + 写明原因", () => {
    const rows = optionRows({
      menuId: "menu_1",
      options: [
        { index: 0, selected: 8, share: 0.8, neverSelected: false, available: true },
        { index: 1, selected: 2, share: 0.2, neverSelected: false, available: true },
        { index: 2, selected: 0, share: 0, neverSelected: true, available: true },
        { index: 3, selected: 0, share: 0, neverSelected: true, available: false },
      ],
    });
    expect(rows.map((r) => r.label)).toEqual([
      "第 1 个选项",
      "第 2 个选项",
      "第 3 个选项",
      "第 4 个选项",
    ]);
    expect(rows.map((r) => r.shareText)).toEqual(["80.0%", "20.0%", "0.0%", "0.0%"]);
    expect(rows[2].tone).toBe("warn");
    expect(rows[2].note).toBe("从没人选");
    expect(rows[3].note).toBe("从没人选（条件恒不成立）");
    expect(rows[0].tone).toBe("ok");
  });

  it("neverSelected 缺失时用菜单级的 neverSelected 下标兜底", () => {
    const rows = optionRows({
      menuId: "menu_1",
      neverSelected: [1],
      options: [{ index: 0, selected: 3, share: 1 }, { index: 1, selected: 0, share: 0 }],
    });
    expect(rows[0].tone).toBe("ok");
    expect(rows[1].tone).toBe("warn");
  });

  it("条件挡住过的选择次数如实写出来", () => {
    const rows = optionRows({
      menuId: "menu_1",
      options: [
        {
          index: 0,
          selected: 5,
          share: 1,
          neverSelected: false,
          conditionBlockedSelections: 2,
        },
      ],
    });
    expect(rows[0].note).toBe("其中 2 次是在条件不成立时被选的");
  });

  it("缺字段 / 空数组都不抛异常，也不显示 NaN", () => {
    expect(optionRows(null)).toEqual([]);
    expect(optionRows({ menuId: "menu_1" })).toEqual([]);
    const rows = optionRows({ menuId: "menu_1", options: [{}] });
    expect(rows[0].label).toBe("第 1 个选项");
    expect(rows[0].shareText).toBe("0.0%");
    expect(rows[0].percent).toBe(0);
  });
});

describe("菜单视图", () => {
  it("标题带章节名，摘要带选择次数，并点名从没人选的选项", () => {
    const view = menuView(
      {
        menuId: "menu_2",
        chapterId: "ch3",
        selections: 10,
        options: [
          { index: 0, selected: 10, share: 1, neverSelected: false },
          { index: 1, selected: 0, share: 0, neverSelected: true },
        ],
      },
      chapterName("ch3")
    );
    expect(view.title).toBe("《ch3》 · menu_2");
    expect(view.summary).toBe("被选 10 次 / 2 个选项");
    expect(view.touchedText).toBe("有人选过 1 / 2 个选项");
    expect(view.neverSelectedText).toBe("从没人选：第 2 个选项");
  });

  it("每个选项都被选过时明确说一句，而不是留白", () => {
    const view = menuView({
      menuId: "menu_1",
      selections: 4,
      options: [
        { index: 0, selected: 2, share: 0.5, neverSelected: false },
        { index: 1, selected: 2, share: 0.5, neverSelected: false },
      ],
    });
    expect(view.neverSelectedText).toBe("每个选项都至少被选过一次。");
    expect(view.title).toBe("menu_1");
  });

  it("没有选择记录 / 剧本里解析不到选项时各给一句解释", () => {
    const empty = menuView({ menuId: "menu_1", selections: 0, options: [] });
    expect(empty.notes).toHaveLength(2);
    expect(empty.notes[0]).toContain("没有任何选择记录");
    expect(empty.notes[1]).toContain("解析不到这个菜单的选项");
  });
});

describe("样本量提示", () => {
  it("没有样本时明说「还没有样本」并解释什么时候才会有", () => {
    const view = sampleView({ runs: 0, choices: 0, minSample: 10, sufficient: false });
    expect(view.tone).toBe("warn");
    expect(view.headline).toBe("还没有任何试玩样本。");
    expect(view.hint).toContain("走到结局");
  });

  it("样本不足时给出具体数字，并声明不足以下结论", () => {
    const view = sampleView({ runs: 3, choices: 7, minSample: 10, sufficient: false });
    expect(view.tone).toBe("warn");
    expect(view.headline).toContain("只有 3 次试玩、7 次选择");
    expect(view.headline).toContain("至少 10 次");
    expect(view.hint).toContain("不足以下结论");
  });

  it("达到下限时报口径，并把截断如实说出来", () => {
    const ok = sampleView({ runs: 12, choices: 40, minSample: 10, sufficient: true });
    expect(ok.tone).toBe("ok");
    expect(ok.headline).toContain("达到统计口径下限 10 次");
    expect(sampleView({ runs: 12, minSample: 10, truncated: true }).hint).toContain(
      "超过单次分析上限"
    );
  });

  it("缺字段也能给出话（回退到 0 / 10）", () => {
    expect(sampleView(null).headline).toBe("还没有任何试玩样本。");
    expect(sampleView({}).headline).toBe("还没有任何试玩样本。");
  });
});

describe("漏斗与流失", () => {
  it("逐章列出到达与流失，第一章不算流失", () => {
    const view = funnelView(
      {
        startedRuns: 10,
        chapters: [
          { chapterId: "ch1", reached: 10, choosingRuns: 8, dropFromPrevious: 0, dropRate: 0 },
          { chapterId: "ch2", reached: 6, choosingRuns: 5, dropFromPrevious: 4, dropRate: 0.4 },
        ],
        biggestDrop: { chapterId: "ch2", dropFromPrevious: 4, dropRate: 0.4 },
      },
      chapterName
    );
    expect(view.rows.map((r) => r.title)).toEqual(["《ch1》", "《ch2》"]);
    expect(view.rows[0].dropText).toBe("没有流失");
    expect(view.rows[1].dropText).toBe("流失 4 次（40.0%）");
    expect(view.rows[1].tone).toBe("warn");
    expect(view.verdict).toBe("流失最多的一章：《ch2》（流失 4 次，流失率 40.0%）。");
  });

  it("没有流失 / 没有样本 / 解析不到章节各给一句结论", () => {
    expect(
      funnelView({ startedRuns: 5, chapters: [{ chapterId: "ch1", reached: 5 }] }).verdict
    ).toBe("没有任何一章出现流失：读到这里的人基本都读完了。");
    expect(funnelView({ startedRuns: 0, chapters: [] }).verdict).toBe(
      "还没有试玩样本，漏斗是空的。"
    );
    expect(funnelView({ startedRuns: 3, chapters: [] }).verdict).toContain(
      "解析不到章节顺序"
    );
    expect(funnelView(null).verdict).toBe("还没有试玩样本，漏斗是空的。");
  });

  it("纯阅读（所有章都没有选择）与未知章节都如实说明", () => {
    const view = funnelView({
      startedRuns: 2,
      chapters: [{ chapterId: "ch1", reached: 2, choosingRuns: 0 }],
      unknownChapters: [{ chapterId: "gone", selections: 3 }],
    });
    expect(view.notes.join("")).toContain("纯阅读");
    expect(view.notes.join("")).toContain("不在当前章节顺序里");
    expect(view.notes.join("")).toContain("试玩器一次只演一章");
  });
});

describe("结局分布", () => {
  it("列出读者走到的结局并按是否登记标色，点名从没人走到的结局", () => {
    const view = endingsView({
      reached: [
        { label: "ending_good", name: "好结局", runs: 7, share: 0.7, declared: true },
        {
          label: "ending_orphan",
          name: "ending_orphan",
          runs: 3,
          share: 0.3,
          declared: false,
          isStaticTerminal: true,
        },
      ],
      declaredTotal: 3,
      declaredReached: 1,
      neverReached: [
        { label: "ending_bad", name: "坏结局", reachableInScript: true },
        { label: "ending_secret", name: "隐藏结局", reachableInScript: false },
      ],
      unfinishedRuns: 2,
    });
    expect(view.headline).toBe("登记了 3 个结局，读者实际走到 1 个。");
    expect(view.rows[0].title).toBe("好结局");
    expect(view.rows[0].shareText).toBe("70.0%");
    expect(view.rows[0].tone).toBe("ok");
    expect(view.rows[1].tone).toBe("warn");
    expect(view.rows[1].note).toContain("在控制流里确实是个终点");
    expect(view.neverReachedText).toContain("从没人走到的结局（2）");
    expect(view.neverReachedText).toContain("坏结局");
    expect(view.neverReached[0].reachableInScript).toBe(true);
    expect(view.notes.join("")).toContain("没走到任何结局");
  });

  it("没有登记结局时改用「读者实际走到的终点」口径", () => {
    const view = endingsView({
      reached: [{ label: "the_end", runs: 1, share: 1, declared: false }],
      declaredTotal: 0,
      declaredReached: 0,
    });
    expect(view.headline).toContain("还没有登记任何结局");
    expect(view.rows[0].title).toBe("the_end");
    expect(view.neverReachedText).toBe("");
    expect(view.rows[0].note).toContain("不在静态分析的终点里");
  });

  it("没有样本时不给「都走到了」这种假结论，缺字段也不抛", () => {
    expect(endingsView(null).rows).toEqual([]);
    expect(endingsView({ reached: [], declaredTotal: 2, neverReached: [] }).neverReachedText).toBe(
      ""
    );
  });

  it("未登记结局 / 没有 label 的结局分别提示", () => {
    const view = endingsView({
      reached: [{ label: "x", runs: 1, share: 1, declared: true }],
      declaredTotal: 2,
      declaredReached: 1,
      unknownEndingLabels: [{ label: "mystery" }],
      declaredWithoutLabel: [{ name: "无名结局" }],
    });
    expect(view.notes.join("")).toContain("漏登记");
    expect(view.notes.join("")).toContain("没有 label");
  });
});

describe("读者侧分支覆盖率", () => {
  it("给出碰过的选项/菜单比例与没被碰过的菜单", () => {
    const view = coverageView({
      availableOptions: 8,
      observedOptions: 3,
      ratio: 0.375,
      menusTotal: 4,
      menusTouched: 2,
      menusNeverTouched: ["menu_9", "menu_10"],
      unmappedSelections: 1,
    });
    expect(view.text).toBe("读者碰过的选项：3 / 8（37.5%），碰过的菜单：2 / 4");
    expect(view.percent).toBeCloseTo(37.5, 5);
    expect(view.tone).toBe("warn");
    expect(view.menusNeverTouchedText).toContain("menu_9");
    expect(view.notes.join("")).toContain("找不到对应的选项");
  });

  it("覆盖率高时给 ok，剧本里没有可选项时给 bad 并解释", () => {
    expect(
      coverageView({ availableOptions: 4, observedOptions: 4, ratio: 1 }).tone
    ).toBe("ok");
    const none = coverageView({ availableOptions: 0, observedOptions: 0, ratio: 0 });
    expect(none.tone).toBe("bad");
    expect(none.notes.join("")).toContain("条件可满足的选项");
  });

  it("每个菜单都被碰过时明说，缺字段不抛", () => {
    expect(coverageView({ availableOptions: 2, observedOptions: 1, ratio: 0.5 }).menusNeverTouchedText).toBe(
      "每个菜单都至少有一名读者碰过。"
    );
    expect(coverageView(null).text).toContain("0 / 0");
  });
});

describe("开关文案", () => {
  it("未开启时明说「未开启，没有数据」", () => {
    const copy = telemetrySwitchCopy(false);
    expect(copy.title).toContain("未开启");
    expect(copy.emptyText).toContain("未开启，没有数据");
    expect(copy.emptyText).toContain("不会被补记");
  });

  it("开启后明说已开启，并解释为什么还没有数据", () => {
    const copy = telemetrySwitchCopy(true);
    expect(copy.title).toContain("已开启");
    expect(copy.emptyText).toContain("还没有任何样本");
  });

  it("两种状态下都提示「不记任何台词/文案」", () => {
    for (const enabled of [true, false]) {
      const copy = telemetrySwitchCopy(enabled);
      expect(copy.hint).toBe(TELEMETRY_PRIVACY_NOTE);
      expect(copy.hint).toContain("不记任何台词、选项文案或旁白");
      expect(copy.hint).toContain("只记选项 id 与计数");
    }
  });
});
