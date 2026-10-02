/**
 * 快照恢复保护窗：防止「restore 已落库 → 旧 autosave/空编辑器 PUT 盖回」。
 *
 * 时序（修订方案）：
 * - T0 请求发出：打开保护窗（in-flight，直到成功/失败）
 * - T1 成功返回：再保证至少满 N 秒（now + N）
 * - 失败：立即清零
 */

import { blocksToEditable } from "./scriptCodec";
import { storedProse } from "./scriptProse";
import type { Character, ScriptBlock, VnProject } from "../types/vn";
import { diffProjectAgainst } from "./projectDiff";

export const RESTORE_GUARD_MS = 5000;

/** 请求进行中占位：远大于任何合理 API 耗时，成功/失败时会被改写。 */
export const RESTORE_GUARD_IN_FLIGHT_UNTIL = Number.MAX_SAFE_INTEGER;

export const RESTORE_LOADING_STATUS = "正在加载快照，暂不允许编辑";
export const RESTORE_FAILED_STATUS = "恢复失败，请重试";
export const RESTORE_DIRTY_CONFIRM =
  "恢复快照会丢弃当前未保存的编辑器内容。是否继续？";

/** 409 冲突说明（章级/全量共用）：说清刷新 vs 保留本地的后果。 */
export const PROJECT_CONFLICT_DETAIL =
  "该项目已在其他位置被修改。刷新将获取最新数据；保留本地将覆盖服务器版本，对方未保存的内容会丢失。";

export type WriteMode = "prose" | "rpy";

/** T0：请求发出 — 进入 in-flight 保护（API 再慢也不提前放行）。 */
export function openRestoreGuardAtRequest(_now: number): number {
  return RESTORE_GUARD_IN_FLIGHT_UNTIL;
}

/** T1：成功 — 从「现在」再保护满 N 秒。 */
export function extendRestoreGuardOnSuccess(
  _previousUntil: number,
  now: number
): number {
  return now + RESTORE_GUARD_MS;
}

export function clearRestoreGuard(): number {
  return 0;
}

export function isRestoreGuardActive(until: number, now: number): boolean {
  return until > now;
}

/** 编辑器缓冲相对「上次保存」章面是否脏。 */
export function isEditorDirtyVsSaved(opts: {
  editorText: string;
  saved: VnProject | null;
  chapterId: string;
  mode: WriteMode;
  characters: Character[];
}): boolean {
  const { editorText, saved, chapterId, mode, characters } = opts;
  if (!saved) {
    return editorText.trim().length > 0;
  }
  const ch = saved.chapters.find((c) => c.id === chapterId);
  const expected =
    mode === "prose"
      ? storedProse(ch)
      : blocksToEditable(
          (ch?.blocks ?? []) as ScriptBlock[],
          characters.length ? characters : saved.characters ?? []
        );
  return editorText !== expected;
}

/**
 * 恢复成功后是否应跳过一次「立即保存」。
 * lastSaved 已对齐 restored 且候选无 diff → 不发 PUT（补 5）。
 */
export function shouldSkipPersistBecauseClean(opts: {
  lastSaved: VnProject | null;
  candidate: VnProject;
}): boolean {
  const diff = diffProjectAgainst(opts.lastSaved, opts.candidate);
  return Boolean(opts.lastSaved) && !diff.hasChanges;
}

/** persist 入口：保护窗内一律禁 PUT。 */
export function shouldBlockPersistForRestoreGuard(
  guardUntil: number,
  now: number
): boolean {
  return isRestoreGuardActive(guardUntil, now);
}
