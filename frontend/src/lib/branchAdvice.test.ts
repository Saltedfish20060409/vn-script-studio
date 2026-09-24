import { describe, expect, it } from "vitest";
import type { BranchRecommendationsOut } from "../api/projects";
import {
  ADVICE_CAVEAT,
  adviceCodeLabel,
  adviceGroups,
  adviceRows,
  adviceSeverityLabel,
  adviceSeverityTone,
  adviceStale,
  adviceSummary,
  basisView,
  choiceVarietyView,
  confidenceView,
  DEFAULT_MIN_RUNS,
  emptyAdvice,
  isKnownSeverity,
  MIN_RUNS_RANGE,
  minRunsView,
  parseMinRuns,
  SCRIPT_ONLY_CAVEAT,
} from "./branchAdvice";

/** 一条建议（默认是"必须改"的静态结论），只覆盖要测的字段。 */
function rec(over: Record<string, unknown> = {}) {
  return {
    code: "loop_no_exit",
    severity: "error",
    priority: 100,
    confidence: "static",
    title: "存在玩家出不去的死循环",
    why: "「a → b」这条回路既没有变量变化、也没有条件出口。",
    action: "在回路上加一个能真正改变状态的变量赋值。",
    where: "ch1/m1",
    evidence: {},
    ...over,
  };
}

/** 视图里绝不能出现的东西：NaN / undefined / null 被当成文案渲染出去。 */
function expectNoBadTokens(view: unknown) {
  const text = JSON.stringify(view);
  expect(text).not.toContain("NaN");
  expect(text).not.toContain("undefined");
  expect(text).not.toContain(":null");
}

describe("建议等级与置信度", () => {
  it("三个已知等级各有中文说法，未知等级归「其它」而不是丢掉", () => {
    expect(adviceSeverityLabel("error")).toBe("必须改");
    expect(adviceSeverityLabel("warn")).toBe("建议改");
    expect(adviceSeverityLabel("info")).toBe("可以看看");
    expect(adviceSeverityLabel("fatal")).toBe("其它");
    expect(adviceSeverityLabel(undefined)).toBe("其它");
    expect(adviceSeverityTone("fatal")).toBe("other");
    expect(adviceSeverityTone("warn")).toBe("warn");
    expect(isKnownSeverity("error")).toBe(true);
    expect(isKnownSeverity("WARN")).toBe(true);
    expect(isKnownSeverity("fatal")).toBe(false);
    expect(isKnownSeverity("")).toBe(false);
  });

  it("置信度必须分得开「有读者证据」与「纯静态推断」", () => {
    const evidence = confidenceView("evidence");
    const stat = confidenceView("static");
    expect(evidence.label).toBe("有读者证据");
    expect(evidence.tone).toBe("evidence");
    expect(evidence.hint).toContain("读者实际行为");
    expect(stat.label).toBe("纯静态推断");
    expect(stat.hint).toContain("没有读者数据支撑");
    expect(evidence.label).not.toBe(stat.label);
  });

  it("置信度未知时按未知处理，并把后端给的值原样写出来", () => {
    expect(confidenceView("maybe").tone).toBe("other");
    expect(confidenceView("maybe").hint).toContain("maybe");
    expect(confidenceView(undefined).hint).toContain("没给置信度字段");
  });

  it("code 有中文短名，没登记的 code 原样露出代号", () => {
    expect(adviceCodeLabel("no_effect_menu")).toBe("选哪个都一样");
    expect(adviceCodeLabel("brand_new_code")).toBe("brand_new_code");
    expect(adviceCodeLabel("")).toBe("未标注类别的问题");
  });
});

describe("choiceVarietyView（选项分类的展示层）", () => {
  const variety = (counts: Record<string, number>, relaxed: string[] = []) => ({
    menus: [],
    counts,
    classLabels: {
      relaxed: "怎么选都一样",
      obvious: "意图明确（后果可预期，但没有代价）",
      dilemma: "两难（两边都要付出代价）",
    },
    allRelaxedMenus: relaxed,
    notes: ["分类是**结构启发式**……", "没有两难选择不是错误：……"],
  });

  it("没有数据时返回 null（界面不渲染空块）", () => {
    expect(choiceVarietyView(null)).toBeNull();
    expect(choiceVarietyView(undefined)).toBeNull();
    expect(choiceVarietyView(variety({ menus: 0 }))).toBeNull();
  });

  it("有两难选项时报出条数，并把它说成「真正的取舍」", () => {
    const view = choiceVarietyView(variety({ menus: 3, relaxed: 1, obvious: 4, dilemma: 2 }));
    expect(view?.headline).toContain("3 个选择点");
    expect(view?.headline).toContain("2 个选项构成真正的取舍");
  });

  it("没有两难时明说「不是错误」，免得像在挑错（两种分支都要说）", () => {
    const onlyObvious = choiceVarietyView(variety({ menus: 2, obvious: 4 }));
    expect(onlyObvious?.headline).toContain("不是错误");

    const withRelaxed = choiceVarietyView(variety({ menus: 2, obvious: 1, relaxed: 3 }));
    expect(withRelaxed?.headline).toContain("还没有出现");
    expect(withRelaxed?.headline).toContain("不是错误");
  });

  it("只列出有条数的类别（0 条不该显示成缺功能）", () => {
    const view = choiceVarietyView(variety({ menus: 2, obvious: 4, relaxed: 0, dilemma: 0 }));
    expect(view?.parts.map((p) => p.key)).toEqual(["obvious"]);
    expect(view?.parts[0].label).toContain("意图明确");
  });

  it("把「怎么选都一样」的选择点列出来（作者要能直接找过去改）", () => {
    const view = choiceVarietyView(variety({ menus: 3, relaxed: 3 }, ["ch1/m1", "ch2/m4"]));
    expect(view?.relaxedMenus).toEqual(["ch1/m1", "ch2/m4"]);
  });

  it("后端的口径说明原样带出（不在前端改写边界说明）", () => {
    const view = choiceVarietyView(variety({ menus: 1, obvious: 1 }));
    expect(view?.notes.join()).toContain("结构启发式");
    expect(view?.notes.join()).toContain("不是错误");
  });

  it("缺 classLabels 时退回英文键而不是崩（老后端兼容）", () => {
    const view = choiceVarietyView({
      menus: [],
      counts: { menus: 1, dilemma: 1 },
      classLabels: {},
      allRelaxedMenus: [],
      notes: [],
    });
    expect(view?.parts[0].label).toBe("dilemma");
  });
});

describe("试玩次数门槛（min_runs）", () => {
  it("门槛的含义要能读出来：低于它就不做经验判断", () => {
    const view = minRunsView(10);
    expect(view.text).toBe("经验判断门槛：至少 10 次试玩");
    expect(view.hint).toContain("不做任何经验判断");
    expect(view.hint).toContain("低于 10 次");
    expect(view.notes).toEqual([]);
  });

  it("门槛缺失时按后端默认 10 次显示并如实说明", () => {
    expect(minRunsView(undefined).text).toContain(`${DEFAULT_MIN_RUNS} 次`);
    expect(minRunsView(undefined).notes.join("")).toContain("后端没给门槛");
    expect(minRunsView(Number.NaN).text).toContain(`${DEFAULT_MIN_RUNS} 次`);
  });

  it("输入框 → min_runs：空/非法回落默认值，超范围夹到后端允许的 1–10000", () => {
    expect(parseMinRuns("12")).toBe(12);
    expect(parseMinRuns(12)).toBe(12);
    expect(parseMinRuns("")).toBe(DEFAULT_MIN_RUNS);
    expect(parseMinRuns("abc")).toBe(DEFAULT_MIN_RUNS);
    expect(parseMinRuns(null)).toBe(DEFAULT_MIN_RUNS);
    expect(parseMinRuns("0")).toBe(MIN_RUNS_RANGE.min);
    expect(parseMinRuns("-5")).toBe(MIN_RUNS_RANGE.min);
    expect(parseMinRuns("999999")).toBe(MIN_RUNS_RANGE.max);
    expect(parseMinRuns("7.9")).toBe(7);
  });
});

describe("判断依据（basis / sampleNote）", () => {
  it("script-only 时明说「只有静态建议，读者数据不足」，并给出为什么不能当成没问题", () => {
    const view = basisView("script-only", "读者数据只有 3 次试玩（低于 10 次的门槛）。");
    expect(view.tone).toBe("warn");
    expect(view.headline).toContain("只有静态建议");
    expect(view.headline).toContain("读者数据不足");
    expect(view.caveat).toBe(SCRIPT_ONLY_CAVEAT);
    expect(view.caveat).toContain("不等于「没有问题」");
    expect(view.readerAdviceMissing).toBe(true);
    expect(view.sampleNote).toBe("读者数据只有 3 次试玩（低于 10 次的门槛）。");
  });

  it("script+readers 时报两类建议都在，不给警告", () => {
    const view = basisView("script+readers", "静态分析 + 12 次试玩的实际选择。");
    expect(view.tone).toBe("ok");
    expect(view.headline).toContain("读者实际行为");
    expect(view.caveat).toBe("");
    expect(view.readerAdviceMissing).toBe(false);
    expect(view.sampleNote).toContain("12 次试玩");
  });

  it("sampleNote 缺失 / basis 未知都不留空白：兜底说明 + 最保守口径", () => {
    expect(basisView("script-only", "").sampleNote).toContain("后端没有给样本说明");
    const unknown = basisView("static+magic", "");
    expect(unknown.tone).toBe("other");
    expect(unknown.readerAdviceMissing).toBe(true);
    expect(unknown.headline).toContain("static+magic");
    expect(basisView(undefined).headline).toContain("没给判断依据字段");
  });
});

describe("建议行（action 必须显示、where 没有就不显示）", () => {
  it("一行里同时带着依据与具体改法，并按 severity 排序", () => {
    const rows = adviceRows({
      recommendations: [
        rec({ code: "single_option_menu", severity: "info", priority: 20, where: "ch2/m9" }),
        rec({ code: "no_effect_menu", severity: "warn", priority: 50, where: "ch1/m1" }),
        rec({ code: "softlock_menu", severity: "error", priority: 100, where: "ch3/m2" }),
        rec({ code: "fatal_thing", severity: "fatal", priority: 900, where: "ch4/m3" }),
      ],
    });
    expect(rows.map((r) => r.severity)).toEqual(["error", "warn", "info", "other"]);
    expect(rows.map((r) => r.severityLabel)).toEqual([
      "必须改",
      "建议改",
      "可以看看",
      "其它",
    ]);
    expect(rows[0].action).toContain("变量赋值");
    expect(rows[0].why).toContain("回路");
    expect(rows[3].rawSeverity).toBe("fatal");
    expect(rows.every((r) => r.action !== "" && r.actionMissing === false)).toBe(true);
    expectNoBadTokens(rows);
  });

  it("同等级内按 priority 降序，相同优先级再按位置稳定排", () => {
    const rows = adviceRows({
      recommendations: [
        rec({ code: "a", severity: "warn", priority: 50, where: "ch2/m1" }),
        rec({ code: "b", severity: "warn", priority: 70, where: "ch9/m1" }),
        rec({ code: "c", severity: "warn", priority: 50, where: "ch1/m1" }),
      ],
    });
    expect(rows.map((r) => r.code)).toEqual(["b", "c", "a"]);
  });

  it("where 缺失时不显示空标签（空串而不是 undefined）", () => {
    const rows = adviceRows({
      recommendations: [rec({ where: "" }), rec({ code: "x", where: "" })],
    });
    expect(rows[0].where).toBe("");
    expect(rows[1].where).toBe("");
    expectNoBadTokens(rows);
  });

  it("action 缺失时如实说明缺了什么，而不是安静地只显示结论", () => {
    const rows = adviceRows({ recommendations: [rec({ action: "", title: "", why: "" })] });
    expect(rows[0].action).toBe("");
    expect(rows[0].actionMissing).toBe(true);
    expect(rows[0].title).toBe("死循环");
    expect(rows[0].why).toBe("（后端没给依据）");
    expectNoBadTokens(rows);
  });

  it("字段整体缺失 / 非法类型也不抛异常，不显示 NaN", () => {
    expect(adviceRows(null)).toEqual([]);
    expect(adviceRows({})).toEqual([]);
    expect(adviceRows({ recommendations: null })).toEqual([]);
    const rows = adviceRows({
      recommendations: [{ code: "no_effect_menu", priority: Number.NaN } as never],
    });
    expect(rows[0].priority).toBe(0);
    expect(rows[0].severityLabel).toBe("其它");
    expectNoBadTokens(rows);
  });

  it("按 severity 分组：空组不出现，未知等级单独成组", () => {
    const groups = adviceGroups(
      adviceRows({
        recommendations: [
          rec({ severity: "warn", code: "no_effect_menu" }),
          rec({ severity: "weird" }),
        ],
      })
    );
    expect(groups.map((g) => g.severity)).toEqual(["warn", "other"]);
    expect(groups[1].label).toBe("其它");
    expect(adviceGroups([])).toEqual([]);
    expect(adviceGroups(null)).toEqual([]);
  });
});

describe("总述与计数", () => {
  it("给出「几条必须改、几条建议改」并点名无后果分支", () => {
    const summary = adviceSummary({
      recommendations: [
        rec({ code: "loop_no_exit", severity: "error" }),
        rec({ code: "unreachable_ending", severity: "error" }),
        rec({ code: "no_effect_menu", severity: "warn", confidence: "evidence" }),
        rec({ code: "never_selected_option", severity: "warn", confidence: "evidence" }),
        rec({ code: "dominant_option", severity: "warn", confidence: "evidence" }),
      ],
    });
    expect(summary.counts).toEqual({ error: 2, warn: 3, info: 0, other: 0, total: 5 });
    expect(summary.headline).toBe("2 条必须改、3 条建议改：其中 1 条是「选哪个都一样」。");
    expect(summary.confidenceText).toBe("置信度：3 条有读者证据，2 条纯静态推断。");
    expect(summary.notes).toEqual([]);
  });

  it("未知等级也计入总述（不静默丢）", () => {
    const summary = adviceSummary({
      recommendations: [rec({ severity: "error" }), rec({ severity: "??" })],
    });
    expect(summary.counts.other).toBe(1);
    expect(summary.headline).toContain("1 条其它（等级未知）");
    expect(summary.headline).toContain("1 条必须改");
  });

  it("没有点名 code 时总述只报计数，不硬凑一句", () => {
    const summary = adviceSummary({
      recommendations: [rec({ code: "unreachable_ending", severity: "info" })],
    });
    expect(summary.headline).toBe("1 条可以看看。");
  });

  it("计数一律以列表为准：后端 counts 对不上时如实说明并按列表显示", () => {
    const summary = adviceSummary({
      recommendations: [rec({ severity: "error" }), rec({ severity: "error" }), rec({ severity: "warn" })],
      counts: { error: 1, warn: 1, info: 0, total: 2 },
    });
    expect(summary.counts).toEqual({ error: 2, warn: 1, info: 0, other: 0, total: 3 });
    expect(summary.notes.join("")).toContain("对不上");
    expect(summary.notes.join("")).toContain("必须改 后端报 1 条、列表里 2 条");
    expect(summary.notes.join("")).toContain("界面按列表实际内容显示");
    expectNoBadTokens(summary);
  });

  it("后端 summary 的 static/evidence 与逐条统计对不上时也说清楚", () => {
    const summary = adviceSummary({
      recommendations: [rec({ severity: "warn", confidence: "evidence" })],
      summary: { static: 5, evidence: 1, topCode: "no_effect_menu" },
    });
    expect(summary.notes.join("")).toContain("与列表里逐条统计");
  });

  it("recommendations 字段整个缺失时说一句，而不是假装「没有问题」", () => {
    const summary = adviceSummary({ basis: "script-only" });
    expect(summary.counts.total).toBe(0);
    expect(summary.headline).toBe("这一轮没有任何建议。");
    expect(summary.notes.join("")).toContain("没有建议列表");
  });
});

describe("空列表文案", () => {
  it("说「没有发现结构性问题」，并附上「这不等于剧本没问题」", () => {
    const view = emptyAdvice({
      basis: "script+readers",
      notes: [
        "没有任何建议不等于剧本没问题：语义层面的问题（动机、反转、潜台词）不在这里的射程内。",
      ],
    });
    expect(view.headline).toBe("没有发现结构性问题。");
    expect(view.caveat).toBe(ADVICE_CAVEAT);
    expect(view.caveat).toContain("不等于剧本没问题");
    expect(view.caveat).toContain("语义层面");
    // 后端那句与本层这句同义，去掉重复，避免同样的话在屏幕上出现两遍
    expect(view.notes).toEqual([]);
  });

  it("只有静态分析的空列表要带上「读者数据不足」这个前提", () => {
    const view = emptyAdvice({ basis: "script-only", sampleNote: "只有静态分析。" });
    expect(view.headline).toContain("没有发现结构性问题");
    expect(view.headline).toContain("读者数据不足");
    expect(view.notes).toEqual([]);
  });

  it("后端额外 notes 原样带出，缺字段也不抛", () => {
    const view = emptyAdvice({
      basis: "script+readers",
      notes: ["每条建议都带 why 与 action。", "", null as never],
    });
    expect(view.notes).toEqual(["每条建议都带 why 与 action。"]);
    expect(emptyAdvice(null).notes).toEqual([]);
    expectNoBadTokens(emptyAdvice(null));
  });
});

describe("与后端响应形状对齐（整条翻译链路跑一遍）", () => {
  // 照 `core/branch_recommendations.recommend_branch_improvements` 的返回键名写死：
  // 这里用的是 `api/projects` 的强类型，字段名一旦和后端对不上，typecheck 就会先炸。
  const payload: BranchRecommendationsOut = {
    basis: "script+readers",
    sampleNote: "静态分析 + 12 次试玩的实际选择。",
    minRuns: 10,
    recommendations: [
      {
        code: "never_selected_option",
        severity: "warn",
        priority: 68,
        confidence: "evidence",
        title: "第 2 个选项从没人选过",
        why: "12 次选择里第 2 个选项被选 0 次（它没有条件）。",
        action: "它无条件却没人选：检查它是否被排在最不显眼的位置，或它的文案读起来像「坏选项」。",
        where: "ch1/menu_1",
        evidence: { menuId: "menu_1", index: 1, selections: 12, share: 0, runs: 12 },
      },
      {
        code: "no_effect_menu",
        severity: "warn",
        priority: 50,
        confidence: "static",
        title: "这个菜单选哪个都一样",
        why: "菜单「ch2/menu_2」的 3 个选项后果完全相同（同一种出口、都不改变量）。",
        action: "让至少一个选项产生真实差异：改一个变量（好感/旗标），或让它跳向不同的 label。",
        where: "ch2/menu_2",
        evidence: { options: 3, signature: "jump:|" },
      },
      {
        code: "unreachable_ending",
        severity: "error",
        priority: 100,
        confidence: "static",
        title: "结局「真结局」写在剧本里但走不到",
        why: "它登记在案的 label 存在，但从入口顺着 jump / 选项都到不了。",
        action: "检查通往它的选项条件是否永远不成立、或上游某个 label 本身不可达。",
        where: "ending_true",
        evidence: { label: "ending_true" },
      },
    ],
    counts: { error: 1, warn: 2, info: 0, total: 3 },
    summary: { static: 2, evidence: 1, topCode: "unreachable_ending" },
    coverage: {
      labels: { total: 8, reachable: 7, ratio: 0.875 },
      choices: {
        total: 6,
        usable: 5,
        traversed: 3,
        neverTraversed: 2,
        ratio: 0.5,
        satisfiableRatio: 0.833,
      },
      paths: { count: 7, truncated: false, minLabels: 2, maxLabels: 5, avgLabels: 3.1 },
      terminals: ["ending_true"],
      score: 0.688,
    },
    notes: [
      "每条建议都带 why（依据）与 action（具体改法），不做「建议优化剧情」这种空话。",
      "没有任何建议不等于剧本没问题：语义层面的问题（动机、反转、潜台词）不在这里的射程内。",
    ],
  };

  it("basis / minRuns / action / where 全部能读出来，且没有 NaN/undefined", () => {
    const basis = basisView(payload.basis, payload.sampleNote);
    expect(basis.headline).toContain("读者实际行为");
    expect(basis.sampleNote).toContain("12 次试玩");

    const rows = adviceRows(payload);
    expect(rows.map((r) => r.severityLabel)).toEqual(["必须改", "建议改", "建议改"]);
    expect(rows[0].where).toBe("ending_true");
    expect(rows.every((r) => r.action.length > 10)).toBe(true);
    expect(rows[1].confidence.label).toBe("有读者证据");
    expect(rows[2].confidence.label).toBe("纯静态推断");

    const summary = adviceSummary(payload);
    expect(summary.headline).toBe("1 条必须改、2 条建议改：其中 1 条是「选哪个都一样」。");
    expect(summary.notes).toEqual([]);
    expect(minRunsView(payload.minRuns).hint).toContain("低于 10 次");
    expect(adviceStale(payload, { minRuns: 10, includeReaders: true }).stale).toBe(false);
    expectNoBadTokens({ rows, summary, basis });
  });

  it("后端字段缺失（旧版本 / 报错兜底）也不会渲染出 NaN，并会说明缺了什么", () => {
    const partial = { basis: "script-only", sampleNote: "", minRuns: 10 } as BranchRecommendationsOut;
    const rows = adviceRows(partial);
    expect(rows).toEqual([]);
    expect(adviceSummary(partial).notes.join("")).toContain("没有建议列表");
    const empty = emptyAdvice(partial);
    expect(empty.headline).toContain("读者数据不足");
    expect(empty.caveat).toContain("不等于剧本没问题");
    expectNoBadTokens({ rows, empty, basis: basisView(partial.basis, partial.sampleNote) });
  });
});

describe("参数变更后的失效提示", () => {
  it("门槛改了就提示下面还是旧结果，且不自动重拉", () => {
    const stale = adviceStale({ minRuns: 10, basis: "script-only" }, { minRuns: 30 });
    expect(stale.stale).toBe(true);
    expect(stale.reason).toContain("当前门槛是 30 次");
    expect(stale.reason).toContain("重新生成建议");
  });

  it("关掉「读读者数据」后，带读者数据的结果算是失效", () => {
    const stale = adviceStale({ minRuns: 10, basis: "script+readers" }, {
      minRuns: 10,
      includeReaders: false,
    });
    expect(stale.stale).toBe(true);
    expect(stale.reason).toContain("读读者数据");
  });

  it("参数一致 / 还没有结果时都不提示", () => {
    expect(
      adviceStale({ minRuns: 10, basis: "script+readers" }, { minRuns: 10, includeReaders: true })
        .stale
    ).toBe(false);
    expect(adviceStale(null, { minRuns: 10 }).stale).toBe(false);
    expect(adviceStale(null).reason).toBe("");
  });
});
