/**
 * 「这次没装下什么、怎么取回来」的展示口径（纯函数，便于单测）。
 *
 * 界面上要守住的三件事：
 *
 * 1. **两类原因不能混**：`droppedSections` / `trimmedParts` 是**因为篇幅没装下**（要处理），
 *    `excludedByTask` 是**按任务省去**（立绘、变量这类机制资料对写散文没用，属于设计）。
 *    混在一起会让作者以为"AI 少读了东西"，然后去关一堆本来就不该带的资料。
 * 2. **每一行都要能照着做**：取回方式由后端给出（`retrieve`），前端原样显示，
 *    不在本地编一套工具名（工具名写错比不写更糟）。
 * 3. **没有就不显示**：没有被裁过时这一段整块不出现（不是显示"0 项"）。
 */
import type { AgentBudgetReport } from "../types/vn";

export type BudgetRow = {
  /** 展示用标题，例如「当前章正文（第一章）」 */
  label: string;
  /** 具体说明，例如「只带了末尾 24,000 / 60,000 字」 */
  detail: string;
  /** 照着做的话，例如「让它用 get_chapter 读「第一章」的完整正文」 */
  action: string;
};

export type BudgetNotice = {
  /** 因为篇幅没装下的那些（要处理） */
  missing: BudgetRow[];
  /** 按任务省去的那些（属于设计，折叠显示） */
  byDesign: BudgetRow[];
  /** 有没有"没装下"这件事 */
  hasMissing: boolean;
};

function fmt(n: number | undefined): string {
  return typeof n === "number" && Number.isFinite(n) ? Math.round(n).toLocaleString("en-US") : "";
}

/** 把报告翻成两组可显示的清单；报告缺失时返回空（界面就不显示这一段）。 */
export function budgetNotice(report?: AgentBudgetReport | null): BudgetNotice {
  if (!report) {
    return { missing: [], byDesign: [], hasMissing: false };
  }

  const missing: BudgetRow[] = [];

  for (const part of report.trimmedParts ?? []) {
    if (!part || !part.label) continue;
    const detail =
      part.detail ||
      (typeof part.keptChars === "number" && typeof part.totalChars === "number"
        ? `只带了 ${fmt(part.keptChars)} / ${fmt(part.totalChars)} 字`
        : "");
    missing.push({ label: part.label, detail, action: part.retrieve || "" });
  }

  for (const section of report.droppedSections ?? []) {
    if (!section || !section.label) continue;
    missing.push({
      label: section.label,
      detail: "因为篇幅被整块省去了",
      action: section.retrieve || "",
    });
  }

  const byDesign: BudgetRow[] = (report.excludedByTask ?? [])
    .filter((s) => s && s.label)
    .map((s) => ({
      label: s.label,
      detail: "按任务省去（这类资料对写正文没有信息量）",
      action: "",
    }));

  return { missing, byDesign, hasMissing: missing.length > 0 };
}

/**
 * 「这次带了哪些资料」的一句话摘要（给状态行用）。
 *
 * 这里以前是拿正则去过滤 `included` 里的中文串（`/工艺卡|bible|角色|…/`），
 * 加一个新资料块就得同时改那个正则，漏了就不显示。现在用后端给的结构化清单。
 */
export function includedSummary(report?: AgentBudgetReport | null, max = 6): string {
  const labels = (report?.includedSections ?? [])
    .filter((s) => s && s.label)
    .map((s) => s.label);
  if (labels.length === 0) return "";
  const shown = labels.slice(0, max).join("·");
  return labels.length > max ? `参考 ${shown} 等 ${labels.length} 项` : `参考 ${shown}`;
}
