/**
 * 深度分析结果的"翻译层"：把后端四个只读分析端点的原始 JSON，变成给作者看的结论。
 *
 * 为什么单独一层：后端返回的是**事实**（哪个 code、哪一章、几个选项），界面上要说的是
 * **话**（"2 个错误、5 个警告：其中 1 处是死循环、2 处是走不到的选项"）。这层全是纯函数，
 * 不碰 DOM、不请求网络，所以每个边界都能用单测钉死（空列表、n=0、缺字段）。
 *
 * 输入类型刻意写成"字段全可选"：后端返回的是宽松 dict，字段可能缺失，
 * 缺字段时必须降级成一句如实的说明，而不是在界面上显示 NaN / undefined。
 */

/* ------------------------------------------------------------------ 结论等级 */

export type FindingSeverity = "error" | "warn" | "info" | "other";

const SEVERITY_ORDER: readonly FindingSeverity[] = ["error", "warn", "info", "other"];

const SEVERITY_LABELS: Record<FindingSeverity, string> = {
  error: "错误",
  warn: "警告",
  info: "提示",
  other: "其它",
};

export type SeverityCounts = Record<FindingSeverity, number>;

/** 宽松的结论形状（`branch-report` / `continuity` 的 findings 元素）。 */
export type FindingInput = {
  severity?: string;
  code?: string;
  message?: string;
  chapterId?: string;
  label?: string;
  source?: string;
};

export function severityLabel(severity: FindingSeverity): string {
  return SEVERITY_LABELS[severity];
}

/** 后端只保证 error / warn / info；未知等级归到 other，不许静默丢掉一条结论。 */
export function normalizeSeverity(raw?: string | null): FindingSeverity {
  const s = (raw ?? "").trim().toLowerCase();
  if (s === "error" || s === "warn" || s === "info") return s;
  return "other";
}

export function severityCounts(findings?: readonly FindingInput[] | null): SeverityCounts {
  const out: SeverityCounts = { error: 0, warn: 0, info: 0, other: 0 };
  for (const f of findings ?? []) {
    if (!f) continue;
    out[normalizeSeverity(f.severity)] += 1;
  }
  return out;
}

/* ---------------------------------------------------------------- code 字典 */

/**
 * code → 给作者看的短名。
 *
 * 只登记后端真实会发的 code（见 backend/app/core/branch_analysis.py 与
 * continuity_graph.py）；没登记的 code 原样显示 —— 宁可露出代号，也不编一个
 * 可能说错的中文名。短名刻意保持 2–6 字，因为总述里会连着写好几个。
 */
const CODE_LABELS: Record<string, string> = {
  // —— 分支结构（branch_analysis.py）——
  ending_label_missing: "结局指向不存在的 label",
  ending_no_label: "结局没登记 label",
  ending_duplicate_label: "结局挤在同一个 label",
  ending_undeclared: "可达终点没登记为结局",
  menu_no_effect: "选哪个都一样的菜单",
  choice_empty_text: "没有文案的选项",
  choice_inline_empty: "空选项",
  choice_never_available: "永远看不到的选项",
  choice_duplicate_text: "重复的选项文案",
  choice_duplicate_condition: "重复的选项条件",
  menu_always_empty: "没有可选项的死菜单",
  menu_single_option: "只有一个选项的菜单",
  dead_block: "永远不会执行的块",
  chapter_end_no_exit: "章末没有出口",
  dangling_jump: "跳转目标不存在",
  duplicate_label: "重复定义的 label",
  unreachable_label: "走不到的 label",
  loop_no_exit: "死循环",
  plot_cycle: "回路",
  invalid_condition: "条件写法不合法",
  condition_type_mismatch: "条件类型不匹配",
  condition_never_true: "永远不成立的条件",
  choice_never_traversed: "走不到的选项",
  // —— 跨章事实（continuity_graph.py）——
  unknown_speaker: "未登记的说话人",
  dangling_character_link: "悬空的关系边",
  dangling_location_link: "悬空的地点通路",
  alias_collision: "重名角色",
  unused_character_card: "没用上的角色卡",
  unknown_location_tag: "未知的地点标签",
  timeline_bad_ref: "时间线挂到不存在的章节",
  duplicate_timeline_event: "重复的时间线事件",
  timeline_order_conflict: "时间线顺序矛盾",
  death_then_speaks: "死亡后仍然出场",
};

export function codeLabel(code?: string | null): string {
  const key = (code ?? "").trim();
  if (!key) return "未标注类别的问题";
  return CODE_LABELS[key] ?? key;
}

/* -------------------------------------------------------------------- 分组 */

export type SeverityGroup = {
  severity: FindingSeverity;
  label: string;
  findings: FindingInput[];
};

/** 按 severity 分组，顺序固定 error → warn → info → other；空输入返回空数组。 */
export function groupBySeverity(findings?: readonly FindingInput[] | null): SeverityGroup[] {
  const buckets = new Map<FindingSeverity, FindingInput[]>();
  for (const f of findings ?? []) {
    if (!f) continue;
    const s = normalizeSeverity(f.severity);
    const list = buckets.get(s);
    if (list) list.push(f);
    else buckets.set(s, [f]);
  }
  const out: SeverityGroup[] = [];
  for (const s of SEVERITY_ORDER) {
    const list = buckets.get(s);
    if (list) out.push({ severity: s, label: SEVERITY_LABELS[s], findings: list });
  }
  return out;
}

export type CodeGroup = {
  code: string;
  label: string;
  count: number;
  /** 这个 code 下最严重的一条的等级 */
  severity: FindingSeverity;
  findings: FindingInput[];
};

/** 按 code 归类：先按最严重的等级，再按条数从多到少。 */
export function groupByCode(findings?: readonly FindingInput[] | null): CodeGroup[] {
  const buckets = new Map<string, FindingInput[]>();
  for (const f of findings ?? []) {
    if (!f) continue;
    const code = (f.code ?? "").trim() || "unknown";
    const list = buckets.get(code);
    if (list) list.push(f);
    else buckets.set(code, [f]);
  }
  const rows: CodeGroup[] = [];
  for (const [code, list] of buckets) {
    let severity: FindingSeverity = "other";
    for (const f of list) {
      const s = normalizeSeverity(f.severity);
      if (SEVERITY_ORDER.indexOf(s) < SEVERITY_ORDER.indexOf(severity)) severity = s;
    }
    rows.push({ code, label: codeLabel(code), count: list.length, severity, findings: list });
  }
  rows.sort((a, b) => {
    const bySeverity = SEVERITY_ORDER.indexOf(a.severity) - SEVERITY_ORDER.indexOf(b.severity);
    if (bySeverity !== 0) return bySeverity;
    if (b.count !== a.count) return b.count - a.count;
    return a.code.localeCompare(b.code);
  });
  return rows;
}

export type SummaryOptions = {
  /** 总述里最多点名几类问题（默认 3，避免一句话读到断气） */
  maxCategories?: number;
};

/**
 * 一句中文总述，例如：
 * 「2 个错误、5 个警告：其中 1 处是死循环、2 处是走不到的选项。」
 */
export function summarizeFindings(
  findings?: readonly FindingInput[] | null,
  opts: SummaryOptions = {}
): string {
  const list = (findings ?? []).filter((f): f is FindingInput => Boolean(f));
  if (list.length === 0) return "没有发现问题。";

  const counts = severityCounts(list);
  const head: string[] = [];
  if (counts.error > 0) head.push(`${counts.error} 个错误`);
  if (counts.warn > 0) head.push(`${counts.warn} 个警告`);
  if (counts.info > 0) head.push(`${counts.info} 条提示`);
  if (counts.other > 0) head.push(`${counts.other} 条其它`);

  const maxCategories = Math.max(0, opts.maxCategories ?? 3);
  const details = groupByCode(list)
    .slice(0, maxCategories)
    .map((g) => `${g.count} 处是${g.label}`);

  const headText = head.join("、");
  if (details.length === 0) return `${headText}。`;
  return `${headText}：其中 ${details.join("、")}。`;
}

/* ---------------------------------------------------------------- 章节标题 */

/** 章节 id → 标题（空标题 / 空 id 不入表）。 */
export function chapterTitleMap(
  chapters?: ReadonlyArray<{ id?: string; title?: string }> | null
): Record<string, string> {
  const out: Record<string, string> = {};
  for (const c of chapters ?? []) {
    if (!c) continue;
    const id = (c.id ?? "").trim();
    const title = (c.title ?? "").trim();
    if (id && title) out[id] = title;
  }
  return out;
}

/** 有标题就显示标题，找不到就退回 id；没有 id 返回空串（界面按"全篇"处理）。 */
export function chapterLabel(
  chapterId?: string | null,
  titles?: Record<string, string> | null
): string {
  const id = (chapterId ?? "").trim();
  if (!id) return "";
  const title = titles?.[id];
  return title && title.trim() ? title.trim() : id;
}

export type FindingRow = {
  key: string;
  severity: FindingSeverity;
  severityLabel: string;
  code: string;
  codeLabel: string;
  message: string;
  chapterId: string;
  /** 章节标题（找不到退回 id；无 chapterId 时为空串） */
  chapter: string;
  label: string;
};
/** 每条结论 → 界面直接可渲染的一行（severity + 中文 message + 所在章节）。 */
export function findingRows(
  findings?: readonly FindingInput[] | null,
  titles?: Record<string, string> | null
): FindingRow[] {
  const rows: FindingRow[] = [];
  (findings ?? []).forEach((f, i) => {
    if (!f) return;
    const severity = normalizeSeverity(f.severity);
    const code = (f.code ?? "").trim();
    const chapterId = (f.chapterId ?? "").trim();
    rows.push({
      key: `${code || "finding"}-${chapterId}-${i}`,
      severity,
      severityLabel: SEVERITY_LABELS[severity],
      code,
      codeLabel: codeLabel(code),
      message: (f.message ?? "").trim() || "（后端没有给出说明）",
      chapterId,
      chapter: chapterLabel(chapterId, titles),
      label: (f.label ?? "").trim(),
    });
  });
  return rows;
}

export type FindingGroupView = {
  code: string;
  label: string;
  severity: FindingSeverity;
  count: number;
  /** 实际要渲染的行（受 maxRowsPerGroup 限制） */
  rows: FindingRow[];
  /** 被展示上限挡住的条数 */
  hidden: number;
};

/**
 * 结论 → 界面分组：同 code 归一块，块内按上限截断（后端可能一次报几百条
 * 走不到的 label，全渲染出来浏览器会卡，作者也读不完）。
 */
export function findingGroups(
  findings?: readonly FindingInput[] | null,
  titles?: Record<string, string> | null,
  opts: { maxRowsPerGroup?: number; expandAll?: boolean } = {}
): FindingGroupView[] {
  const rows = findingRows(findings, titles);
  const byCode = new Map<string, FindingRow[]>();
  for (const row of rows) {
    const key = row.code || "unknown";
    const list = byCode.get(key);
    if (list) list.push(row);
    else byCode.set(key, [row]);
  }
  const max = Math.max(0, opts.maxRowsPerGroup ?? 6);
  const expandAll = Boolean(opts.expandAll);
  return groupByCode(findings).map((g) => {
    const all = byCode.get(g.code) ?? [];
    const shown = expandAll ? all : all.slice(0, max);
    return {
      code: g.code,
      label: g.label,
      severity: g.severity,
      count: g.count,
      rows: shown,
      hidden: all.length - shown.length,
    };
  });
}

/**
 * 跨章体检里"机器也拿不准"的计数键 → 中文说明。
 *
 * 这些不是通过项，是**查不了**的项（缺地点表、事件没挂章节……）。未登记的键原样显示。
 */
const UNKNOWN_KEY_LABELS: Record<string, string> = {
  characterWithoutAnyName: "角色卡一个名字都没有，没法比对",
  locationTableEmpty: "还没有建地点表，地点相关检查整条没跑",
  showImageNotClassified: "show 的图既不是立绘也不是背景，没法归类",
  timelineWithoutChapter: "时间线事件没有挂章节",
  timelineOrderUncheckable: "事件挂的章节不存在，顺序查不了",
  timelineOrderNotNumeric: "事件的 order 不是数字，顺序查不了",
  timelineOrderTies: "不同章节的 order 相同，排序有歧义（不算矛盾）",
  timelineOrderFindingsTruncated: "顺序矛盾报到达上限，可能还有没报出来的",
  deathEvidenceWithoutChapter: "找到死亡痕迹但定位不到章节，没敢报",
  deathMentionedInCardOnly: "只在角色卡里提到过死亡",
};

export function unknownKeyLabel(key?: string | null): string {
  const k = (key ?? "").trim();
  if (!k) return "";
  return UNKNOWN_KEY_LABELS[k] ?? k;
}

/* ------------------------------------------------------------------ 覆盖率 */

export type CoverageInput = {
  labels?: { total?: number; reachable?: number; ratio?: number };
  choices?: {
    total?: number;
    usable?: number;
    traversed?: number;
    neverTraversed?: number;
    ratio?: number;
    satisfiableRatio?: number;
  };
  paths?: {
    count?: number;
    truncated?: boolean;
    minLabels?: number;
    maxLabels?: number;
    avgLabels?: number;
  };
  score?: number;
};

export type CoverageView = {
  labelsTotal: number;
  labelsReachable: number;
  labelsPercent: number;
  choicesTotal: number;
  choicesUsable: number;
  choicesTraversed: number;
  /** 条件永远不可能成立 → 玩家永远看不到 */
  impossibleChoices: number;
  /** 条件成立，但枚举到的路径一条都没走到 */
  neverTraversedChoices: number;
  choicesPercent: number;
  /** 后端有没有给出"路径覆盖"信息 */
  pathsKnown: boolean;
  pathsCount: number;
  pathsTruncated: boolean;
  scorePercent: number;
  labelsText: string;
  choicesText: string;
  /** 明确区分"永远看不到"与"没有路走到" */
  choicesNote: string;
  pathsText: string;
  verdict: string;
};

function num(v: number | undefined | null): number {
  return typeof v === "number" && Number.isFinite(v) ? v : 0;
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v));
}

function percent(part: number, whole: number): number {
  if (whole <= 0) return 0;
  return Math.round((part / whole) * 100);
}

/**
 * 分支覆盖率 → 百分比 + 人话。
 *
 * 关键区分（这正是这个端点存在的理由）：
 * - `usable` < `total`：条件**永远不可能成立**，玩家永远看不到这些选项；
 * - `neverTraversed`：条件成立（玩家看得见），但枚举到的可达路径一条都没经过它。
 * 两者都会让"覆盖率"掉下来，但修法完全不同，所以文案必须分开说。
 */
export function viewCoverage(coverage?: CoverageInput | null): CoverageView {
  const labelsTotal = num(coverage?.labels?.total);
  const labelsReachable = clamp(num(coverage?.labels?.reachable), 0, labelsTotal);

  const choicesTotal = num(coverage?.choices?.total);
  // usable 缺失时不能反推"哪些选项玩家看不到"，保守按"全部看得见"处理
  const choicesUsable =
    coverage?.choices?.usable === undefined
      ? choicesTotal
      : clamp(num(coverage.choices.usable), 0, choicesTotal);
  const impossibleChoices = Math.max(0, choicesTotal - choicesUsable);

  const traversedRaw = coverage?.choices?.traversed;
  const neverRaw = coverage?.choices?.neverTraversed;
  const pathsKnown = traversedRaw !== undefined || neverRaw !== undefined;
  let choicesTraversed: number;
  let neverTraversedChoices: number;
  if (traversedRaw !== undefined) {
    choicesTraversed = clamp(num(traversedRaw), 0, choicesUsable);
    neverTraversedChoices =
      neverRaw === undefined
        ? Math.max(0, choicesUsable - choicesTraversed)
        : clamp(num(neverRaw), 0, choicesUsable);
  } else if (neverRaw !== undefined) {
    neverTraversedChoices = clamp(num(neverRaw), 0, choicesUsable);
    choicesTraversed = Math.max(0, choicesUsable - neverTraversedChoices);
  } else {
    choicesTraversed = 0;
    neverTraversedChoices = 0;
  }

  const pathsCount = num(coverage?.paths?.count);
  const pathsTruncated = Boolean(coverage?.paths?.truncated);
  const minLabels = num(coverage?.paths?.minLabels);
  const maxLabels = num(coverage?.paths?.maxLabels);

  const scorePercent =
    coverage?.score === undefined
      ? pathsKnown
        ? percent(labelsReachable + choicesTraversed, labelsTotal + choicesTotal)
        : percent(labelsReachable, labelsTotal)
      : Math.round(clamp(num(coverage.score), 0, 1) * 100);

  const labelsText =
    labelsTotal > 0
      ? `可达 label ${labelsReachable}/${labelsTotal}（${percent(labelsReachable, labelsTotal)}%）`
      : "没有 label（剧本还是空的）";

  const choicesText =
    choicesTotal > 0
      ? `选项走过 ${choicesTraversed}/${choicesTotal}（${percent(choicesTraversed, choicesTotal)}%）`
      : "没有可统计的选项";

  const notes: string[] = [];
  if (choicesTotal > 0) {
    if (impossibleChoices > 0) {
      notes.push(`${impossibleChoices} 个选项的条件永远不可能成立，玩家永远看不到`);
    }
    if (neverTraversedChoices > 0) {
      notes.push(`${neverTraversedChoices} 个选项条件成立、但没有任何可达路径走到`);
    }
    if (!pathsKnown) {
      notes.push("后端没有给出路径覆盖信息，这里只统计了看得见的选项");
    }
    if (notes.length === 0) notes.push("所有选项都既看得见、又走得通");
  }

  let pathsText: string;
  if (pathsCount > 0) {
    const lengthPart = maxLabels > 0 ? `，路径长度 ${minLabels}–${maxLabels} 步` : "";
    pathsText = `枚举到 ${pathsCount} 条路径${lengthPart}${
      pathsTruncated ? "（已到枚举上限，组合没列完）" : ""
    }`;
  } else {
    pathsText = "没有枚举到任何路径";
  }

  const verdictParts: string[] = [];
  if (labelsTotal === 0 && choicesTotal === 0) {
    verdictParts.push("剧本里还没有可统计的分支结构");
  } else {
    verdictParts.push(`分支覆盖 ${scorePercent}%`);
    if (impossibleChoices > 0) verdictParts.push(`${impossibleChoices} 个选项玩家永远看不到`);
    if (neverTraversedChoices > 0) {
      verdictParts.push(`${neverTraversedChoices} 个选项没有任何路径走到`);
    }
    if (
      choicesTotal > 0 &&
      impossibleChoices === 0 &&
      neverTraversedChoices === 0 &&
      pathsKnown
    ) {
      verdictParts.push("所有选项都看得见、走得通");
    }
  }

  return {
    labelsTotal,
    labelsReachable,
    labelsPercent: percent(labelsReachable, labelsTotal),
    choicesTotal,
    choicesUsable,
    choicesTraversed,
    impossibleChoices,
    neverTraversedChoices,
    choicesPercent: percent(choicesTraversed, choicesTotal),
    pathsKnown,
    pathsCount,
    pathsTruncated,
    scorePercent,
    labelsText,
    choicesText,
    choicesNote: notes.join("；"),
    pathsText,
    verdict: `${verdictParts.join("，")}。`,
  };
}

/* ------------------------------------------------------------------ 声线漂移 */

export type DriftLevel = "ok" | "watch" | "drift" | "unknown";
export type DriftTone = "ok" | "watch" | "drift" | "muted";

export type DriftView = {
  level: DriftLevel;
  tone: DriftTone;
  label: string;
  hint: string;
};

/** drift 等级 → 颜色语义 + 文案（ok 绿 / watch 黄 / drift 红 / 未知灰）。 */
export function driftView(level?: string | null): DriftView {
  const s = (level ?? "").trim().toLowerCase();
  if (s === "ok") {
    return {
      level: "ok",
      tone: "ok",
      label: "像本人",
      hint: "这一章的说话方式与该角色其余章节一致。",
    };
  }
  if (s === "watch") {
    return {
      level: "watch",
      tone: "watch",
      label: "留意",
      hint: "略有出入，值得抽查一两句。",
    };
  }
  if (s === "drift") {
    return {
      level: "drift",
      tone: "drift",
      label: "跑味",
      hint: "这一章明显不像该角色，建议逐句回看。",
    };
  }
  return {
    level: "unknown",
    tone: "muted",
    label: "未评估",
    hint: "后端没有给出漂移等级。",
  };
}

/** `calibrated: false` 必须如实说明阈值不是自校准来的，否则结论会被当成定论。 */
export function calibrationNote(
  calibration?: { calibrated?: boolean; samples?: number } | null
): string {
  if (!calibration) return "没有自校准信息：阈值来源未知。";
  const samples = num(calibration.samples);
  if (calibration.calibrated) {
    return `阈值由该角色自己的台词分布自校准（留一法，${samples} 个样本）。`;
  }
  return `样本不足（只有 ${samples} 个），未自校准：阈值用的是默认经验值，结论仅供参考。`;
}

export type VoiceChapterInput = {
  characterId?: string;
  displayName?: string;
  chapterId?: string;
  ready?: boolean;
  utteranceCount?: number;
  drift?: number;
  level?: string;
  watchThreshold?: number;
  driftThreshold?: number;
  reasons?: string[];
  flaggedLines?: Array<{ text?: string; drift?: number; reason?: string }>;
};

export type VoiceCharacterInput = {
  characterId?: string;
  displayName?: string;
  ready?: boolean;
  utteranceCount?: number;
  reason?: string;
  chaptersSpoken?: number;
  calibration?: { calibrated?: boolean; samples?: number };
  signaturePhrases?: Array<{ phrase?: string; count?: number }>;
  chapters?: VoiceChapterInput[];
  driftChapters?: string[];
};

export type VoiceReportInput = {
  characters?: VoiceCharacterInput[];
  closestPairs?: Array<{ a?: string; b?: string; aId?: string; bId?: string; distance?: number }>;
  confusablePairs?: Array<{ a?: string; b?: string; aId?: string; bId?: string; distance?: number }>;
  notes?: string[];
};

export type VoiceSummaryView = {
  totalCharacters: number;
  evaluatedCharacters: number;
  /** 台词不足、后端明确说"不评估"的角色数 */
  skippedCharacters: number;
  evaluatedChapters: number;
  driftChapters: number;
  watchChapters: number;
  confusablePairs: number;
  text: string;
};

/** 声线报告总述：评估了几个角色 / 几处跑味，以及"谁没被评估"。 */
export function viewVoiceReport(report?: VoiceReportInput | null): VoiceSummaryView {
  const characters = (report?.characters ?? []).filter(Boolean);
  const evaluated = characters.filter((c) => c.ready);
  const skipped = characters.length - evaluated.length;

  let evaluatedChapters = 0;
  let driftChapters = 0;
  let watchChapters = 0;
  for (const c of evaluated) {
    for (const ch of c.chapters ?? []) {
      if (!ch) continue;
      evaluatedChapters += 1;
      const tone = driftView(ch.level).level;
      if (tone === "drift") driftChapters += 1;
      else if (tone === "watch") watchChapters += 1;
    }
  }
  const confusablePairs = (report?.confusablePairs ?? []).filter(Boolean).length;

  const parts: string[] = [];
  if (characters.length === 0) {
    parts.push("还没有可评估的角色（对白太少，或剧本还没写对白）");
  } else {
    parts.push(
      `评估了 ${evaluated.length} 个角色、${evaluatedChapters} 处「角色-章」：` +
        `${driftChapters} 处明显跑味、${watchChapters} 处值得留意`
    );
    if (confusablePairs > 0) {
      parts.push(`${confusablePairs} 对角色声线过于接近（读者可能分不清谁在说话）`);
    }
    if (skipped > 0) {
      parts.push(`另有 ${skipped} 个角色台词不足，未评估`);
    }
  }
  return {
    totalCharacters: characters.length,
    evaluatedCharacters: evaluated.length,
    skippedCharacters: skipped,
    evaluatedChapters,
    driftChapters,
    watchChapters,
    confusablePairs,
    text: `${parts.join("；")}。`,
  };
}

/* -------------------------------------------------------------- 分片扫描覆盖 */

export type ScanCoverageInput = {
  chaptersTotal?: number;
  chaptersWithText?: number;
  chaptersScanned?: number;
  coverageRatio?: number;
  windowsPlanned?: number;
  windowsRun?: number;
  windowsFailed?: number;
  truncatedChapters?: string[];
  maxWindowsHit?: boolean;
  textTruncatedChapters?: string[];
  chaptersWithBlocksButNoText?: number;
};

export type ScanCoverageView = {
  scanned: number;
  /** 分母：有正文、可以送审的章节数（缺失时退回全书章数） */
  scannable: number;
  total: number;
  percent: number;
  /** 「本次扫了 12/28 章（43%）」—— 静默截断就是死在这句话上 */
  headline: string;
  windowsText: string;
  missedChapterIds: string[];
  missedText: string;
  /** 逐章截断 / 有块无正文等如实补充 */
  notes: string[];
  /** 全书每一个可扫章节都进了成功的窗口 */
  complete: boolean;
};

/**
 * 分片扫描的覆盖率 → 一句话 + 明细。
 *
 * 必须出现"这次扫了多少章 / 共多少章"：旧实现只扫前 14 章且不告诉作者，
 * 于是第 30 章有没有被检查过，作者无从判断。这里把它摆在第一句。
 */
export function viewScanCoverage(coverage?: ScanCoverageInput | null): ScanCoverageView {
  const total = num(coverage?.chaptersTotal);
  const withText = num(coverage?.chaptersWithText);
  const scannable = withText > 0 ? withText : total;
  const scanned = clamp(num(coverage?.chaptersScanned), 0, Math.max(scannable, 0));
  const coveragePercent = percent(scanned, scannable);

  const headline =
    scannable > 0
      ? `本次扫了 ${scanned}/${scannable} 章（${coveragePercent}%）` +
        (total > scannable ? `；全书共 ${total} 章，其中 ${total - scannable} 章没有可送审的正文` : "")
      : total > 0
        ? `全书 ${total} 章都没有可送审的正文，本轮没有扫到任何内容`
        : "还没有章节，本轮没有扫到任何内容";

  const windowsRun = num(coverage?.windowsRun);
  const windowsPlanned = num(coverage?.windowsPlanned);
  const windowsFailed = num(coverage?.windowsFailed);
  const windowsText =
    windowsRun > 0
      ? `分 ${windowsRun} 个窗口扫描` +
        (windowsPlanned > windowsRun ? `（原计划 ${windowsPlanned} 个）` : "") +
        (windowsFailed > 0 ? `，其中 ${windowsFailed} 个窗口失败：那些章节本轮没有结论` : "")
      : "没有任何窗口真正跑起来";

  const missedChapterIds = (coverage?.truncatedChapters ?? [])
    .filter((id): id is string => Boolean(id && id.trim()))
    .map((id) => id.trim());
  const missedText =
    missedChapterIds.length > 0
      ? `未扫到的章节：${missedChapterIds.join("、")}`
      : "";

  const notes: string[] = [];
  if (coverage?.maxWindowsHit) {
    notes.push("受 max_windows 预算限制提前停了：预算可以砍，但没扫到的章节都列在上面");
  }
  const trimmed = (coverage?.textTruncatedChapters ?? []).filter(Boolean).length;
  if (trimmed > 0) notes.push(`${trimmed} 章正文超过单章上限，截断后才送审`);
  const noText = num(coverage?.chaptersWithBlocksButNoText);
  if (noText > 0) notes.push(`${noText} 章有脚本块但没产出可送审的文本`);

  return {
    scanned,
    scannable,
    total,
    percent: coveragePercent,
    headline,
    windowsText,
    missedChapterIds,
    missedText,
    notes,
    complete: scannable > 0 && scanned >= scannable && windowsFailed === 0,
  };
}

export type ScanResultInput = {
  coverage?: ScanCoverageInput | null;
  ceilingNote?: string | null;
  issues?: readonly ScanIssueInput[] | null;
  error?: string | null;
};

function trimTail(text: string): string {
  return text.replace(/[。；;]+$/u, "");
}

/** 扫描结果的一句话人话：扫了多少章 / 共多少章 + 分窗情况 + 后端的截断说明。 */
export function scanCoverageSentence(scan?: ScanResultInput | null): string {
  const view = viewScanCoverage(scan?.coverage);
  const parts = [trimTail(view.headline), trimTail(view.windowsText)];
  const ceiling = trimTail((scan?.ceilingNote ?? "").trim());
  if (ceiling) parts.push(ceiling);
  else if (view.missedText) parts.push(trimTail(view.missedText));
  return `${parts.filter(Boolean).join("；")}。`;
}

/* -------------------------------------------------------------- 扫描出的冲突 */

export type ScanIssueInput = {
  category?: string;
  severity?: string;
  chapterIds?: string[];
  quote?: string;
  description?: string;
  suggestion?: string;
  foundInWindows?: number;
  confidence?: string;
};

const SCAN_CATEGORY_LABELS: Record<string, string> = {
  character: "角色",
  timeline: "时间线",
  location: "地点",
  bible: "设定",
  plot: "剧情",
  style: "书写",
};

const SCAN_SEVERITY_LABELS: Record<string, string> = {
  high: "高",
  medium: "中",
  low: "低",
};

export function scanCategoryLabel(raw?: string | null): string {
  const key = (raw ?? "").trim().toLowerCase();
  if (!key) return "剧情";
  return SCAN_CATEGORY_LABELS[key] ?? key;
}

export function scanSeverityLabel(raw?: string | null): string {
  const key = (raw ?? "").trim().toLowerCase();
  return SCAN_SEVERITY_LABELS[key] ?? "未知";
}

/** 与界面 data-sev 对齐的色语义。 */
export function scanSeverityTone(raw?: string | null): "high" | "warn" | "low" | "muted" {
  const key = (raw ?? "").trim().toLowerCase();
  if (key === "high") return "high";
  if (key === "medium") return "warn";
  if (key === "low") return "low";
  return "muted";
}

/** 冲突总述：几条、几条高优先级、有没有跨窗复发（跨窗复发更可信）。 */
export function summarizeScanIssues(issues?: readonly ScanIssueInput[] | null): string {
  const list = (issues ?? []).filter(Boolean);
  if (list.length === 0) return "没有发现明显冲突。";
  let high = 0;
  let medium = 0;
  let repeated = 0;
  for (const i of list) {
    const sev = (i.severity ?? "").trim().toLowerCase();
    if (sev === "high") high += 1;
    else if (sev === "medium") medium += 1;
    if (num(i.foundInWindows) >= 2 || (i.confidence ?? "").trim().toLowerCase() === "high") {
      repeated += 1;
    }
  }
  const details: string[] = [];
  if (high > 0) details.push(`${high} 条高优先级`);
  if (medium > 0) details.push(`${medium} 条中优先级`);
  if (repeated > 0) details.push(`${repeated} 条在多个窗口复现（更可信）`);
  const head = `${list.length} 条冲突`;
  return details.length === 0 ? `${head}。` : `${head}：${details.join("、")}。`;
}
