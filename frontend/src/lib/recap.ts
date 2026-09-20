/**
 * 前情提要的前端纯逻辑：往正文里插入回述。
 *
 * 只动 `prose`（大白话正文，也是轻小说/网文的主写作面）：
 * 不动 blocks，所以 VN 作者的脚本一行都不会被碰到。
 */

import type { SceneChapter } from "../types/vn";

export type InsertPosition = "prepend" | "append";

export function insertRecapIntoProse(
  prose: string | undefined,
  text: string,
  position: InsertPosition
): string {
  const body = (text ?? "").trim();
  const current = prose ?? "";
  if (!body) return current;
  if (!current.trim()) return body;
  return position === "prepend"
    ? `${body}\n\n${current}`
    : `${current}\n\n${body}`;
}

/** 返回插入了回述的新章节（其余字段原样）。 */
export function chapterWithRecap(
  chapter: SceneChapter,
  text: string,
  position: InsertPosition = "prepend"
): SceneChapter {
  return { ...chapter, prose: insertRecapIntoProse(chapter.prose, text, position) };
}
