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
 * 只在两个数都拿得到时给结论：作者自己写过的日均净增（近 7 个有产出的天），
 * 以及当前章的实时字数。**样本不足时返回 null**，界面显示"样本不够"——
 * 编一个数字出来比不给更糟。
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
