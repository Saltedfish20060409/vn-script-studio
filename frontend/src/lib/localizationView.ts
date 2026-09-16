/**
 * 本地化页的展示逻辑（分组、进度、下一条未翻）。
 *
 * 抽出来的原因：这些是页面里唯一"算得出来"的部分，放在组件里只能靠肉眼看；
 * 而且踩过的坑（章节顺序、章节标题、空章节）都值得钉住。
 */

import type { LocalizationEntry } from "../api/projects";

export type ChapterLike = { id: string; title?: string };

export type ChapterGroup = {
  chapterId: string;
  /** 章节标题（拿不到时退回 id，绝不显示空标题） */
  title: string;
  entries: LocalizationEntry[];
  translated: number;
  total: number;
};

export type Progress = { done: number; total: number; pct: number };

export function progressFor(
  entries: LocalizationEntry[],
  locale: string
): Progress {
  const total = entries.length;
  const done = entries.filter((e) => (e.targets?.[locale] || "").trim()).length;
  return { done, total, pct: total ? Math.round((done / total) * 100) : 0 };
}

/**
 * 按**剧本里的章节顺序**分组（不是按条目出现顺序），这样作者看到的分组顺序
 * 和写稿顺序一致；章节标题来自项目，避免界面上出现 `ch1` 这种内部 id。
 */
export function groupByChapter(
  entries: LocalizationEntry[],
  chapters: ChapterLike[],
  locale: string
): ChapterGroup[] {
  const titleOf = new Map(chapters.map((c) => [c.id, c.title || c.id]));
  const order = chapters.map((c) => c.id);
  const buckets = new Map<string, LocalizationEntry[]>();
  for (const e of entries) {
    const key = e.chapterId || "__other";
    const list = buckets.get(key) || [];
    list.push(e);
    buckets.set(key, list);
  }
  const ids = [...order.filter((id) => buckets.has(id)), ...[...buckets.keys()].filter((id) => !order.includes(id))];
  return ids.map((id) => {
    const list = buckets.get(id) || [];
    return {
      chapterId: id,
      title: titleOf.get(id) || id,
      entries: list,
      translated: list.filter((e) => (e.targets?.[locale] || "").trim()).length,
      total: list.length,
    };
  });
}

/** 第一条还没翻的条目（用于"跳到下一条"按钮）；全翻完返回 null。 */
export function nextUntranslated(
  entries: LocalizationEntry[],
  locale: string
): LocalizationEntry | null {
  return entries.find((e) => !(e.targets?.[locale] || "").trim()) ?? null;
}

/** 术语表预填对某条目是否真的会产生变化（用于提示"已无需预填"）。 */
export function hasUntranslated(entries: LocalizationEntry[], locale: string): boolean {
  return entries.some((e) => !(e.targets?.[locale] || "").trim());
}

/**
 * 单次 AI 代翻能处理多少句（必须和后端 `MAX_ENTRIES_PER_CALL` 一致）。
 * 后端还有 4000 字符的预算，所以实际每轮可能少于这个数。
 */
export const AUTO_L10N_PER_CALL = 50;

/**
 * token 估算系数：**实测**得来，不是拍的。
 *
 * 对线上最长的一部（14016 句、平均 27 字/句）用生产模型 glm-4-flash-250414 实测：
 *   25 句 / 639 字 → 输入 1099 + 输出 789 = 1888 token（2.96 token/字）
 *   50 句 / 1196 字 → 输入 2015 + 输出 1495 = 3510 token（2.94 token/字）
 *   100 句 / 2671 字 → 输入 4123 + 输出 3572 = 7695 token（2.88 token/字）
 * 三档高度一致，所以按源文本字数线性估算就够准（误差 <5%）。
 * 中译英的输入比输出大（中文一个字约 1.7 token，英文译文约 1.25 token/字）。
 */
const L10N_INPUT_TOKENS_PER_CHAR = 1.7;
const L10N_OUTPUT_TOKENS_PER_CHAR = 1.25;

export type TranslateEstimate = {
  /** 还要翻几句 */
  sentences: number;
  /** 这些句子的源文本总字数 */
  chars: number;
  /** 还需请求几次 */
  calls: number;
  inputTokens: number;
  outputTokens: number;
  totalTokens: number;
};

/** 估算"翻完剩下的"要花多少请求和 token —— 让用户动手前心里有底。 */
export function estimateTranslate(
  entries: LocalizationEntry[],
  locale: string,
  perCall = AUTO_L10N_PER_CALL
): TranslateEstimate {
  const todo = entries.filter((e) => !(e.targets?.[locale] || "").trim());
  const chars = todo.reduce((n, e) => n + (e.source || "").trim().length, 0);
  return {
    sentences: todo.length,
    chars,
    calls: todo.length ? Math.ceil(todo.length / Math.max(1, perCall)) : 0,
    inputTokens: Math.round(chars * L10N_INPUT_TOKENS_PER_CHAR),
    outputTokens: Math.round(chars * L10N_OUTPUT_TOKENS_PER_CHAR),
    totalTokens: Math.round(
      chars * (L10N_INPUT_TOKENS_PER_CHAR + L10N_OUTPUT_TOKENS_PER_CHAR)
    ),
  };
}

/** 大数字写成"12.3 万"这种一眼能读的形式。 */
export function humanTokens(n: number): string {
  if (n >= 10_000_000) return `${(n / 10_000_000).toFixed(1)} 千万`;
  if (n >= 10_000) return `${(n / 10_000).toFixed(1)} 万`;
  return `${Math.round(n)}`;
}

/**
 * 一次「AI 翻完剩下的」最多发几次请求。
 *
 * 后端对本接口限流 60 次/小时，留出余量后取 40：这样连点两次不会一头撞上限流，
 * 同时也避免长剧本在用户没盯着的时候把免费额度一口吃光。
 */
export const AUTO_L10N_MAX_CALLS = 40;

type AutoTranslateStop =
  | "done"
  | "limit"
  | "cancelled"
  | "error"
  | "stalled";

export type AutoTranslateProgress = {
  calls: number;
  applied: number;
  remaining: number;
  /** 开始前的未翻总数，用于算进度百分比 */
  startedWith: number;
  /** 本次已真实消耗的 token（服务端每轮回传，累加） */
  tokens: number;
};

export type AutoTranslateResult = AutoTranslateProgress & {
  stop: AutoTranslateStop;
  error?: unknown;
  /** 已翻句数（applied 的累计） */
  progressPct: number;
};

/**
 * 「AI 翻完剩下的」循环：一轮一轮地调接口，直到翻完/被叫停/撞上限流。
 *
 * 为什么不放在后端做一个"全量翻译"接口：一轮的 token 预算必须可预测，
 * 而且用户要能随时打住。真正的边界留在客户端，每轮的边界留在服务端。
 *
 * 抽成纯函数（依赖全部注入）是为了能测：连续两轮 applied=0 时如果继续跑，
 * 就会变成一个永远转圈的循环——这是这里最容易犯的错。
 */
export async function runAutoTranslate(opts: {
  /** 开始前还有多少句没翻（用于进度条） */
  remaining: number;
  /** 单次请求翻译上限 */
  perCall?: number;
  /** 最多发几次请求 */
  maxCalls?: number;
  /** 取消检查（每轮开始前调用） */
  shouldStop?: () => boolean;
  /** 发一轮请求；返回本轮写入句数、剩余句数与真实 token 消耗 */
  translateOnce: () => Promise<{ applied: number; remaining: number; tokens?: number }>;
  onProgress?: (p: AutoTranslateProgress) => void;
}): Promise<AutoTranslateResult> {
  const maxCalls = opts.maxCalls ?? AUTO_L10N_MAX_CALLS;
  const startedWith = Math.max(0, opts.remaining);
  let calls = 0;
  let applied = 0;
  let remaining = startedWith;
  let tokens = 0;
  let stalled = 0;
  const emit = () =>
    opts.onProgress?.({ calls, applied, remaining, startedWith, tokens });
  const finish = (
    stop: AutoTranslateStop,
    error?: unknown
  ): AutoTranslateResult => {
    emit();
    const doneCount = startedWith - remaining;
    return {
      calls,
      applied,
      remaining,
      startedWith,
      tokens,
      stop,
      error,
      progressPct: startedWith
        ? Math.min(100, Math.round((doneCount / startedWith) * 100))
        : 100,
    };
  };

  if (startedWith === 0) return finish("done");
  emit();

  while (calls < maxCalls) {
    if (opts.shouldStop?.()) return finish("cancelled");
    let out: { applied: number; remaining: number; tokens?: number };
    try {
      out = await opts.translateOnce();
    } catch (error) {
      return finish("error", error);
    }
    calls += 1;
    applied += Math.max(0, out.applied);
    remaining = Math.max(0, out.remaining);
    tokens += Math.max(0, out.tokens ?? 0);
    emit();
    if (remaining === 0) return finish("done");
    // 服务端一句都没写、也没说翻完了 —— 再点下去只是白烧额度。
    stalled = out.applied > 0 ? 0 : stalled + 1;
    if (stalled >= 2) return finish("stalled");
    if (opts.shouldStop?.()) return finish("cancelled");
  }
  return finish("limit");
}

/** 把自动翻译的结果写成一句人话（页面顶部提示用）。 */
export function autoTranslateMessage(r: AutoTranslateResult): string {
  const done = r.startedWith - r.remaining;
  const head = done > 0 ? `AI 译了 ${done} 句，请在步骤 ③ 逐句校对` : "这次没有新增译文";
  // 真实消耗写在每条提示里：额度是共享的，用户有权知道这次点了多少钱（token）。
  const cost = r.tokens > 0 ? `（消耗约 ${humanTokens(r.tokens)} token）` : "";
  switch (r.stop) {
    case "done":
      return `${head}${cost}。这个语言已经全部有译文了（AI 草稿仍需校对后再导出）。`;
    case "limit":
      return `${head}${cost}；本次连跑了 ${r.calls} 轮，还剩 ${r.remaining} 句。歇一会儿再点一次可以接着翻（接口限流 60 次/小时）。`;
    case "cancelled":
      return `${head}${cost}；已按你的要求停下，还剩 ${r.remaining} 句。`;
    case "stalled":
      return `${head}${cost}；模型连着两轮都没给出可用译文（还剩 ${r.remaining} 句），先停下来了。可以换一个模型，或在步骤 ③ 手动补几句再试。`;
    case "error":
      return `${head}${cost}；中途失败停下了，还剩 ${r.remaining} 句。${
        r.error instanceof Error ? `原因：${r.error.message}` : ""
      }`;
  }
}
