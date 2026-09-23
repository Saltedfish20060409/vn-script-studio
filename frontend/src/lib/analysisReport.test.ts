import { describe, expect, it } from "vitest";
import {
  calibrationNote,
  chapterLabel,
  chapterTitleMap,
  codeLabel,
  driftView,
  findingGroups,
  findingRows,
  groupByCode,
  groupBySeverity,
  normalizeSeverity,
  scanCategoryLabel,
  scanCoverageSentence,
  scanSeverityLabel,
  scanSeverityTone,
  severityCounts,
  summarizeFindings,
  summarizeScanIssues,
  unknownKeyLabel,
  viewCoverage,
  viewScanCoverage,
  viewVoiceReport,
  type FindingInput,
} from "./analysisReport";

describe("结论等级与分组", () => {
  it("已知等级原样归一，未知/缺失等级归到 other（不丢结论）", () => {
    expect(normalizeSeverity("ERROR")).toBe("error");
    expect(normalizeSeverity("warn")).toBe("warn");
    expect(normalizeSeverity("info")).toBe("info");
    expect(normalizeSeverity("fatal")).toBe("other");
    expect(normalizeSeverity(undefined)).toBe("other");
    expect(normalizeSeverity("")).toBe("other");
  });

  it("按 severity 分组：顺序固定 error → warn → info → other", () => {
    const groups = groupBySeverity([
      { severity: "info" },
      { severity: "error" },
      { severity: "warn" },
      { severity: "weird" },
    ]);
    expect(groups.map((g) => g.severity)).toEqual(["error", "warn", "info", "other"]);
    expect(groups.map((g) => g.label)).toEqual(["错误", "警告", "提示", "其它"]);
    expect(groups[0].findings).toHaveLength(1);
  });

  it("空列表 / null 输入返回空分组，不抛异常", () => {
    expect(groupBySeverity([])).toEqual([]);
    expect(groupBySeverity(null)).toEqual([]);
    expect(groupBySeverity(undefined)).toEqual([]);
  });

  it("按 code 归类：先按最严重等级，再按条数从多到少", () => {
    const groups = groupByCode([
      { severity: "warn", code: "unreachable_label" },
      { severity: "warn", code: "unreachable_label" },
      { severity: "error", code: "loop_no_exit" },
      { severity: "warn", code: "choice_never_traversed" },
    ]);
    expect(groups.map((g) => g.code)).toEqual([
      "loop_no_exit",
      "unreachable_label",
      "choice_never_traversed",
    ]);
    expect(groups[0].count).toBe(1);
    expect(groups[1].count).toBe(2);
    expect(groups[1].severity).toBe("warn");
  });

  it("缺 code 的结论不会被丢掉（归到 unknown）", () => {
    const groups = groupByCode([{ severity: "warn", message: "x" }]);
    expect(groups).toHaveLength(1);
    expect(groups[0].code).toBe("unknown");
  });

  it("code 字典命中时给中文短名，未登记的原样显示，空 code 也有兜底", () => {
    expect(codeLabel("loop_no_exit")).toBe("死循环");
    expect(codeLabel("choice_never_traversed")).toBe("走不到的选项");
    expect(codeLabel("death_then_speaks")).toBe("死亡后仍然出场");
    expect(codeLabel("brand_new_code")).toBe("brand_new_code");
    expect(codeLabel("")).toBe("未标注类别的问题");
    expect(codeLabel(undefined)).toBe("未标注类别的问题");
  });

  it("severityCounts 把未知等级计入 other", () => {
    expect(
      severityCounts([
        { severity: "error" },
        { severity: "warn" },
        { severity: "?" },
        { severity: undefined },
      ])
    ).toEqual({ error: 1, warn: 1, info: 0, other: 2 });
  });
});

describe("总述文案", () => {
  it("空列表说没有问题", () => {
    expect(summarizeFindings([])).toBe("没有发现问题。");
    expect(summarizeFindings(null)).toBe("没有发现问题。");
  });

  it("典型：2 个错误 + 5 个警告，点名最大的几类", () => {
    const findings: FindingInput[] = [
      { severity: "error", code: "loop_no_exit" },
      { severity: "error", code: "dangling_jump" },
      { severity: "warn", code: "choice_never_traversed" },
      { severity: "warn", code: "choice_never_traversed" },
      { severity: "warn", code: "unreachable_label" },
      { severity: "warn", code: "unreachable_label" },
      { severity: "warn", code: "unreachable_label" },
    ];
    expect(summarizeFindings(findings)).toBe(
      "2 个错误、5 个警告：其中 1 处是跳转目标不存在、1 处是死循环、3 处是走不到的 label。"
    );
  });

  it("只有提示时不写「0 个错误」", () => {
    expect(summarizeFindings([{ severity: "info", code: "plot_cycle" }])).toBe(
      "1 条提示：其中 1 处是回路。"
    );
  });

  it("未知等级也进总述，不静默吞掉", () => {
    expect(summarizeFindings([{ severity: "fatal", code: "??" }])).toBe(
      "1 条其它：其中 1 处是??。"
    );
  });

  it("点名类别数量可限（默认 3）", () => {
    const many: FindingInput[] = ["a", "b", "c", "d", "e"].map((code) => ({
      severity: "warn",
      code,
    }));
    expect(summarizeFindings(many).split("、")).toHaveLength(3);
    expect(summarizeFindings(many, { maxCategories: 1 })).toBe(
      "5 个警告：其中 1 处是a。"
    );
    expect(summarizeFindings(many, { maxCategories: 0 })).toBe("5 个警告。");
  });
});

describe("覆盖率：看得见 vs 走得通", () => {
  it("labels / choices / paths 转成百分比与文案", () => {
    const view = viewCoverage({
      labels: { total: 10, reachable: 8, ratio: 0.8 },
      choices: { total: 6, usable: 5, traversed: 4, neverTraversed: 1, ratio: 0.667 },
      paths: { count: 12, truncated: false, minLabels: 2, maxLabels: 6, avgLabels: 3.4 },
      score: 0.75,
    });
    expect(view.labelsText).toBe("可达 label 8/10（80%）");
    expect(view.choicesText).toBe("选项走过 4/6（67%）");
    expect(view.pathsText).toBe("枚举到 12 条路径，路径长度 2–6 步");
    expect(view.scorePercent).toBe(75);
    expect(view.verdict).toContain("分支覆盖 75%");
  });

  it("区分「条件永远不可能成立」与「条件成立但没有路径走到」", () => {
    const view = viewCoverage({
      labels: { total: 4, reachable: 4 },
      choices: { total: 6, usable: 5, traversed: 4, neverTraversed: 1 },
      paths: { count: 3, truncated: false },
    });
    expect(view.impossibleChoices).toBe(1);
    expect(view.neverTraversedChoices).toBe(1);
    expect(view.choicesNote).toBe(
      "1 个选项的条件永远不可能成立，玩家永远看不到；1 个选项条件成立、但没有任何可达路径走到"
    );
    expect(view.verdict).toContain("1 个选项玩家永远看不到");
    expect(view.verdict).toContain("1 个选项没有任何路径走到");
  });

  it("只有路径没走到时，不许提「条件不成立」", () => {
    const view = viewCoverage({
      labels: { total: 3, reachable: 3 },
      choices: { total: 4, usable: 4, traversed: 2, neverTraversed: 2 },
      paths: { count: 5, truncated: false },
    });
    expect(view.impossibleChoices).toBe(0);
    expect(view.choicesNote).toBe("2 个选项条件成立、但没有任何可达路径走到");
    expect(view.choicesNote).not.toContain("永远不可能成立");
  });

  it("只有条件不可能成立时，不许提「没有路径走到」", () => {
    const view = viewCoverage({
      labels: { total: 3, reachable: 3 },
      choices: { total: 4, usable: 2, traversed: 2, neverTraversed: 0 },
      paths: { count: 5, truncated: false },
    });
    expect(view.impossibleChoices).toBe(2);
    expect(view.neverTraversedChoices).toBe(0);
    expect(view.choicesNote).toBe("2 个选项的条件永远不可能成立，玩家永远看不到");
    expect(view.choicesNote).not.toContain("没有任何可达路径走到");
  });

  it("全部选项都走得通时给肯定结论", () => {
    const view = viewCoverage({
      labels: { total: 3, reachable: 3 },
      choices: { total: 4, usable: 4, traversed: 4, neverTraversed: 0 },
      paths: { count: 5, truncated: false },
    });
    expect(view.choicesNote).toBe("所有选项都既看得见、又走得通");
    expect(view.verdict).toContain("所有选项都看得见、走得通");
  });

  it("缺字段（null / 空对象）时给 0 而不是 NaN，并降级说明", () => {
    const empty = viewCoverage(null);
    expect(empty.labelsTotal).toBe(0);
    expect(empty.choicesTotal).toBe(0);
    expect(empty.labelsPercent).toBe(0);
    expect(empty.choicesPercent).toBe(0);
    expect(empty.labelsText).toBe("没有 label（剧本还是空的）");
    expect(empty.choicesText).toBe("没有可统计的选项");
    expect(empty.pathsText).toBe("没有枚举到任何路径");
    expect(empty.choicesNote).toBe("");
    expect(empty.verdict).toBe("剧本里还没有可统计的分支结构。");
    expect(JSON.stringify(empty)).not.toContain("NaN");
  });

  it("缺 choices.usable 时不反推「玩家看不到」，按全部可见处理", () => {
    const view = viewCoverage({
      labels: { total: 5, reachable: 5 },
      choices: { total: 3, traversed: 3 },
      paths: { count: 2, truncated: false },
    });
    expect(view.choicesUsable).toBe(3);
    expect(view.impossibleChoices).toBe(0);
    expect(view.choicesNote).toBe("所有选项都既看得见、又走得通");
  });

  it("完全没有路径覆盖信息时如实说明，并用 label 覆盖率给分", () => {
    const view = viewCoverage({
      labels: { total: 4, reachable: 2 },
      choices: { total: 4, usable: 4 },
    });
    expect(view.pathsKnown).toBe(false);
    expect(view.choicesTraversed).toBe(0);
    expect(view.choicesNote).toBe("后端没有给出路径覆盖信息，这里只统计了看得见的选项");
    expect(view.scorePercent).toBe(50);
    expect(view.verdict).toBe("分支覆盖 50%。");
  });

  it("路径枚举被截断时如实标注", () => {
    const view = viewCoverage({
      labels: { total: 2, reachable: 2 },
      choices: { total: 2, usable: 2, traversed: 2, neverTraversed: 0 },
      paths: { count: 500, truncated: true },
    });
    expect(view.pathsTruncated).toBe(true);
    expect(view.pathsText).toContain("已到枚举上限");
  });

  it("数值越界（traversed > total）被夹住，不出现 >100%", () => {
    const view = viewCoverage({
      labels: { total: 2, reachable: 9 },
      choices: { total: 2, usable: 2, traversed: 7, neverTraversed: 0 },
      paths: { count: 1 },
    });
    expect(view.labelsPercent).toBe(100);
    expect(view.choicesPercent).toBe(100);
    expect(view.choicesTraversed).toBe(2);
  });

  it("n = 0 时百分比是 0（不除零）", () => {
    const view = viewCoverage({
      labels: { total: 0, reachable: 0 },
      choices: { total: 0, usable: 0, traversed: 0, neverTraversed: 0 },
      paths: { count: 0 },
    });
    expect(view.labelsPercent).toBe(0);
    expect(view.choicesPercent).toBe(0);
    expect(view.scorePercent).toBe(0);
    expect(Number.isFinite(view.scorePercent)).toBe(true);
  });
});

describe("声线漂移等级", () => {
  it("三档等级 → 颜色语义与文案", () => {
    expect(driftView("ok")).toMatchObject({ level: "ok", tone: "ok", label: "像本人" });
    expect(driftView("watch")).toMatchObject({ level: "watch", tone: "watch", label: "留意" });
    expect(driftView("drift")).toMatchObject({ level: "drift", tone: "drift", label: "跑味" });
  });

  it("等级大小写不敏感", () => {
    expect(driftView("DRIFT").level).toBe("drift");
  });

  it("缺等级 / 未知等级 → 未评估（灰），不当成「像本人」", () => {
    expect(driftView(undefined)).toMatchObject({ level: "unknown", tone: "muted" });
    expect(driftView("").level).toBe("unknown");
    expect(driftView("weird").label).toBe("未评估");
    expect(driftView(undefined).hint).toContain("没有给出漂移等级");
  });

  it("calibrated: false 必须说清「样本不足、未自校准」", () => {
    const note = calibrationNote({ calibrated: false, samples: 3 });
    expect(note).toContain("样本不足");
    expect(note).toContain("未自校准");
    expect(note).toContain("3 个");
  });

  it("calibrated: true 说明阈值来源与样本数", () => {
    const note = calibrationNote({ calibrated: true, samples: 42 });
    expect(note).toContain("自校准");
    expect(note).toContain("42");
    expect(note).not.toContain("样本不足");
  });

  it("缺 calibration 字段时如实说未知", () => {
    expect(calibrationNote(undefined)).toContain("未知");
    expect(calibrationNote(null)).toContain("未知");
  });

  it("声线总述统计角色与漂移处数，并交代谁没被评估", () => {
    const view = viewVoiceReport({
      characters: [
        {
          ready: true,
          chapters: [{ level: "drift" }, { level: "watch" }, { level: "ok" }],
        },
        { ready: true, chapters: [{ level: "ok" }] },
        { ready: false, reason: "台词不足 12 句，不评估声线" },
      ],
      confusablePairs: [{ a: "林夏", b: "周屿", distance: 0.1 }],
    });
    expect(view.totalCharacters).toBe(3);
    expect(view.evaluatedCharacters).toBe(2);
    expect(view.skippedCharacters).toBe(1);
    expect(view.evaluatedChapters).toBe(4);
    expect(view.driftChapters).toBe(1);
    expect(view.watchChapters).toBe(1);
    expect(view.text).toContain("评估了 2 个角色、4 处");
    expect(view.text).toContain("1 处明显跑味");
    expect(view.text).toContain("1 对角色声线过于接近");
    expect(view.text).toContain("另有 1 个角色台词不足");
  });

  it("空报告 / 缺字段不抛异常，也不编结论", () => {
    expect(viewVoiceReport(null).text).toBe(
      "还没有可评估的角色（对白太少，或剧本还没写对白）。"
    );
    const view = viewVoiceReport({ characters: [{ ready: true }] });
    expect(view.evaluatedChapters).toBe(0);
    expect(view.text).toContain("0 处明显跑味");
    expect(view.text).not.toContain("NaN");
  });
});

describe("分片扫描覆盖率", () => {
  const partial = {
    chaptersTotal: 40,
    chaptersWithText: 28,
    chaptersScanned: 12,
    coverageRatio: 0.43,
    windowsPlanned: 6,
    windowsRun: 4,
    windowsFailed: 1,
    truncatedChapters: ["ch13", "ch14"],
    maxWindowsHit: true,
    textTruncatedChapters: ["ch1"],
    chaptersWithBlocksButNoText: 2,
  };

  it("人话里必须出现「扫了多少章 / 共多少章」", () => {
    const sentence = scanCoverageSentence({
      coverage: partial,
      ceilingNote: "旧实现只扫前 14 章且不告知；本次分 4 个窗口扫了 12/28 章（43%）。",
    });
    expect(sentence).toContain("本次扫了 12/28 章（43%）");
    expect(sentence).toContain("旧实现只扫前 14 章");
    expect(sentence.endsWith("。")).toBe(true);
  });

  it("没有 ceilingNote 时也不丢掉未扫章节", () => {
    const sentence = scanCoverageSentence({ coverage: partial, ceilingNote: "" });
    expect(sentence).toContain("12/28");
    expect(sentence).toContain("ch13");
  });

  it("未扫到的章节 / 逐章截断 / 预算上限都如实报出", () => {
    const view = viewScanCoverage(partial);
    expect(view.scanned).toBe(12);
    expect(view.scannable).toBe(28);
    expect(view.percent).toBe(43);
    expect(view.complete).toBe(false);
    expect(view.headline).toBe(
      "本次扫了 12/28 章（43%）；全书共 40 章，其中 12 章没有可送审的正文"
    );
    expect(view.windowsText).toBe(
      "分 4 个窗口扫描（原计划 6 个），其中 1 个窗口失败：那些章节本轮没有结论"
    );
    expect(view.missedText).toBe("未扫到的章节：ch13、ch14");
    expect(view.notes.join("；")).toContain("max_windows");
    expect(view.notes.join("；")).toContain("1 章正文超过单章上限");
    expect(view.notes.join("；")).toContain("2 章有脚本块但没产出可送审的文本");
  });

  it("扫完全部可扫章节时判为完成", () => {
    const view = viewScanCoverage({
      chaptersTotal: 10,
      chaptersWithText: 10,
      chaptersScanned: 10,
      windowsPlanned: 2,
      windowsRun: 2,
      windowsFailed: 0,
      truncatedChapters: [],
    });
    expect(view.complete).toBe(true);
    expect(view.headline).toBe("本次扫了 10/10 章（100%）");
  });

  it("缺 coverage / 空对象时给降级文案，不出现 NaN", () => {
    const none = viewScanCoverage(undefined);
    expect(none.headline).toBe("还没有章节，本轮没有扫到任何内容");
    expect(none.percent).toBe(0);
    expect(none.complete).toBe(false);
    expect(scanCoverageSentence({})).toBe(
      "还没有章节，本轮没有扫到任何内容；没有任何窗口真正跑起来。"
    );
    expect(JSON.stringify(none)).not.toContain("NaN");
  });

  it("只有 chaptersTotal、没有 chaptersWithText 时用全书章数当分母", () => {
    const view = viewScanCoverage({ chaptersTotal: 5, chaptersScanned: 5 });
    expect(view.scannable).toBe(5);
    expect(view.headline).toBe("本次扫了 5/5 章（100%）");
  });

  it("冲突总述：条数 / 优先级 / 跨窗复发", () => {
    expect(summarizeScanIssues([])).toBe("没有发现明显冲突。");
    expect(summarizeScanIssues(null)).toBe("没有发现明显冲突。");
    const text = summarizeScanIssues([
      { severity: "high", foundInWindows: 2 },
      { severity: "medium", confidence: "high" },
      { severity: "low" },
    ]);
    expect(text).toBe("3 条冲突：1 条高优先级、1 条中优先级、2 条在多个窗口复现（更可信）。");
  });

  it("冲突的分类 / 等级文案有兜底", () => {
    expect(scanCategoryLabel("character")).toBe("角色");
    expect(scanCategoryLabel("bible")).toBe("设定");
    expect(scanCategoryLabel("unheard_of")).toBe("unheard_of");
    expect(scanCategoryLabel(undefined)).toBe("剧情");
    expect(scanSeverityLabel("high")).toBe("高");
    expect(scanSeverityLabel("???")).toBe("未知");
    expect(scanSeverityTone("medium")).toBe("warn");
    expect(scanSeverityTone(undefined)).toBe("muted");
  });
});

describe("章节标题", () => {
  it("有标题用标题，没有就退回 id，空 id 返回空串", () => {
    const titles = chapterTitleMap([
      { id: "ch1", title: "第一章 雨夜" },
      { id: "ch2", title: "   " },
      { id: "", title: "无 id" },
    ]);
    expect(titles).toEqual({ ch1: "第一章 雨夜" });
    expect(chapterLabel("ch1", titles)).toBe("第一章 雨夜");
    expect(chapterLabel("ch2", titles)).toBe("ch2");
    expect(chapterLabel("ch9", titles)).toBe("ch9");
    expect(chapterLabel("", titles)).toBe("");
    expect(chapterLabel(undefined, titles)).toBe("");
    expect(chapterLabel("ch1", undefined)).toBe("ch1");
  });

  it("每行结论带 severity、中文 message、所在章节", () => {
    const rows = findingRows(
      [
        { severity: "error", code: "loop_no_exit", message: "死循环：a → b", chapterId: "ch1" },
        { severity: "warn", code: "mystery", message: "", chapterId: "ch9", label: "L1" },
      ],
      { ch1: "第一章 雨夜" }
    );
    expect(rows).toHaveLength(2);
    expect(rows[0]).toMatchObject({
      severity: "error",
      severityLabel: "错误",
      codeLabel: "死循环",
      chapter: "第一章 雨夜",
      message: "死循环：a → b",
    });
    expect(rows[1].chapter).toBe("ch9");
    expect(rows[1].codeLabel).toBe("mystery");
    expect(rows[1].message).toBe("（后端没有给出说明）");
    expect(rows[1].label).toBe("L1");
    expect(new Set(rows.map((r) => r.key)).size).toBe(2);
  });

  it("空 / null findings 返回空数组", () => {
    expect(findingRows(null)).toEqual([]);
    expect(findingRows([])).toEqual([]);
  });

  it("结论分组：同 code 归一块，超出上限的条数如实报出", () => {
    const findings: FindingInput[] = Array.from({ length: 8 }, (_, i) => ({
      severity: "warn",
      code: "unreachable_label",
      message: `第 ${i} 条`,
      chapterId: "ch1",
    }));
    const groups = findingGroups(findings, { ch1: "第一章" }, { maxRowsPerGroup: 3 });
    expect(groups).toHaveLength(1);
    expect(groups[0].count).toBe(8);
    expect(groups[0].rows).toHaveLength(3);
    expect(groups[0].hidden).toBe(5);
    expect(groups[0].rows[0].chapter).toBe("第一章");
  });

  it("展开全部时不再截断", () => {
    const findings: FindingInput[] = Array.from({ length: 8 }, () => ({
      severity: "warn",
      code: "unreachable_label",
    }));
    const groups = findingGroups(findings, null, { maxRowsPerGroup: 3, expandAll: true });
    expect(groups[0].rows).toHaveLength(8);
    expect(groups[0].hidden).toBe(0);
  });

  it("缺 code 的结论归到 unknown 分组，不会被丢掉", () => {
    const groups = findingGroups([{ severity: "error", message: "x" }], null);
    expect(groups).toHaveLength(1);
    expect(groups[0].code).toBe("unknown");
    expect(groups[0].rows).toHaveLength(1);
  });

  it("空输入返回空分组", () => {
    expect(findingGroups([], null)).toEqual([]);
    expect(findingGroups(null, null)).toEqual([]);
  });

  it("「机器也拿不准」的计数键给中文说明，未登记的原样显示", () => {
    expect(unknownKeyLabel("locationTableEmpty")).toContain("地点表");
    expect(unknownKeyLabel("timelineOrderTies")).toContain("歧义");
    expect(unknownKeyLabel("someNewKey")).toBe("someNewKey");
    expect(unknownKeyLabel("")).toBe("");
  });
});
