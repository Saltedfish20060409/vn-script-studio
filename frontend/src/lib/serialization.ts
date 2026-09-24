/**
 * 连载工作流（纯函数层）：连续更新天数、更新日历、存稿/发布进度。
 *
 * 为什么单独一层：这一层全是"给定写作记录（activity）与章节，得到几个数字"的确定性
 * 计算，可以直接跑单测。面板只负责画出来。
 *
 * 口径上最需要说清楚的一条：**热力图上的"有更新"= 当日净增 > 0**（与「写作统计」
 * 同一口径，来自后端 `/stats` 的逐日活动记录）。它量的是"今天有没有往前写"，
 * 不是"今天有没有发新章"——改旧章 200 字也算数，删了 300 字就不算。
 */

import type { WritingActivityDay } from "../api/projects";
import type { SceneChapter } from "../types/vn";
// 字数口径复用 wordCount（与后端 writing_stats 同一规则），别在这里再造一份
import { countChapterWords } from "./wordCount";

const DAY_MS = 24 * 60 * 60 * 1000;

/** 本地时区的 YYYY-MM-DD（不能用 toISOString：那是 UTC，晚上写的东西会算到明天）。 */
export function dayKey(date: Date): string {
  return `${date.getFullYear()}-${String(date.getMonth() + 1).padStart(2, "0")}-${String(
    date.getDate()
  ).padStart(2, "0")}`;
}

export function todayKey(now: Date = new Date()): string {
  return dayKey(now);
}

function shiftDays(now: Date, days: number): Date {
  const d = new Date(now.getTime());
  d.setDate(d.getDate() + days);
  return d;
}

/** 这一天算不算"写了"：净增 > 0（删字不算，只改标点也不算）。 */
export function wroteOn(day: WritingActivityDay | null | undefined): boolean {
  return Boolean(day && day.net > 0);
}

export interface StreakInfo {
  /** 当前连续更新天数 */
  current: number;
  /** 历史最长连续更新天数 */
  longest: number;
  /** 最近一次"写了"的日期（没有就是空串） */
  lastWriteDate: string;
  /** 今天是否已经写了 */
  wroteToday: boolean;
  /** 总产出天数 */
  totalDays: number;
}

/**
 * 连续更新天数。
 *
 * 规则（这是产品判断，写在这里免得以后被改乱）：
 * - **今天还没写不算断**：连续性允许"今天稍后补上"，所以从昨天开始往回数。
 *   否则作者每天早上打开工具都会看到"连续 0 天"，那是纯粹的错误反馈。
 * - 昨天也没写 → 连续天数就是 0（真的断了）。
 * - 最长连续只看历史记录里出现过的日期。
 */
export function streakInfo(
  activity: WritingActivityDay[],
  now: Date = new Date()
): StreakInfo {
  const written = new Set(
    (activity ?? []).filter(wroteOn).map((d) => d.date)
  );
  const wroteToday = written.has(todayKey(now));

  // 当前连续：从今天（写了的话）或昨天往回数
  let current = 0;
  let cursor = wroteToday ? now : shiftDays(now, -1);
  while (written.has(dayKey(cursor))) {
    current += 1;
    cursor = shiftDays(cursor, -1);
  }

  // 最长连续：把日期排序后扫一遍，隔一天就断开
  const dates = [...written].sort();
  let longest = 0;
  let run = 0;
  let prev: Date | null = null;
  for (const key of dates) {
    const d = new Date(`${key}T00:00:00`);
    if (Number.isNaN(d.getTime())) continue;
    run = prev && Math.round((d.getTime() - prev.getTime()) / DAY_MS) === 1 ? run + 1 : 1;
    longest = Math.max(longest, run);
    prev = d;
  }

  return {
    current,
    longest,
    lastWriteDate: dates.length ? dates[dates.length - 1] : "",
    wroteToday,
    totalDays: dates.length,
  };
}

export interface CalendarCell {
  date: string;
  /** 净增字数（没有记录就是 0） */
  net: number;
  /** 有没有记录（哪怕净增为负）——用来区分"没写"与"删了" */
  hasRecord: boolean;
  /** 0–4 的色阶（按净增相对最大值） */
  level: number;
  /** 是否为未来日期（画格子时占位） */
  future: boolean;
  /** 是不是今天 */
  today: boolean;
}

/**
 * 更新日历（按周分列，最后一列是本周）。
 *
 * 与「写作统计」的 30 天热力图差别：这里按**周对齐**（周一起），因为连载作者的
 * 节奏单位是"这周更了几章"，不是"最近 30 天"。返回的是按列排好的二维数组。
 */
export function updateCalendar(
  activity: WritingActivityDay[],
  weeks = 12,
  now: Date = new Date()
): CalendarCell[][] {
  const byDate = new Map((activity ?? []).map((d) => [d.date, d]));
  const maxNet = Math.max(1, ...[...byDate.values()].map((d) => Math.max(0, d.net)));

  // 对齐到本周周一
  const weekday = (now.getDay() + 6) % 7; // 周一=0
  const thisMonday = shiftDays(now, -weekday);
  const columns: CalendarCell[][] = [];
  for (let w = weeks - 1; w >= 0; w -= 1) {
    const column: CalendarCell[] = [];
    for (let d = 0; d < 7; d += 1) {
      const date = shiftDays(thisMonday, -w * 7 + d);
      const key = dayKey(date);
      const record = byDate.get(key);
      const net = record?.net ?? 0;
      column.push({
        date: key,
        net,
        hasRecord: Boolean(record),
        level: net > 0 ? Math.max(1, Math.round((net / maxNet) * 4)) : 0,
        future: date.getTime() > now.getTime() + DAY_MS - 1,
        today: key === todayKey(now),
      });
    }
    columns.push(column);
  }
  return columns;
}

export type PublishState = "published" | "draft" | "empty";

export function publishState(chapter: SceneChapter): PublishState {
  if (chapter.publishedAt) return "published";
  return countChapterWords(chapter) > 0 ? "draft" : "empty";
}

export interface SerializationStats {
  /** 总章数 */
  total: number;
  /** 已发布章数 */
  published: number;
  /** 存稿：写了但还没发 */
  drafts: number;
  /** 空章：还没写 */
  empty: number;
  publishedWords: number;
  draftWords: number;
  /** 下一章该发哪一章（第一个"写了没发"的）；没有就返回 null */
  nextToPublish: { id: string; title: string; words: number } | null;
}

export function serializationStats(chapters: SceneChapter[]): SerializationStats {
  let published = 0;
  let drafts = 0;
  let empty = 0;
  let publishedWords = 0;
  let draftWords = 0;
  let nextToPublish: SerializationStats["nextToPublish"] = null;
  for (const chapter of chapters ?? []) {
    const state = publishState(chapter);
    const words = countChapterWords(chapter);
    if (state === "published") {
      published += 1;
      publishedWords += words;
    } else if (state === "draft") {
      drafts += 1;
      draftWords += words;
      if (!nextToPublish) {
        nextToPublish = { id: chapter.id, title: chapter.title, words };
      }
    } else {
      empty += 1;
    }
  }
  return {
    total: (chapters ?? []).length,
    published,
    drafts,
    empty,
    publishedWords,
    draftWords,
    nextToPublish,
  };
}

/**
 * 发布节奏建议：按"每天能写多少"估这一章还要几天。
 *
 * 只在两个数都拿得到时给结论：作者自己写过的日均净增（近 7 个**有产出的天**），
 * 以及当前章的实时字数。**样本不足时返回 null**，界面显示"样本不够"——
 * 编一个数字出来比不给更糟。
 *
 * 注意它算的是"开工日能写多少"（pace），不是"日历日均"（后者见
 * `recentAverageOverDays`）。两个数用途不同：估"还要几天写完"用开工日产能才准；
 * 核对"日更目标是否可达"必须把没写的天算进去。
 */
export function paceEstimate(
  activity: WritingActivityDay[],
  remainingWords: number
): { perDay: number; days: number } | null {
  const recent = (activity ?? [])
    .filter(wroteOn)
    .slice(-7)
    .map((d) => d.net);
  if (recent.length < 3 || remainingWords <= 0) return null;
  const perDay = Math.round(recent.reduce((a, b) => a + b, 0) / recent.length);
  if (perDay <= 0) return null;
  return { perDay, days: Math.max(1, Math.ceil(remainingWords / perDay)) };
}

/**
 * 近 N 个**日历日**的日均净增（没写的天按 0 计入）。
 *
 * 依据 Locke & Latham 的目标设定理论：目标要"有难度但可达"，否则承诺度会掉——
 * 而这个数字是判断"可达"的唯一实据。用日历日均而不是开工日均：一周写三天、
 * 每天 3000 字的人，日更 3000 是做不到的，但按开工日均算会显示"已达标"——那是自欺。
 */
export function recentAverageOverDays(
  activity: WritingActivityDay[],
  days = 7,
  now: Date = new Date()
): { perDay: number; totalNet: number; days: number; activeDays: number } {
  const window = Math.max(1, Math.floor(days));
  const keys = new Set<string>();
  for (let i = 0; i < window; i += 1) keys.add(dayKey(shiftDays(now, -i)));
  let total = 0;
  let active = 0;
  for (const day of activity ?? []) {
    if (!keys.has(day.date)) continue;
    if (day.net > 0) {
      total += day.net;
      active += 1;
    }
  }
  return {
    perDay: Math.round(total / window),
    totalNet: total,
    days: window,
    activeDays: active,
  };
}

export interface GoalCalibration {
  /** 目标与近期实际节奏的关系 */
  verdict: "no-goal" | "insufficient" | "comfortable" | "stretch" | "unreachable";
  /** 给作者看的一句话（描述事实，不劝、不夸） */
  message: string;
}

/**
 * 日更目标与近期实际节奏的对照。
 *
 * 为什么值得专门做：目标设定理论里"反馈"与"目标难度"是决定成效的两个调节变量。
 * 一个长期达不到的目标不会激励人，只会让人不再看这个数字——所以这里给的是**中性的事实
 * 对照**（近期日历日均 vs 目标），不是鼓励也不是责备。
 *
 * 阈值是手调的经验值（代码里注明）：日均 ≥ 目标 → comfortable；≥ 一半 → stretch；
 * 低于一半 → unreachable（这时该建议调目标，而不是让人硬撑）。
 * 近 7 天产出少于 2 天时不下结论——样本不足时任何"你落后了"都是噪音。
 */
export function calibrateDailyGoal(
  activity: WritingActivityDay[],
  target: number,
  now: Date = new Date()
): GoalCalibration {
  if (!(target > 0)) {
    return { verdict: "no-goal", message: "" };
  }
  const recent = recentAverageOverDays(activity, 7, now);
  if (recent.activeDays < 2) {
    return {
      verdict: "insufficient",
      message: "近 7 天产出少于 2 天，样本不足——再写几天就有对照了",
    };
  }
  if (recent.perDay >= target) {
    return {
      verdict: "comfortable",
      message: `近 7 天日均 ${recent.perDay} 字，已经能稳定达到这个目标`,
    };
  }
  if (recent.perDay * 2 >= target) {
    return {
      verdict: "stretch",
      message: `近 7 天日均 ${recent.perDay} 字，目标 ${target} 字偏紧但够得着`,
    };
  }
  return {
    verdict: "unreachable",
    message:
      `近 7 天日均 ${recent.perDay} 字，离目标 ${target} 字差得较远——` +
      "把它调低到能稳定做到的水平，比长期差一截更有用",
  };
}
