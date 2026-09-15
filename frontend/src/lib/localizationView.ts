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
