/**
 * 读者行为分析结果的"翻译层"：把 `/playtest/analytics` 的原始 JSON 变成给作者看的结论。
 *
 * 与 `lib/analysisReport.ts` 同一路子 —— 全是纯函数，不碰 DOM、不请求网络，
 * 所以每个边界（空样本、缺字段、从没人选的选项、从没人走到的结局）都能用单测钉死。
 *
 * 输入类型刻意写宽（字段全可选）并单独定义，不直接吃 `api/projects` 的强类型：
 * 后端返回的是宽松 dict，字段可能缺失；缺字段时必须降级成一句如实的说明，
 * 而不是在界面上显示 NaN / undefined。面板传进来的强类型对象天然满足这些宽松类型。
 *
 * **为什么界面上只有"第 N 个选项"**：分析响应里刻意不回选项文案（整条遥测链路都是
 * "零正文"），作者要还原"第 3 个选项是哪一个"，用 menuId + 序号回编辑器定位即可。
 */

/* ------------------------------------------------------------------ 小工具 */

function asNumber(value: unknown, fallback = 0): number {
  return typeof value === "number" && Number.isFinite(value) ? value : fallback;
}

function asText(value: unknown): string {
  return typeof value === "string" ? value : "";
}

/** 占比 → `23.5%`；缺失/非法显示 `—`（不显示 NaN）。 */
export function formatShare(share?: number | null): string {
  if (typeof share !== "number" || !Number.isFinite(share)) return "—";
  return `${(share * 100).toFixed(1)}%`;
}

/** 选项在界面上**只能**这么说：文案不在遥测里，序号才是可对照的坐标。 */
export function optionLabel(index?: number | null): string {
  if (typeof index !== "number" || !Number.isFinite(index) || index < 0) {
    return "序号缺失的选项";
  }
  return `第 ${index + 1} 个选项`;
}

/** 面板上固定的那句说明：为什么只有序号、没有文案。 */
export const OPTION_COPY_NOTE =
  "选项只显示「第 N 个选项（menuId）」：遥测链路不含任何正文，选项文案请按 menuId + 序号回编辑器对照。";

/** 开关的隐私说明（作者点开关前必须看到）。 */
export const TELEMETRY_PRIVACY_NOTE =
  "开启后才会记录读者选择；只记选项 id 与计数（menuId / 第几项 / 是否被条件挡住 / 走到了哪个结局），不记任何台词、选项文案或旁白。";

/* ---------------------------------------------------------------- 菜单与选项 */

export type LooseOption = {
  index?: number;
  selected?: number;
  share?: number;
  /** Wilson 区间（后端算的）：比例读数必须带不确定度 */
  shareCi?: ProportionCi;
  neverSelected?: boolean;
  available?: boolean;
  conditionBlockedSelections?: number;
};

/** 后端 `eval_stats.wilson_interval` 的返回形状（只取前端要用到的字段）。 */
export type ProportionCi = {
  n?: number;
  k?: number;
  p?: number | null;
  lo?: number | null;
  hi?: number | null;
  alpha?: number;
  /** 区间宽度 ≥ 半个单位区间 */
  wide?: boolean;
  /** 样本次数 < 10（「样本太少」的另一半判据） */
  thin?: boolean;
};

/**
 * 区间 → 一行短文本：`95%CI 38–96%`。
 *
 * 为什么不把区间塞进 `shareText`：那个字段是"占比本身"，很多地方（条宽、既有断言）
 * 按纯百分比解析它；区间是**附加信息**，单独一格更安全。
 */
export function ciText(ci?: ProportionCi | null): string {
  if (!ci || typeof ci.lo !== "number" || typeof ci.hi !== "number") return "";
  const pct = Math.round((1 - asNumber(ci.alpha, 0.05)) * 100);
  return `${pct}%CI ${Math.round(ci.lo * 100)}–${Math.round(ci.hi * 100)}%`;
}

/** 这条比例读数"敢不敢下结论"：样本次数少或区间很宽时不该当结论。 */
export function ciThin(ci?: ProportionCi | null): boolean {
  if (!ci) return false;
  return Boolean(ci.thin || ci.wide);
}

export type LooseMenu = {
  menuId?: string;
  chapterId?: string;
  selections?: number;
  optionCount?: number;
  options?: LooseOption[];
  neverSelected?: number[];
};

export type OptionRowView = {
  key: string;
  /** "第 3 个选项" */
  label: string;
  /** "42.9%" */
  shareText: string;
  /** "95%CI 12–73%"；后端没给区间时为空串 */
  ciText: string;
  /** 样本够不够下结论（样本次数少或区间很宽） */
  ciThin: boolean;
  /** 0~100，给条宽用 */
  percent: number;
  selected: number;
  tone: "ok" | "warn" | "muted";
  /** 一句补充：没人选 / 条件恒不成立 / 条件挡住过多少次 */
  note: string;
};

/** 单个菜单的选项占比视图：**从不被选的选项也列出来**（那才是作者要找的）。 */
export function optionRows(menu: LooseMenu | null | undefined): OptionRowView[] {
  const options = Array.isArray(menu?.options) ? menu!.options! : [];
  const never = new Set(
    (Array.isArray(menu?.neverSelected) ? menu!.neverSelected! : []).filter(
      (v): v is number => typeof v === "number"
    )
  );
  return options.map((opt, position) => {
    const index = typeof opt?.index === "number" ? opt.index : position;
    const selected = Math.max(0, asNumber(opt?.selected, 0));
    const share = asNumber(opt?.share, 0);
    const neverSelected = opt?.neverSelected ?? never.has(index);
    const unavailable = opt?.available === false;
    const blocked = Math.max(0, asNumber(opt?.conditionBlockedSelections, 0));
    const notes: string[] = [];
    if (neverSelected) notes.push(unavailable ? "从没人选（条件恒不成立）" : "从没人选");
    else if (blocked > 0) notes.push(`其中 ${blocked} 次是在条件不成立时被选的`);
    return {
      key: `${menu?.menuId ?? "menu"}#${index}`,
      label: optionLabel(index),
      shareText: formatShare(share),
      ciText: ciText(opt?.shareCi),
      ciThin: ciThin(opt?.shareCi),
      percent: Math.max(0, Math.min(100, share * 100)),
      selected,
      tone: neverSelected ? "warn" : "ok",
      note: notes.join("；"),
    };
  });
}

export type MenuView = {
  key: string;
  /** "第 2 章 · menu_1" */
  title: string;
  /** "被选 12 次 / 4 个选项" */
  summary: string;
  rows: OptionRowView[];
  /** 有人选的选项数 / 总选项数 */
  touchedText: string;
  /** 明确写出"哪几个从没人选"，而不是让作者自己扫表格 */
  neverSelectedText: string;
  notes: string[];
};

/** 一段菜单里的选择次数（用于"这个菜单有没有样本"的判断）。 */
function menuSelections(menu: LooseMenu): number {
  if (typeof menu.selections === "number" && Number.isFinite(menu.selections)) {
    return Math.max(0, menu.selections);
  }
  return (menu.options ?? []).reduce((n, o) => n + Math.max(0, asNumber(o?.selected, 0)), 0);
}

export function menuView(menu: LooseMenu, chapterName = ""): MenuView {
  const menuId = asText(menu.menuId) || "menu";
  const rows = optionRows(menu);
  const selections = menuSelections(menu);
  const neverSelected = rows.filter((r) => r.tone === "warn");
  const notes: string[] = [];
  if (selections === 0) {
    notes.push("这个菜单没有任何选择记录：要么玩家没走到这里，要么它被条件挡住了。");
  }
  if (rows.length === 0) {
    notes.push("当前剧本里解析不到这个菜单的选项（剧本改过？）：只能看到总次数，无法判断占比。");
  }
  return {
    key: `${chapterName || asText(menu.chapterId)}::${menuId}`,
    title: chapterName ? `${chapterName} · ${menuId}` : menuId,
    summary: `被选 ${selections} 次 / ${rows.length} 个选项`,
    rows,
    touchedText: `有人选过 ${rows.length - neverSelected.length} / ${rows.length} 个选项`,
    neverSelectedText:
      neverSelected.length > 0
        ? `从没人选：${neverSelected.map((r) => r.label).join("、")}`
        : "每个选项都至少被选过一次。",
    notes,
  };
}

/* ------------------------------------------------------------- 样本量与漏斗 */

export type SampleView = {
  tone: "ok" | "warn";
  /** 一句话样本量结论 */
  headline: string;
  /** 补充口径说明 */
  hint: string;
};

export function sampleView(
  sample?: { runs?: number; choices?: number; minSample?: number; sufficient?: boolean; truncated?: boolean } | null
): SampleView {
  const runs = Math.max(0, asNumber(sample?.runs, 0));
  const choices = Math.max(0, asNumber(sample?.choices, 0));
  const minSample = Math.max(1, asNumber(sample?.minSample, 10));
  const truncated = sample?.truncated === true;
  const hint = truncated
    ? "数据量超过单次分析上限，下面只统计最近一批试玩。"
    : "口径：只统计已落库的选择记录，不含任何正文；同一次试玩重复上报只补缺失的选项，不会重复计数。";
  if (runs === 0) {
    return {
      tone: "warn",
      headline: "还没有任何试玩样本。",
      hint:
        "打开试玩器完整玩一遍（走到结局）就会产生一条记录；只在试玩器里点几下而没有结束，样本要等到那次试玩收尾才会上报。" +
        hint,
    };
  }
  if (runs < minSample) {
    return {
      tone: "warn",
      headline: `样本量不足：只有 ${runs} 次试玩、${choices} 次选择（建议至少 ${minSample} 次）。`,
      hint: `下面的比例只代表这 ${runs} 个读者，不足以下结论。${hint}`,
    };
  }
  return {
    tone: "ok",
    headline: `样本量：${runs} 次试玩、${choices} 次选择（达到统计口径下限 ${minSample} 次）。`,
    hint,
  };
}

export type FunnelRowView = {
  key: string;
  /** "第 3 章 · ch3" */
  title: string;
  reached: number;
  choosingRuns: number;
  /** "流失 4 次（12.5%）" */
  dropText: string;
  tone: "ok" | "warn" | "muted";
};

export type FunnelView = {
  rows: FunnelRowView[];
  /** 结论句：哪一章流失最多 / 有没有样本 */
  verdict: string;
  notes: string[];
};

export function funnelView(
  funnel?: {
    startedRuns?: number;
    chapters?: Array<{
      chapterId?: string;
      reached?: number;
      choosingRuns?: number;
      dropFromPrevious?: number;
      dropRate?: number;
    }>;
    biggestDrop?: { chapterId?: string; dropFromPrevious?: number; dropRate?: number } | null;
    deepestChapterId?: string;
    unknownChapters?: Array<{ chapterId?: string; selections?: number }>;
  } | null,
  chapterName: (id: string) => string = (id) => id
): FunnelView {
  const started = Math.max(0, asNumber(funnel?.startedRuns, 0));
  const chapters = Array.isArray(funnel?.chapters) ? funnel!.chapters! : [];
  const rows: FunnelRowView[] = chapters.map((ch, position) => {
    const id = asText(ch?.chapterId);
    const drop = Math.max(0, asNumber(ch?.dropFromPrevious, 0));
    const dropRate = asNumber(ch?.dropRate, 0);
    return {
      key: `${id || position}`,
      title: chapterName(id) || `第 ${position + 1} 章`,
      reached: Math.max(0, asNumber(ch?.reached, 0)),
      choosingRuns: Math.max(0, asNumber(ch?.choosingRuns, 0)),
      dropText:
        position === 0 || drop === 0
          ? "没有流失"
          : `流失 ${drop} 次（${formatShare(dropRate)}）`,
      tone: drop > 0 ? "warn" : position === 0 ? "muted" : "ok",
    };
  });
  const notes: string[] = [];
  const biggest = funnel?.biggestDrop;
  let verdict: string;
  if (started === 0) {
    verdict = "还没有试玩样本，漏斗是空的。";
  } else if (rows.length === 0) {
    verdict = "当前剧本里解析不到章节顺序，漏斗算不出来（选择记录仍然有效）。";
  } else if (biggest && asNumber(biggest.dropFromPrevious, 0) > 0) {
    const name = chapterName(asText(biggest.chapterId)) || asText(biggest.chapterId);
    verdict = `流失最多的一章：${name}（流失 ${asNumber(
      biggest.dropFromPrevious,
      0
    )} 次，流失率 ${formatShare(asNumber(biggest.dropRate, 0))}）。`;
  } else {
    verdict = "没有任何一章出现流失：读到这里的人基本都读完了。";
  }
  if (rows.length > 0 && rows.every((r) => r.choosingRuns === 0)) {
    notes.push(
      "所有章节都没有选择记录：这批试玩可能没经过任何菜单（纯阅读），此时分支覆盖率恒为 0，不代表分支没人走。"
    );
  }
  const unknown = Array.isArray(funnel?.unknownChapters) ? funnel!.unknownChapters! : [];
  if (unknown.length > 0) {
    notes.push(
      `有 ${unknown.length} 个选择记录里的 chapter_id 不在当前章节顺序里（章节被删或改名？）：它们不计入漏斗。`
    );
  }
  notes.push(
    "「到达」由客户端上报的章节数与选择记录里出现的最大章序号共同推断：试玩器一次只演一章，所以跨章流失要小心解读。"
  );
  return { rows, verdict, notes };
}

/* ---------------------------------------------------------------- 结局分布 */

export type EndingRowView = {
  key: string;
  title: string;
  runs: number;
  shareText: string;
  tone: "ok" | "warn";
  note: string;
};

export type EndingsView = {
  rows: EndingRowView[];
  /** "登记了 4 个结局，实际只有 2 个被走到" */
  headline: string;
  /** 从没人走到的结局（这是作者最想看到的一句） */
  neverReachedText: string;
  neverReached: Array<{ label: string; name: string; reachableInScript: boolean }>;
  notes: string[];
};

export function endingsView(
  endings?: {
    reached?: Array<{
      label?: string;
      name?: string;
      runs?: number;
      share?: number;
      declared?: boolean;
      isStaticTerminal?: boolean;
    }>;
    declaredTotal?: number;
    declaredReached?: number;
    neverReached?: Array<{ label?: string; name?: string; reachableInScript?: boolean }>;
    unknownEndingLabels?: unknown[];
    declaredWithoutLabel?: unknown[];
    unfinishedRuns?: number;
  } | null
): EndingsView {
  const reached = Array.isArray(endings?.reached) ? endings!.reached! : [];
  const rows: EndingRowView[] = reached.map((row, position) => {
    const label = asText(row?.label) || "(没有 label)";
    const declared = row?.declared === true;
    const terminal = row?.isStaticTerminal === true;
    const notes: string[] = [];
    if (!declared) {
      notes.push(
        terminal
          ? "没登记为结局，但在控制流里确实是个终点"
          : "既没登记为结局，也不在静态分析的终点里"
      );
    }
    return {
      key: `${label}-${position}`,
      title: asText(row?.name) || label,
      runs: Math.max(0, asNumber(row?.runs, 0)),
      shareText: formatShare(asNumber(row?.share, 0)),
      tone: declared ? "ok" : "warn",
      note: notes.join("；"),
    };
  });
  const never = (Array.isArray(endings?.neverReached) ? endings!.neverReached! : []).map(
    (row) => ({
      label: asText(row?.label),
      name: asText(row?.name) || asText(row?.label),
      reachableInScript: row?.reachableInScript === true,
    })
  );
  const declaredTotal = Math.max(0, asNumber(endings?.declaredTotal, 0));
  const declaredReached = Math.max(0, asNumber(endings?.declaredReached, 0));
  const notes: string[] = [];
  const unknown = Array.isArray(endings?.unknownEndingLabels) ? endings!.unknownEndingLabels! : [];
  if (unknown.length > 0) {
    notes.push(
      `有 ${unknown.length} 个结局名既没登记、也不在静态分析的终点里：可能漏登记，也可能是客户端报上来的自造名字。`
    );
  }
  const noLabel = Array.isArray(endings?.declaredWithoutLabel) ? endings!.declaredWithoutLabel! : [];
  if (noLabel.length > 0) {
    notes.push(`有 ${noLabel.length} 个已登记结局没有 label，没法与读者实际走到的结局对账。`);
  }
  const unfinished = Math.max(0, asNumber(endings?.unfinishedRuns, 0));
  if (unfinished > 0) {
    notes.push(`有 ${unfinished} 次试玩没走到任何结局就结束了（中途退出 / 只玩了一章）。`);
  }
  return {
    rows,
    headline:
      declaredTotal > 0
        ? `登记了 ${declaredTotal} 个结局，读者实际走到 ${declaredReached} 个。`
        : "这个工程还没有登记任何结局：下面是读者实际走到的终点 label。",
    neverReachedText:
      never.length > 0
        ? `从没人走到的结局（${never.length}）：${never.map((n) => n.name).join("、")}`
        : // 只有"确实登记过结局、而且没有任何一个被落下"时才能说这句：
          // 工程没登记结局、或压根没样本时，说"都走到了"是个假结论。
          declaredTotal > 0 && reached.length > 0
          ? "已登记的结局都至少被走到了。"
          : "",
    neverReached: never,
    notes,
  };
}

/* ---------------------------------------------------------------- 覆盖率 */

export type CoverageView = {
  /** "读者碰过的选项：3 / 8（37.5%）" */
  text: string;
  percent: number;
  tone: "ok" | "warn" | "bad";
  /** 一次都没被碰过的菜单（不是选项） */
  menusNeverTouchedText: string;
  notes: string[];
};

export function coverageView(
  coverage?: {
    availableOptions?: number;
    observedOptions?: number;
    ratio?: number;
    menusTotal?: number;
    menusTouched?: number;
    menusNeverTouched?: string[];
    unmappedSelections?: number;
    selectedUnavailableOptions?: Array<{ menuId?: string; index?: number }>;
  } | null
): CoverageView {
  const available = Math.max(0, asNumber(coverage?.availableOptions, 0));
  const observed = Math.max(0, asNumber(coverage?.observedOptions, 0));
  const ratio = asNumber(coverage?.ratio, available ? observed / available : 0);
  const menusTotal = Math.max(0, asNumber(coverage?.menusTotal, 0));
  const menusTouched = Math.max(0, asNumber(coverage?.menusTouched, 0));
  const neverTouched = Array.isArray(coverage?.menusNeverTouched)
    ? coverage!.menusNeverTouched!.map((m) => asText(m)).filter(Boolean)
    : [];
  const notes: string[] = [];
  const unavailable = Array.isArray(coverage?.selectedUnavailableOptions)
    ? coverage!.selectedUnavailableOptions!
    : [];
  if (unavailable.length > 0) {
    notes.push(
      `有 ${unavailable.length} 个「静态分析判定不可选」的选项被读者真的选了：优先检查条件求值（运行时的状态可能比分析器认为的更宽松）。`
    );
  }
  const unmapped = Math.max(0, asNumber(coverage?.unmappedSelections, 0));
  if (unmapped > 0) {
    notes.push(
      `有 ${unmapped} 条选择在剧本里找不到对应的选项（菜单被删/改过？）：它们不参与覆盖率。`
    );
  }
  if (available === 0) {
    notes.push(
      "当前剧本里没有「条件可满足的选项」，覆盖率无从计算（先跑一次分支推理确认菜单解析正常）。"
    );
  }
  return {
    text: `读者碰过的选项：${observed} / ${available}（${formatShare(ratio)}），碰过的菜单：${menusTouched} / ${menusTotal}`,
    percent: Math.max(0, Math.min(100, ratio * 100)),
    tone: available === 0 ? "bad" : ratio >= 0.6 ? "ok" : "warn",
    menusNeverTouchedText:
      neverTouched.length > 0
        ? `没有任何读者碰过的菜单（${neverTouched.length}）：${neverTouched.slice(0, 8).join("、")}`
        : "每个菜单都至少有一名读者碰过。",
    notes,
  };
}

/* -------------------------------------------------------------- 开关文案 */

export type TelemetrySwitchCopy = {
  title: string;
  hint: string;
  /** 未开启时用于面板正中央的那句话 */
  emptyText: string;
};

export function telemetrySwitchCopy(enabled: boolean): TelemetrySwitchCopy {
  return enabled
    ? {
        title: "读者行为采集：已开启",
        hint: TELEMETRY_PRIVACY_NOTE,
        emptyText: "已开启采集，但还没有任何样本：让试玩器完整玩一遍（走到结局）就会出现数据。",
      }
    : {
        title: "读者行为采集：未开启",
        hint: TELEMETRY_PRIVACY_NOTE,
        emptyText:
          "未开启，没有数据。开启后才会记录读者选择；开启之前玩过的试玩不会被补记（没有留存任何数据）。",
      };
}
