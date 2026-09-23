/**
 * 故事层指标的"翻译层"：把 `/analysis/story-metrics` 与 `/analysis/adaptive-plan`
 * 两个端点的原始 JSON，变成给作者看的结论。
 *
 * 为什么单独一层：后端返回的是**事实**（几条 open、哪个 code、刻度差几格），界面上要说的是
 * **话**（"埋了 5 条钩子只回收了 2 条，最老的一条挂了 9 章都没收"）。这层全是纯函数，
 * 不碰 DOM、不请求网络，所以每个边界都能用单测钉死。
 *
 * 输入类型刻意写成"字段全可选"：后端返回的是宽松 dict，字段可能缺失或类型异常，
 * 那时必须降级成一句如实的说明，而不是在界面上显示 NaN / undefined。
 *
 * 三条**不能写错**的口径（后端的源码注释里也专门说了）：
 * 1. `resolutionRate === null` = 这个作品还没有记录任何伏笔。它**不是** 0%：
 *    把"没有伏笔"显示成"回收率 0%"会让作者去修一个不存在的问题。
 * 2. 情绪是**台词关键词推断**：反讽、压抑、言不由衷都可能读错。所以每条情绪结论旁边
 *    都要能给出证据句（`emotionArcBreaks.rows[].evidence`），由作者自己判断。
 * 3. 自适应计数是**导出时显式开关**的行为（`adaptive_reader=True`），默认不开：
 *    不说清这一点，作者会以为"导出就有了"。
 */

/* ------------------------------------------------------------------ 常量文案 */

/** 情绪结论旁边**必须**出现的说明：这是推断，不是判断。 */
export const EMOTION_INFERENCE_NOTE =
  "情绪是从台词关键词推断的，不是语义判断：反讽、压抑、言不由衷都可能读错。每条都带证据句，请结合原文自己判断。";

/** 没有证据句时提醒作者"这条没法自查"，而不是让他以为后端忘了给。 */
export const EMOTION_NO_EVIDENCE_NOTE = "后端没有给出证据句，这条只能回原文抽查。";

/** 自适应计数的导出开关：作者最容易误解的一点，必须写在最显眼的地方。 */
export const ADAPTIVE_EXPORT_NOTE =
  "导出默认不开自适应：只有导出时带上 adaptive_reader=True，这些计数语句（$ persistent.xxx += 1）与 default 声明块才会被写进 .rpy。不加这个开关导出，产物里没有任何自适应逻辑——下面这份只是「可以怎么写」的方案。当前的导出入口还没有暴露这个开关，所以下面的条件与声明块要手工加进 .rpy。";

/** 条件示例的用法。 */
export const RECIPE_COPY_HINT =
  "把条件原样粘进选项的「条件」栏即可（Ren'Py 里的 if 写法）。";

/* -------------------------------------------------------------------- 小工具 */

function num(v: unknown): number {
  return typeof v === "number" && Number.isFinite(v) ? v : 0;
}

function str(v: unknown): string {
  return typeof v === "string" ? v.trim() : "";
}

function clamp(v: number, lo: number, hi: number): number {
  return Math.max(lo, Math.min(hi, v));
}

/** 情绪词缺失时的兜底：宁可显示"没推断出来"，也不显示空白。 */
function emotionLabel(v: unknown): string {
  return str(v) || "（没推断出情绪）";
}

/* -------------------------------------------------------------- 输入类型（宽松） */

export type StoryHookInput = {
  hook?: string;
  plantedChapter?: string;
  plantedChapterTitle?: string;
  chaptersOpen?: number;
};

export type StoryForeshadowInput = {
  total?: number;
  paid?: number;
  open?: number;
  /** null = 没有伏笔（不是 0%） */
  resolutionRate?: number | null;
  chapters?: number;
  oldestOpenChapters?: number;
  openHooks?: StoryHookInput[] | null;
  note?: string;
};

export type StoryArcInput = {
  character?: string;
  start?: string;
  end?: string;
  delta?: number;
};

export type StoryChapterRowInput = {
  characterId?: string;
  character?: string;
  chapterId?: string;
  chapterTitle?: string;
  chapterIndex?: number;
  start?: string;
  end?: string;
  delta?: number;
  lines?: number;
  evidence?: string[] | null;
};

export type StoryArcBreakInput = {
  character?: string;
  chapterId?: string;
  chapterTitle?: string;
  issue?: string;
  overallDelta?: number;
  chapterDelta?: number;
  actual?: string;
  message?: string;
};

export type StoryDeclaredMismatchInput = {
  character?: string;
  issue?: string;
  declared?: string;
  actual?: string;
  message?: string;
};

export type StoryMetricsInput = {
  foreshadow?: StoryForeshadowInput | null;
  emotionArcs?: {
    characters?: StoryArcInput[] | null;
    flatArcs?: StoryArcInput[] | null;
    note?: string;
  } | null;
  emotionArcBreaks?: {
    rows?: StoryChapterRowInput[] | null;
    breaks?: StoryArcBreakInput[] | null;
  } | null;
  declaredArcMismatches?: StoryDeclaredMismatchInput[] | null;
};

/* ------------------------------------------------------------------ 伏笔回收率 */

export type ForeshadowTone = "ok" | "watch" | "muted";

export type ForeshadowRateView = {
  /** 后端给没给得出回收率：false = 这个作品还没有伏笔 */
  hasRate: boolean;
  /** 0–100；**null 表示"还没有伏笔"**，界面必须显示成说明文字而不是 0% */
  percent: number | null;
  headline: string;
  detail: string;
  tone: ForeshadowTone;
  total: number;
  paid: number;
  open: number;
  oldestOpenChapters: number;
  chapters: number;
  /** 字段之间对不上 / 后端没给某个数时的如实说明 */
  notes: string[];
};

/**
 * 伏笔回收率 → 一句话 + 明细。
 *
 * 核心判断：**分母为 0 时后端给的是 `resolutionRate: null`**，界面照着说
 * "这个作品还没有记录任何伏笔"，而不是算成 0%。这两句话对作者的意义完全不同：
 * 前者是"你还没埋钩子"，后者是"你埋了一堆一个都没收"。
 */
export function foreshadowView(input?: StoryMetricsInput | null): ForeshadowRateView {
  const f = input?.foreshadow;
  const notes: string[] = [];
  const chapters = Math.max(0, num(f?.chapters));
  const total = Math.max(0, num(f?.total));
  const rateRaw = f?.resolutionRate;
  const rateKnown = typeof rateRaw === "number" && Number.isFinite(rateRaw as number);

  if (total <= 0) {
    if (rateKnown && (rateRaw as number) > 0) {
      notes.push(
        `后端给了回收率 ${(rateRaw as number).toFixed(3)} 但伏笔总数是 0，两个字段对不上：界面按「还没有伏笔」显示。`
      );
    }
    return {
      hasRate: false,
      percent: null,
      headline: "这个作品还没有记录任何伏笔。",
      detail:
        "伏笔由写作账本维护：在章节里埋下钩子、保存之后，这里才会出现回收率。没有伏笔不等于回收率 0%。",
      tone: "muted",
      total: 0,
      paid: 0,
      open: 0,
      oldestOpenChapters: 0,
      chapters,
      notes,
    };
  }

  const paid = clamp(num(f?.paid), 0, total);
  const open =
    f?.open === undefined ? Math.max(0, total - paid) : clamp(num(f.open), 0, total);
  const oldest = Math.max(0, num(f?.oldestOpenChapters));

  let percent: number;
  if (rateKnown) {
    percent = Math.round(clamp(rateRaw as number, 0, 1) * 100);
    if ((rateRaw as number) < 0 || (rateRaw as number) > 1) {
      notes.push(
        `后端给的回收率是 ${rateRaw}（不在 0–1 之间），界面夹在 0–100% 显示。`
      );
    }
    const fromCounts = Math.round((paid / total) * 100);
    if (Math.abs(fromCounts - percent) >= 2) {
      notes.push(
        `后端给的回收率换算成 ${percent}%，而「已回收 ${paid}/${total}」是 ${fromCounts}%：界面显示后端给的那个数。`
      );
    }
  } else {
    percent = Math.round((paid / total) * 100);
    notes.push(
      "后端没有给出 resolutionRate（字段缺失）：这里的百分比是按「已回收 ÷ 总数」现算的。"
    );
  }

  const detailParts = [`还有 ${open} 条没回收`];
  if (oldest > 0) detailParts.push(`最老的一条埋了 ${oldest} 章还没收`);
  if (open > 0 && oldest === 0) {
    detailParts.push("它们都埋在后面的章节，暂时还不算挂太久");
  }
  if (chapters > 0) detailParts.push(`全书 ${chapters} 章`);

  return {
    hasRate: true,
    percent,
    headline: `伏笔回收率 ${percent}%：已回收 ${paid}/${total}`,
    detail: `${detailParts.join("，")}。`,
    // 一半是"值得留意"的经验线，与后端 findings 里的 0.5 门槛同口径
    tone: percent >= 50 ? "ok" : "watch",
    total,
    paid,
    open,
    oldestOpenChapters: oldest,
    chapters,
    notes,
  };
}

/* ---------------------------------------------------------------- 未回收的钩子 */

export type OpenHookRow = {
  key: string;
  /** 钩子文案；后端没给时是「（未命名的伏笔）」，不是空白 */
  hook: string;
  plantedChapter: string;
  /** 章节标题，找不到退回 id；没有 id 时为空串 */
  chapter: string;
  chaptersOpen: number;
  ageText: string;
};

/**
 * 未回收钩子列表：hook 文案 + 埋在哪一章 + 挂了多久，**按章龄降序**。
 *
 * 后端也排过一次序，这里再排一次是有意的：这是作者唯一能自己判断"哪条最该现在收"的
 * 依据，排序规则写在界面这一层，测试才能钉死（章龄相同再按章节顺序，保证结果稳定）。
 */
export function openHookRows(
  input?: StoryMetricsInput | null,
  titles?: Record<string, string> | null
): OpenHookRow[] {
  const rows: OpenHookRow[] = [];
  (input?.foreshadow?.openHooks ?? []).forEach((h, i) => {
    if (!h) return;
    const hook = str(h.hook) || "（未命名的伏笔）";
    const plantedChapter = str(h.plantedChapter);
    const chaptersOpen = Math.max(0, num(h.chaptersOpen));
    const title = str(h.plantedChapterTitle);
    const chapter =
      title || (plantedChapter ? (titles?.[plantedChapter] ?? plantedChapter) : "");
    rows.push({
      key: `${plantedChapter || "hook"}-${i}-${hook.slice(0, 24)}`,
      hook,
      plantedChapter,
      chapter,
      chaptersOpen,
      ageText:
        chaptersOpen > 0
          ? `埋在这里，已经挂了 ${chaptersOpen} 章还没回收`
          : "埋在靠后的章节，还没跨过整章",
    });
  });
  rows.sort(
    (a, b) =>
      b.chaptersOpen - a.chaptersOpen ||
      a.plantedChapter.localeCompare(b.plantedChapter) ||
      a.hook.localeCompare(b.hook)
  );
  return rows;
}

/* ------------------------------------------------------------------ 情感弧线 */

export type ArcDirection = "up" | "down" | "flat";

/** 刻度差 → 方向（0 或非数值都算"没动"）。 */
export function arcDirection(delta: number | undefined | null): ArcDirection {
  const d = num(delta);
  if (d === 0) return "flat";
  return d > 0 ? "up" : "down";
}

/** 方向 → 给作者看的说法。 */
export function arcDirectionText(delta: number | undefined | null): string {
  const d = arcDirection(delta);
  if (d === "up") return "往上走";
  if (d === "down") return "往下走";
  return "基本没动";
}

export type EmotionArcRow = {
  key: string;
  character: string;
  from: string;
  to: string;
  delta: number;
  /** true = 后端把它归进 flatArcs（全篇没变化） */
  flat: boolean;
  direction: ArcDirection;
  /** 「从「平静」走到「激动」（往上走 4 格）」 */
  text: string;
  /** 平的时候的补充说明，非平时为空串（不留空标签） */
  flatNote: string;
};

const FLAT_NOTE =
  "全篇推断为同一个情绪：不是错，但值得看一眼（尤其主角，或节拍表里声明过变化的角色）。";

/**
 * 逐角色的情感弧线：从哪儿走到哪儿 + 是不是平的。
 *
 * `flatArcs` 是后端的判定（|delta| < 2），这里以它为准；同时**兜底**：
 * 万一某个角色只出现在 `flatArcs` 里（字段之间对不上），也要出一个"平"的行，
 * 不能让一条"没变化"的结论静默消失。
 */
export function emotionArcRows(input?: StoryMetricsInput | null): EmotionArcRow[] {
  const arcs = input?.emotionArcs;
  const flatKeys = new Set(
    (arcs?.flatArcs ?? [])
      .filter(Boolean)
      .map((a) => str(a.character))
      .filter(Boolean)
  );

  const list = [...(arcs?.characters ?? []).filter(Boolean)];
  const seen = new Set(list.map((a) => str(a.character)));
  for (const f of arcs?.flatArcs ?? []) {
    if (!f) continue;
    const name = str(f.character);
    if (name && !seen.has(name)) {
      seen.add(name);
      list.push(f);
    }
  }

  return list.map((a, i) => {
    const character = str(a.character) || "（未署名角色）";
    const from = emotionLabel(a.start);
    const to = emotionLabel(a.end);
    const delta = num(a.delta);
    const flat = flatKeys.has(str(a.character)) || delta === 0;
    return {
      key: `${character}-${i}`,
      character,
      from,
      to,
      delta,
      flat,
      direction: arcDirection(delta),
      text: flat
        ? `全篇都停在「${from}」`
        : `从「${from}」走到「${to}」（${arcDirectionText(delta)} ${Math.abs(delta)} 格）`,
      flatNote: flat ? FLAT_NOTE : "",
    };
  });
}

export type EmotionChapterRow = {
  key: string;
  character: string;
  chapterId: string;
  /** 章节标题，找不到退回 id */
  chapter: string;
  chapterIndex: number;
  from: string;
  to: string;
  delta: number;
  /** 这一章该角色说了几句（后端只在 ≥2 句时才评估） */
  lines: number;
  direction: ArcDirection;
  text: string;
  evidence: string[];
  evidenceText: string;
  /** true = 这一行同时出现在 breaks 里（局部走向与全篇相反） */
  broken: boolean;
};

/** 逐（角色 × 章）的情绪走向 + 证据句；断裂的章排在最前面。 */
export function emotionChapterRows(
  input?: StoryMetricsInput | null,
  titles?: Record<string, string> | null
): EmotionChapterRow[] {
  const breaks = input?.emotionArcBreaks?.breaks ?? [];
  const brokenKeys = new Set(
    breaks.filter(Boolean).map((b) => `${str(b.character)}|${str(b.chapterId)}`)
  );

  const rows = (input?.emotionArcBreaks?.rows ?? []).filter(Boolean).map((r, i) => {
    const character = str(r.character) || "（未署名角色）";
    const chapterId = str(r.chapterId);
    const from = emotionLabel(r.start);
    const to = emotionLabel(r.end);
    const delta = num(r.delta);
    const evidence = (r.evidence ?? []).map((e) => str(e)).filter(Boolean);
    const title = str(r.chapterTitle);
    return {
      key: `${character}-${chapterId || "chapter"}-${i}`,
      character,
      chapterId,
      chapter: title || (chapterId ? (titles?.[chapterId] ?? chapterId) : ""),
      chapterIndex: Number.isFinite(r.chapterIndex) ? num(r.chapterIndex) : -1,
      from,
      to,
      delta,
      lines: Math.max(0, num(r.lines)),
      direction: arcDirection(delta),
      text: `${from} → ${to}（${arcDirectionText(delta)} ${Math.abs(delta)} 格）`,
      evidence,
      evidenceText: evidence.length
        ? `证据句：${evidence.map((e) => `「${e}」`).join("、")}`
        : EMOTION_NO_EVIDENCE_NOTE,
      broken: brokenKeys.has(`${str(r.character)}|${chapterId}`),
    };
  });

  // 断裂的章排最前（那才是要改的），其余按角色 + 章节顺序，保证结果稳定
  rows.sort(
    (a, b) =>
      Number(b.broken) - Number(a.broken) ||
      a.character.localeCompare(b.character) ||
      a.chapterIndex - b.chapterIndex
  );
  return rows;
}

export type EmotionBreakRow = {
  key: string;
  character: string;
  chapterId: string;
  chapter: string;
  overallDelta: number;
  chapterDelta: number;
  /** 这一章实际的情绪走向（后端的 actual 字段） */
  actual: string;
  /** 全篇 vs 这一章的对比句 */
  comparison: string;
  message: string;
};

/**
 * 逐章断裂：**哪一章**把角色的情绪写反了。
 *
 * 这是这份数据里唯一能"按章归因"的部分（带 `chapterId`），所以章节标题必须显示出来，
 * 而且要把「全篇的走向」与「这一章的走向」并排说，作者才能一眼判断是不是写反了。
 */
export function emotionBreakRows(
  input?: StoryMetricsInput | null,
  titles?: Record<string, string> | null
): EmotionBreakRow[] {
  return (input?.emotionArcBreaks?.breaks ?? []).filter(Boolean).map((b, i) => {
    const character = str(b.character) || "（未署名角色）";
    const chapterId = str(b.chapterId);
    const title = str(b.chapterTitle);
    const chapter = title || (chapterId ? (titles?.[chapterId] ?? chapterId) : "");
    const overallDelta = num(b.overallDelta);
    const chapterDelta = num(b.chapterDelta);
    const chapterName = chapter || "（章节未知）";
    return {
      key: `${character}-${chapterId || i}`,
      character,
      chapterId,
      chapter,
      overallDelta,
      chapterDelta,
      actual: str(b.actual) || `${arcDirectionText(overallDelta)} → 反向`,
      comparison:
        `全篇「${arcDirectionText(overallDelta)}」` +
        `，${chapterName} 这一章却是「${arcDirectionText(chapterDelta)}」` +
        (str(b.actual) ? `（${str(b.actual)}）` : ""),
      message: str(b.message) || "这一章的局部走向和全篇相反，检查是不是写反了。",
    };
  });
}

/* ------------------------------------------------------- 与节拍表声明的对账 */

export type DeclaredIssue = "arc_flat" | "arc_reversed" | "other";

/** 方向相反更"必须看一眼"（声明与产出直接矛盾），所以排在前面。 */
const DECLARED_ISSUE_ORDER: readonly DeclaredIssue[] = [
  "arc_reversed",
  "arc_flat",
  "other",
];

const DECLARED_ISSUE_LABELS: Record<DeclaredIssue, string> = {
  arc_reversed: "方向和声明相反",
  arc_flat: "声明有变化、实际没变",
  other: "其它对账不一致",
};

const DECLARED_ISSUE_HINTS: Record<DeclaredIssue, string> = {
  arc_reversed:
    "节拍表说这一场情绪往这边走，台词推断出来却是反的：先确认原文是不是有意的反转，不是的话就是写反了（或少了转折）。",
  arc_flat:
    "节拍表声明了变化，台词里却没读出变化：要么这一场真没写出来（补一段转折），要么是关键词没读到（这句话本身是推断，回原文看一眼再改）。",
  other: "后端报出的对账不一致，但类别不在已知的两种里：按下面的原文与推断值自己判断。",
};

export type DeclaredMismatchRow = {
  key: string;
  character: string;
  issue: DeclaredIssue;
  issueLabel: string;
  hint: string;
  declared: string;
  actual: string;
  message: string;
};

function declaredIssueOf(raw: string | undefined): DeclaredIssue {
  const s = str(raw);
  if (s === "arc_reversed") return "arc_reversed";
  if (s === "arc_flat") return "arc_flat";
  return "other";
}

export function declaredMismatchRows(
  input?: StoryMetricsInput | null
): DeclaredMismatchRow[] {
  return (input?.declaredArcMismatches ?? []).filter(Boolean).map((m, i) => {
    const issue = declaredIssueOf(m.issue);
    const character = str(m.character) || "（未署名角色）";
    return {
      key: `${issue}-${character}-${i}`,
      character,
      issue,
      issueLabel: DECLARED_ISSUE_LABELS[issue],
      hint: DECLARED_ISSUE_HINTS[issue],
      declared: str(m.declared) || "（后端没给声明值）",
      actual: str(m.actual) || "（后端没给实际值）",
      message: str(m.message) || "与节拍表声明不一致。",
    };
  });
}

export type DeclaredMismatchGroup = {
  issue: DeclaredIssue;
  label: string;
  hint: string;
  rows: DeclaredMismatchRow[];
};

/** 按 arc_reversed / arc_flat / 其它分组（空组不出现）。 */
export function declaredMismatchGroups(
  input?: StoryMetricsInput | null
): DeclaredMismatchGroup[] {
  const rows = declaredMismatchRows(input);
  const buckets = new Map<DeclaredIssue, DeclaredMismatchRow[]>();
  for (const r of rows) {
    const list = buckets.get(r.issue);
    if (list) list.push(r);
    else buckets.set(r.issue, [r]);
  }
  const out: DeclaredMismatchGroup[] = [];
  for (const issue of DECLARED_ISSUE_ORDER) {
    const list = buckets.get(issue);
    if (!list || list.length === 0) continue;
    out.push({
      issue,
      label: DECLARED_ISSUE_LABELS[issue],
      hint: DECLARED_ISSUE_HINTS[issue],
      rows: list,
    });
  }
  return out;
}

/** 对账总述：「与节拍表声明对不上 2 处：1 处方向相反、1 处声明有变化实际没变。」 */
export function declaredMismatchSummary(input?: StoryMetricsInput | null): string {
  const groups = declaredMismatchGroups(input);
  const total = groups.reduce((n, g) => n + g.rows.length, 0);
  if (total === 0) return "与节拍表声明一致（或这次没有可对账的声明）。";
  const parts = groups.map((g) => `${g.rows.length} 处${g.label}`);
  return `与节拍表声明对不上 ${total} 处：${parts.join("、")}。`;
}

/* ---------------------------------------------------------------- 总述一句话 */

export type StorySummaryView = { headline: string; notes: string[] };

/**
 * 故事层总述：伏笔 + 弧线 + 断裂 + 声明对账，压成一句作者能直接读的话。
 *
 * 数字一律从本层的翻译结果里取（而不是再读一遍原始字段），否则容易出现
 * "上面写 0%、下面写还没有伏笔"这种自相矛盾的屏幕。
 */
export function summarizeStoryMetrics(
  input?: StoryMetricsInput | null,
  titles?: Record<string, string> | null
): StorySummaryView {
  const f = foreshadowView(input);
  const arcs = emotionArcRows(input);
  const breaks = emotionBreakRows(input, titles);
  const mismatches = declaredMismatchGroups(input);
  const mismatchCount = mismatches.reduce((n, g) => n + g.rows.length, 0);
  const notes: string[] = [];

  const parts: string[] = [];
  if (!f.hasRate) {
    parts.push("还没有记录任何伏笔");
  } else {
    parts.push(`伏笔 ${f.paid}/${f.total} 已回收（${f.percent}%）`);
    if (f.open > 0 && f.oldestOpenChapters > 0) {
      parts.push(`${f.open} 条未回收，最老的挂了 ${f.oldestOpenChapters} 章`);
    }
  }

  if (arcs.length === 0) {
    notes.push(
      "没有可评估的情感弧线：后端要求至少 2 句台词才推断，对白太少就一条都不出。"
    );
  } else {
    const flat = arcs.filter((a) => a.flat).length;
    parts.push(
      `${arcs.length} 个角色有情感弧线` +
        (flat > 0 ? `（其中 ${flat} 个全篇没变化）` : "")
    );
  }
  if (breaks.length > 0) parts.push(`${breaks.length} 处逐章走向与全篇相反`);
  if (mismatchCount > 0) parts.push(`与节拍表声明对不上 ${mismatchCount} 处`);

  return { headline: `${parts.join("；")}。`, notes };
}

/* ------------------------------------------------------------ 自适应选项方案 */

export type AdaptivePlanInput = {
  tendencyCounters?: Record<string, string> | null;
  recipeThreshold?: number;
  recipes?: Array<{
    variableKey?: string;
    counter?: string;
    condition?: string;
    meaning?: string;
  }> | null;
  candidates?: Array<{
    menuId?: string;
    chapterId?: string;
    optionCount?: number;
    reason?: string;
    suggestion?: string;
  }> | null;
  prelude?: string | null;
  notes?: string[] | null;
};

export type CounterRow = {
  key: string;
  variableKey: string;
  /** 计数器名（不含 persistent. 前缀） */
  counter: string;
  /** Ren'Py 里可直接读写的引用；计数器名缺失时为空串 */
  ref: string;
  note: string;
};

/** `persistent.` 前缀不能省：省掉写进去的是普通变量，**存档之间各自独立**。 */
export function counterRef(counter: unknown): string {
  const name = str(counter);
  if (!name) return "";
  return name.startsWith("persistent.") ? name : `persistent.${name}`;
}

/** 计数器清单：变量 key → persistent 引用（按 key 排序，结果稳定）。 */
export function tendencyCounterRows(
  counters?: Record<string, string> | null
): CounterRow[] {
  const rows: CounterRow[] = [];
  for (const [variableKey, counter] of Object.entries(counters ?? {})) {
    const key = str(variableKey);
    if (!key) continue;
    const name = str(counter);
    rows.push({
      key,
      variableKey: key,
      counter: name,
      ref: counterRef(name),
      note: name
        ? "选到会改变量的选项时 +1，跨存档保留"
        : "后端没给计数器名：这条没法直接引用，先按变量 key 自己起个名字。",
    });
  }
  rows.sort((a, b) => a.variableKey.localeCompare(b.variableKey));
  return rows;
}

export type RecipeRow = {
  key: string;
  variableKey: string;
  counter: string;
  /** 可直接照抄的选项条件 */
  condition: string;
  meaning: string;
  /** true = condition 是界面按 counter + 门槛现拼的（后端没给） */
  derived: boolean;
  note: string;
};

/**
 * 条件示例：`condition` 是**可以直接照抄**的表达式，所以它就是这一屏的核心内容。
 *
 * 后端没给 `condition` 时，只要计数器在，就按同一个写法现拼一个（并如实标注是现拼的），
 * 而不是让作者看到一行空白。
 */
export function recipeRows(
  input?: AdaptivePlanInput | null,
  opts: { threshold?: number } = {}
): RecipeRow[] {
  const threshold = Number.isFinite(opts.threshold) ? num(opts.threshold) : 3;
  return (input?.recipes ?? []).filter(Boolean).map((r, i) => {
    const variableKey = str(r.variableKey) || `（第 ${i + 1} 条）`;
    const counter = str(r.counter);
    const ref = counterRef(counter);
    let condition = str(r.condition);
    let derived = false;
    const notes: string[] = [];
    if (!condition && ref) {
      condition = `${ref} >= ${threshold}`;
      derived = true;
      notes.push("后端没给条件表达式，这里是按「计数器 >= 门槛」现拼的，可以直接用。");
    }
    if (!condition) {
      notes.push("后端既没给条件、也没给计数器：这条先跳过，等有选项改变量后再来看。");
    } else if (!counter) {
      notes.push("后端没给计数器名，但条件表达式可以直接照抄。");
    }
    notes.push(RECIPE_COPY_HINT);
    return {
      key: `${variableKey}-${i}`,
      variableKey,
      counter,
      condition,
      meaning: str(r.meaning) || "（后端没给这条示例的用途说明）",
      derived,
      note: notes.join(""),
    };
  });
}

export type AdaptiveCandidateRow = {
  key: string;
  menuId: string;
  chapterId: string;
  chapter: string;
  optionCount: number;
  reason: string;
  suggestion: string;
  title: string;
};

/** 值得做成自适应的菜单：哪个菜单、几个选项、为什么。 */
export function adaptiveCandidateRows(
  input?: AdaptivePlanInput | null,
  titles?: Record<string, string> | null
): AdaptiveCandidateRow[] {
  return (input?.candidates ?? []).filter(Boolean).map((c, i) => {
    const menuId = str(c.menuId) || `（第 ${i + 1} 个菜单）`;
    const chapterId = str(c.chapterId);
    const chapter = chapterId ? (titles?.[chapterId] ?? chapterId) : "";
    const optionCount = Math.max(0, num(c.optionCount));
    return {
      key: `${chapterId || "chapter"}-${menuId}-${i}`,
      menuId,
      chapterId,
      chapter,
      optionCount,
      reason: str(c.reason) || "后端没给理由（只说了这个菜单值得做）",
      suggestion: str(c.suggestion) || "（后端没给具体改法）",
      title: `${chapter || "（章节未知）"} · ${menuId}${
        optionCount > 0 ? `（${optionCount} 个选项）` : ""
      }`,
    };
  });
}

export type PreludeView = {
  /** true = prelude 是空串：没有任何"会改变量的选项" */
  empty: boolean;
  text: string;
  headline: string;
  hint: string;
  /** 空的时候给"先在选项里改变量"的引导，非空时为空串 */
  emptyGuide: string;
};

/**
 * `prelude` 是**要写进 .rpy 的声明块，可能是空串**。
 *
 * 空的时候绝不能只渲染一个空代码框：那看起来像"界面坏了"。要说清为什么是空的，
 * 以及下一步该做什么（先在选项里改变量）。
 */
export function preludeView(prelude?: string | null): PreludeView {
  const text = str(prelude);
  if (!text) {
    return {
      empty: true,
      text: "",
      headline: "这份剧本还没有任何会改变量的选项，所以没有声明块要写。",
      hint: "",
      emptyGuide:
        "先在选项里改变量（例如在某个选项的 set 块里把 affection 加 1）：工具会为它生成读者倾向计数器，这里才会出现要写进 .rpy 的 default 声明块，条件示例也才有内容可照抄。",
    };
  }
  return {
    empty: false,
    text,
    headline: "下面这段要放到 .rpy 的开头（default 声明块）：",
    hint: "每个计数器先声明初值，Ren'Py 才知道 persistent.reader_tendency_xxx 是什么。",
    emptyGuide: "",
  };
}

export type AdaptiveSummaryView = {
  counters: number;
  recipes: number;
  candidates: number;
  hasPrelude: boolean;
  headline: string;
  notes: string[];
};

/** 自适应方案总述：识别出几个计数器、几个菜单值得做、以及门槛的含义。 */
export function summarizeAdaptivePlan(
  input?: AdaptivePlanInput | null,
  titles?: Record<string, string> | null
): AdaptiveSummaryView {
  const counters = tendencyCounterRows(input?.tendencyCounters);
  const recipes = recipeRows(input, { threshold: input?.recipeThreshold });
  const candidates = adaptiveCandidateRows(input, titles);
  const prelude = preludeView(input?.prelude);
  const notes: string[] = [];

  if (counters.length === 0) {
    notes.push(
      "一个计数器都没有：自适应的前提是「某个选项会改变量」。先在选项里改变量，这份清单才会有内容。"
    );
  } else if (recipes.length !== counters.length) {
    notes.push(
      `计数器有 ${counters.length} 个，条件示例只有 ${recipes.length} 条：以计数器清单为准，缺的可以按同样的写法自己补。`
    );
  }

  const threshold = Number.isFinite(input?.recipeThreshold)
    ? num(input?.recipeThreshold)
    : 3;
  if (counters.length > 0) {
    notes.push(
      `示例里的门槛统一是 ${threshold} 次：调大它 = 只有"更铁杆"的读者才看得到那条支线。`
    );
  }
  if (candidates.length === 0) {
    notes.push(
      "没有菜单被判为「值得做成自适应」：当所有选项后果完全相同、或读者几乎总是选同一个时才会出现在这里。"
    );
  }

  return {
    counters: counters.length,
    recipes: recipes.length,
    candidates: candidates.length,
    hasPrelude: !prelude.empty,
    headline:
      counters.length === 0
        ? "还没有可用的读者倾向计数器。"
        : `识别出 ${counters.length} 个变量 → ${counters.length} 个持久计数器，${candidates.length} 个菜单值得做成自适应。`,
    notes,
  };
}
