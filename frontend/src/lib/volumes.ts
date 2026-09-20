/**
 * 卷的纯逻辑：分组、进度、增删改与章节归属。
 *
 * 全部做成纯函数（拿旧值返回新值），一是不用起界面就能测，二是 StudioApp 里
 * 所有改动都走同一套 `updateActive` 保存链路，不会出现"某个入口忘了存"。
 */

import type { SceneChapter, Volume } from "../types/vn";
import { countChapterWords } from "./wordCount";

/** 「未分卷」用空字符串表示（和后端 normalize 一致：空 volumeId = 没归卷） */
export const LOOSE_VOLUME_ID = "";

export type VolumeRow = {
  id: string;
  title: string;
  /** 1 基序号；未分卷是 volumes.length + 1 */
  index: number;
  chapters: SceneChapter[];
  /** 该卷章节在 chapters 里的全局序号（0 基），用于章节条上显示 01/02… */
  globalIndexes: number[];
  words: number;
};

export function normalizeVolumeId(volumeId: string | undefined | null): string {
  return (volumeId ?? "").trim();
}

/** 某卷里的章节（保持原有顺序）。 */
export function chaptersInVolume(
  chapters: SceneChapter[],
  volumeId: string
): SceneChapter[] {
  const target = normalizeVolumeId(volumeId);
  return chapters.filter((c) => normalizeVolumeId(c.volumeId) === target);
}

/**
 * 卷的展示行：按 volumes 顺序 + 末尾「未分卷」。
 * 未分卷那一行只在**真的有章节**时才给（否则空卷列表会多出一行噪音）。
 */
export function buildVolumeRows(
  volumes: Volume[] | undefined,
  chapters: SceneChapter[]
): VolumeRow[] {
  const list = volumes ?? [];
  const rows: VolumeRow[] = list.map((vol, i) => {
    const own = chaptersInVolume(chapters, vol.id);
    return {
      id: vol.id,
      title: vol.title || `第${i + 1}卷`,
      index: i + 1,
      chapters: own,
      globalIndexes: own.map((c) => chapters.indexOf(c)),
      words: own.reduce((sum, c) => sum + countChapterWords(c), 0),
    };
  });
  const loose = chaptersInVolume(chapters, LOOSE_VOLUME_ID);
  if (loose.length > 0) {
    rows.push({
      id: LOOSE_VOLUME_ID,
      title: "未分卷",
      index: list.length + 1,
      chapters: loose,
      globalIndexes: loose.map((c) => chapters.indexOf(c)),
      words: loose.reduce((sum, c) => sum + countChapterWords(c), 0),
    });
  }
  return rows;
}

/** 新建一卷（标题留空时给个默认名，序号按当前卷数）。返回新数组与新卷 id。 */
export function addVolume(
  volumes: Volume[] | undefined,
  title: string,
  id: string
): { volumes: Volume[]; id: string } {
  const list = [...(volumes ?? [])];
  const clean = title.trim() || `第${list.length + 1}卷`;
  list.push({ id, title: clean });
  return { volumes: list, id };
}

export function renameVolume(
  volumes: Volume[] | undefined,
  id: string,
  title: string
): Volume[] {
  const clean = title.trim();
  return (volumes ?? []).map((v) => (v.id === id && clean ? { ...v, title: clean } : v));
}

/** 上移/下移一卷（顺序决定导出与界面顺序，所以得能调）。 */
export function moveVolume(
  volumes: Volume[] | undefined,
  id: string,
  delta: number
): Volume[] {
  const list = [...(volumes ?? [])];
  const from = list.findIndex((v) => v.id === id);
  if (from < 0) return list;
  const to = from + delta;
  if (to < 0 || to >= list.length) return list;
  const [item] = list.splice(from, 1);
  list.splice(to, 0, item);
  return list;
}

/**
 * 删一卷：它的章节回到「未分卷」。
 * 必须同时清 chapter.volumeId，否则章节会指向一个不存在的卷（界面找不到归属）。
 */
export function deleteVolume(
  volumes: Volume[] | undefined,
  chapters: SceneChapter[],
  id: string
): { volumes: Volume[]; chapters: SceneChapter[] } {
  return {
    volumes: (volumes ?? []).filter((v) => v.id !== id),
    chapters: chapters.map((c) =>
      normalizeVolumeId(c.volumeId) === id ? { ...c, volumeId: undefined } : c
    ),
  };
}

/** 把一章移入某卷（"" = 移出到未分卷）。 */
export function assignChapterToVolume(
  chapters: SceneChapter[],
  chapterId: string,
  volumeId: string
): SceneChapter[] {
  const target = normalizeVolumeId(volumeId);
  return chapters.map((c) =>
    c.id === chapterId ? { ...c, volumeId: target || undefined } : c
  );
}

/** 该章属于哪一卷（未分卷返回 ""）。 */
export function volumeIdOfChapter(
  chapters: SceneChapter[],
  chapterId: string
): string {
  const ch = chapters.find((c) => c.id === chapterId);
  return normalizeVolumeId(ch?.volumeId);
}
