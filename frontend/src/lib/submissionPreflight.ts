/**
 * 投稿前自检（纯函数）。
 *
 * 为什么不是"按某平台的投稿规范校验"：**没有可核对的统一规范**。各平台/出版社的要求
 * 各不相同且经常改，检索到的只有二手说法（论坛、第三方仓库），拿它当依据既不诚实也不稳。
 * 所以这一层的口径是：检查**我们自己写明的导出默认值**与**作者自己作品的状态**——
 * 这两件事都是可验证的，而且恰好覆盖投稿前最容易翻车的地方（空的章、重复的标题、
 * 引号不配对吞台词、元信息没填导致投稿信息页出现"未填"）。
 *
 * 与「稿件体检」的分工：体检回答"稿子有没有毛病"（全量、按规则），自检回答
 * **"现在这一包能不能交出去"**（只看阻断项与提醒项，条目少、结论明确）。
 */

import { countChapterWords, formatWords } from "./wordCount";

export type PreflightLevel = "blocker" | "warn" | "info";

export interface PreflightCheck {
  id: string;
  level: PreflightLevel;
  title: string;
  /** 具体到章/数字的一句话 */
  detail: string;
  /** 该怎么做（没有就不写） */
  fix?: string;
}

/** 逐章摘要：从作品里取，调用方不用重复算。 */
export interface ChapterBrief {
  id: string;
  title: string;
  words: number;
  /** 有没有正文（prose 或脚本块都算） */
  hasText: boolean;
  published: boolean;
}

export interface PreflightInput {
  title: string;
  genre?: string | null;
  logline?: string | null;
  chapters: ChapterBrief[];
  /** 稿件体检（离线）里的 error 级线索条数；没跑过就传 null */
  auditErrorCount?: number | null;
  /** 体检里"引号不配对"的条数（导出时最容易出事的一类） */
  quoteUnbalancedCount?: number | null;
  /** 作者设的单章目标（用来判断"这章是不是明显没写完"） */
  chapterGoal?: number | null;
}

export interface PreflightReport {
  checks: PreflightCheck[];
  blockers: number;
  warnings: number;
  /** 能不能交：没有 blocker 就算能（warn/info 由作者判断） */
  okToSubmit: boolean;
  totalWords: number;
}

/** 一章少于这个字数时提示"是不是没写完"（只在作者设了单章目标时按目标算）。 */
const SHORT_CHAPTER_FLOOR = 500;

export function chapterBrief(chapter: {
  id: string;
  title: string;
  prose?: string;
  blocks?: unknown[];
  publishedAt?: string;
}): ChapterBrief {
  const words = countChapterWords({
    prose: chapter.prose,
    blocks: (chapter.blocks ?? []) as never,
  });
  return {
    id: chapter.id,
    title: chapter.title || "（无标题）",
    words,
    hasText: words > 0,
    published: Boolean(chapter.publishedAt),
  };
}

/**
 * 跑一遍自检。
 *
 * 级别口径（写清楚，免得以后被"顺手降级"）：
 * - **blocker**：交出去一定会出问题。目前只有一条——正文里有引号不配对，
 *   导出时会把后面的正文一起吞进台词（这是实测过的）。
 * - **warn**：交付质量会受影响，但不一定非改不可（空章、重复标题、字数极端不均）。
 * - **info**：提醒作者确认（元信息没填、有存稿没发、标题层级）。
 */
export function submissionPreflight(input: PreflightInput): PreflightReport {
  const checks: PreflightCheck[] = [];
  const chapters = input.chapters ?? [];
  const totalWords = chapters.reduce((sum, c) => sum + c.words, 0);

  if (!input.title.trim()) {
    checks.push({
      id: "no-title",
      level: "warn",
      title: "作品还没有标题",
      detail: "投稿信息页与文件名都会写成「未命名作品」",
      fix: "在「设定」页填上作品名",
    });
  }

  if (!input.genre?.trim() || !input.logline?.trim()) {
    const missing = [
      !input.genre?.trim() ? "题材" : "",
      !input.logline?.trim() ? "一句话简介" : "",
    ].filter(Boolean);
    checks.push({
      id: "missing-meta",
      level: "info",
      title: `投稿信息页会缺：${missing.join("、")}`,
      detail: "编辑拿到稿子第一眼就是这两项；不填也能导出，只是信息页上写着「未填」",
      fix: "在「设定」页补齐",
    });
  }

  const empty = chapters.filter((c) => !c.hasText);
  if (chapters.length === 0) {
    checks.push({
      id: "no-chapters",
      level: "blocker",
      title: "还没有任何章节",
      detail: "没有内容就没有可投稿的稿子",
      fix: "先在写作页写一章",
    });
  } else if (empty.length > 0) {
    checks.push({
      id: "empty-chapters",
      level: "warn",
      title: `有 ${empty.length} 章还没有正文`,
      detail: `例如「${empty[0].title}」——导出时它们会变成只有标题的空章`,
      fix: "补正文，或先把这些章删掉再导出",
    });
  }

  // 引号不配对：这是唯一会真正破坏阅读的问题（导出时吞掉后续正文）
  if ((input.quoteUnbalancedCount ?? 0) > 0) {
    checks.push({
      id: "quote-unbalanced",
      level: "blocker",
      title: `有 ${input.quoteUnbalancedCount} 处引号不配对`,
      detail: "对白少写收尾引号时，导出会把后面的正文一起吞进这句台词里",
      fix: "到「项目 → 稿件体检」按行号逐条改掉",
    });
  }
  if ((input.auditErrorCount ?? 0) > 0 && !(input.quoteUnbalancedCount ?? 0)) {
    checks.push({
      id: "audit-errors",
      level: "warn",
      title: `稿件体检有 ${input.auditErrorCount} 处错误级问题`,
      detail: "这些是会真正影响阅读的那一类（详见「稿件体检」面板）",
      fix: "先跑一遍「项目 → 稿件体检」逐条处理",
    });
  }

  const titles = chapters.map((c) => c.title.trim());
  const dupes = titles.filter((t, i) => t && titles.indexOf(t) !== i);
  if (dupes.length > 0) {
    checks.push({
      id: "duplicate-titles",
      level: "warn",
      title: `有重复的章节标题（${[...new Set(dupes)].join("、")}）`,
      detail: "编辑按标题找章会找错；导出的文件名也会撞在一起",
      fix: "给这些章改成不同的标题",
    });
  }

  // 字数：只在"作者设了单章目标"时按目标算，否则用一个很低的地板值
  const floor = input.chapterGoal && input.chapterGoal > 0 ? input.chapterGoal : SHORT_CHAPTER_FLOOR;
  const short = chapters.filter((c) => c.hasText && c.words < floor);
  if (short.length > 0) {
    checks.push({
      id: "short-chapters",
      level: "warn",
      title: `有 ${short.length} 章明显偏短`,
      detail:
        `例如「${short[0].title}」只有 ${formatWords(short[0].words)} 字` +
        (input.chapterGoal ? `（你设的单章目标是 ${formatWords(input.chapterGoal)} 字）` : ""),
      fix: "确认这一章是完整的（投稿方常会问「这章是不是没写完」）",
    });
  }

  const drafts = chapters.filter((c) => !c.published && c.hasText).length;
  if (drafts > 0) {
    checks.push({
      id: "unpublished",
      level: "info",
      title: `有 ${drafts} 章写了但没标记发布`,
      detail: "导出不受发布状态影响——只是提醒你确认这次要投的是哪些章",
      fix: "要投的话到「项目 → 连载 / 发布」标记一下，方便自己看进度",
    });
  }

  checks.push({
    id: "scale",
    level: "info",
    title: `本次导出：${chapters.length} 章 / 约 ${formatWords(totalWords)} 字`,
    detail: "投稿信息页与字数统计会写这个数字",
  });

  const blockers = checks.filter((c) => c.level === "blocker").length;
  const warnings = checks.filter((c) => c.level === "warn").length;
  return {
    checks,
    blockers,
    warnings,
    okToSubmit: blockers === 0,
    totalWords,
  };
}
