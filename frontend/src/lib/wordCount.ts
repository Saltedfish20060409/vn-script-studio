/**
 * 字数统计（与后端 `app/services/writing_stats.py` 同一套规则）。
 *
 * 规则：
 * - 汉字逐字计数，拉丁字母/数字按词计数；
 * - **一章优先数 `prose`（大白话正文），正文为空才数 script blocks**。
 *   两者相加会把"由正文生成的脚本"数两遍；而只数 blocks 会让纯用正文写作的人
 *   （网文/轻小说的主流用法）恒为 0 字——那是被实测确认过的老问题。
 *
 * 为什么前端也有一份：卷头/章节条要在**打字时立刻**更新字数，等接口回来太慢。
 * 权威数字仍以 `/stats` 接口为准（写作统计面板用它），两边的规则必须保持一致。
 */

import type { SceneChapter, ScriptBlock } from "../types/vn";

const CJK_RE = /[\u4e00-\u9fff]/g;
const LATIN_RE = /[A-Za-z0-9]+/g;

export function countWords(text: string): number {
  if (!text) return 0;
  return (text.match(CJK_RE)?.length ?? 0) + (text.match(LATIN_RE)?.length ?? 0);
}

export function countBlocksWords(blocks: ScriptBlock[] | undefined): number {
  let total = 0;
  for (const b of blocks ?? []) {
    const type = (b as { type?: string }).type;
    if (type === "narration" || type === "dialogue") {
      total += countWords(String((b as { text?: string }).text ?? ""));
    } else if (type === "raw") {
      total += countWords(String((b as { code?: string }).code ?? ""));
    } else if (type === "menu") {
      const choices = (b as { choices?: Array<{ text?: string }> }).choices ?? [];
      for (const c of choices) total += countWords(String(c?.text ?? ""));
    }
  }
  return total;
}

/** 一章写了多少字（正文优先；正文为空才回落到脚本）。 */
export function countChapterWords(chapter: Pick<SceneChapter, "prose" | "blocks">): number {
  const prose = (chapter.prose ?? "").trim();
  if (prose) return countWords(prose);
  return countBlocksWords(chapter.blocks);
}

/** 人看的字数：12345 → 1.2万 */
export function formatWords(words: number): string {
  if (words < 10000) return String(words);
  const wan = words / 10000;
  return `${wan >= 10 ? Math.round(wan) : wan.toFixed(1)}万`;
}
