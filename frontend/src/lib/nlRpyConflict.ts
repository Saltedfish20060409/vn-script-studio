/**
 * NL↔RPY 冲突判定（与后端 nl_rpy_map.detect_conflict 同口径，前端可离线用）。
 */
import { proseFingerprint } from "./scriptProse";
import type { ScriptBlock, VnProject } from "../types/vn";

export type NlRpyConflict = "none" | "prose" | "blocks" | "both";

function blocksFingerprint(blocks: ScriptBlock[] | undefined): string {
  // 轻量：复用 proseFingerprint 对 JSON 串
  return proseFingerprint(JSON.stringify(blocks || []));
}

export function detectNlRpyConflict(
  chapter: VnProject["chapters"][number] | undefined
): NlRpyConflict {
  if (!chapter?.nlRpyMap) return "none";
  const m = chapter.nlRpyMap;
  const proseFp = proseFingerprint(chapter.prose || "");
  const blocksFp = blocksFingerprint(chapter.blocks);
  const proseDirty = Boolean(m.proseFingerprint) && proseFp !== m.proseFingerprint;
  const blocksDirty =
    Boolean(m.blocksFingerprint) && blocksFp !== m.blocksFingerprint;
  if (proseDirty && blocksDirty) return "both";
  if (proseDirty) return "prose";
  if (blocksDirty) return "blocks";
  return "none";
}

export function nlRpyConflictLabel(c: NlRpyConflict): string {
  if (c === "both") return "正文与脚本都改过，需选择保留哪一面或分段重映射";
  if (c === "prose") return "正文已变，脚本待按映射更新";
  if (c === "blocks") return "脚本已手调，与映射可能漂移";
  return "";
}
