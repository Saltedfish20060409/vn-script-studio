/**
 * 多变体的展示口径（纯函数，便于单测）。
 *
 * 后端按证据给 1–3 版改写排了序（见 `core/variant_select.py`：确定性检查 +
 * 候选间一致度 + 模型自身置信度）。这里只负责**把证据摆出来**，并且守一条纪律：
 *
 * > **没测量的信号不显示成 0。**
 *
 * 例如本地模型或未收录的模型拿不到 logprobs 时，置信度是 `null`——界面上必须
 * 什么都不显示（或"未测"），不能画成 0.00，否则作者会以为"模型完全没把握"。
 */
import type { MarkVariantRow } from "../api/projects";

/** 版本按钮上的短标签：第一顺位标"推荐"，其余标顺位。 */
export function variantBadge(row: MarkVariantRow | undefined, fallbackRank: number): string {
  if (!row) return `第 ${fallbackRank} 版`;
  if (row.recommended || row.rank === 1) return `推荐 · 第 ${row.variantIndex + 1} 版`;
  return `第 ${row.variantIndex + 1} 版`;
}

function num(value: unknown, digits = 2): string | null {
  // 只接受真正的数字：`null`/`undefined`/NaN 一律当"未测"，绝不显示成 0
  if (typeof value !== "number" || !Number.isFinite(value)) return null;
  return value.toFixed(digits);
}

/** 悬停提示：把这一版的证据逐条列出来（缺的项不列，也不写 0）。 */
export function variantTitle(row: MarkVariantRow | undefined): string {
  if (!row) return "";
  const bits: string[] = [];
  const score = num(row.score);
  if (score) bits.push(`综合 ${score}`);
  const certainty = row.certainty ?? null;
  const confidence = certainty ? num(certainty.composite) : null;
  if (confidence) {
    bits.push(`置信度 ${confidence}${certainty?.thin ? "（样本短，仅供参考）" : ""}`);
  }
  const consensus = num(row.consensus);
  if (consensus) bits.push(`与其余候选一致度 ${consensus}`);
  if (row.temperature != null) bits.push(`温度 ${Number(row.temperature).toFixed(2)}`);
  if (row.chars) bits.push(`${row.chars} 字`);
  if (row.problems?.length) bits.push(`问题：${row.problems.join("；")}`);
  return bits.join(" · ");
}

/** 一行取舍说明（后端 `selectionNote` 已经写清了用了哪些信号、缺了哪些）。 */
export function selectionSummary(
  note: string | undefined,
  ranking: MarkVariantRow[] | undefined
): string {
  const text = (note || "").trim();
  if (text) return text;
  if ((ranking?.length ?? 0) > 1) {
    return "多版改写：后端这次没有给出取舍说明（旧版本后端可能没带这个字段）。";
  }
  return "";
}

/** 这一版是否有"能确定"的问题（后端已按此把有问题的版本排到后面）。 */
export function hasProblems(row: MarkVariantRow | undefined): boolean {
  return Boolean(row?.problems?.length);
}
