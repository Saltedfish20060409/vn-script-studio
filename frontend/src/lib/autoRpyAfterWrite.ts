/**
 * P5-B：写入 prose 后是否应自动生成 RPY。
 *
 * 规则（追问补丁）：
 * - 纯 LN（从未手动「根据剧本生成」建过 `rpyFromProseHash`）→ **永不**自动。
 * - 第一次手动 generate 建立 hash 基线后，此后仅当 hash 相对 prose **过期**时自动跟随。
 * - 有脚本正文但无 hash（手调/旧数据）→ **不**自动；须手动生成一次建立基线。
 */

import { rpyIsStale } from "./scriptProse";
import type { VnProject } from "../types/vn";

/**
 * @returns true = 应自动调 generate_rpy_from_prose
 */
export function shouldAutoGenerateRpyAfterProseWrite(
  chapter: VnProject["chapters"][number] | undefined
): boolean {
  if (!chapter) return false;
  const prose = (chapter.prose || "").trim();
  if (!prose) return false;

  const hasHash = Boolean((chapter.rpyFromProseHash || "").trim());
  // 纯 LN / 未建基线：永不自动
  if (!hasHash) return false;

  return rpyIsStale(chapter);
}

/** 设置关闭时的提示文案（不自动生成）。 */
export function autoRpySkippedBySettingMessage(): string {
  return "正文档已写入；未自动更新脚本（设置 → Agent 高级可开启）";
}

/** 纯 LN / 无需自动时的轻提示（可选展示）。 */
export function autoRpyNotNeededMessage(): string {
  return "正文档已写入。需要脚本时再点「根据剧本生成」。";
}
