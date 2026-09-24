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
  /**
   * 一键取回要发出去的原话（后端给的第一人称指令）。
   *
   * **没有工具能取回时后端不给这个字段**（例如作者上传的参考资料）——界面据此不显示按钮，
   * 而不是给一个点了没用的按钮。前端也不自己拼这句话：工具名只有后端一处真源。
   */
  instruction?: string;
};

export type BudgetNotice = {
  /** 因为篇幅没装下的那些（要处理） */
  missing: BudgetRow[];
  /** 按任务省去的那些（属于设计，折叠显示） */
  byDesign: BudgetRow[];
  /** 有没有"没装下"这件事 */
  hasMissing: boolean;
  /** 有没有任何一项能一键取回 */
  hasRetrievable: boolean;
};

function fmt(n: number | undefined): string {
  return typeof n === "number" && Number.isFinite(n) ? Math.round(n).toLocaleString("en-US") : "";
}

function clean(value: unknown): string {
  return typeof value === "string" ? value.trim() : "";
}

/** 把报告翻成两组可显示的清单；报告缺失时返回空（界面就不显示这一段）。 */
export function budgetNotice(report?: AgentBudgetReport | null): BudgetNotice {
  if (!report) {
    return { missing: [], byDesign: [], hasMissing: false, hasRetrievable: false };
  }

  const missing: BudgetRow[] = [];

  for (const part of report.trimmedParts ?? []) {
    if (!part || !part.label) continue;
    const detail =
      clean(part.detail) ||
      (typeof part.keptChars === "number" && typeof part.totalChars === "number"
        ? `只带了 ${fmt(part.keptChars)} / ${fmt(part.totalChars)} 字`
        : "");
    const instruction = clean(part.instruction);
    missing.push({
      label: part.label,
      detail,
      action: clean(part.retrieve),
      ...(instruction ? { instruction } : {}),
    });
  }

  for (const section of report.droppedSections ?? []) {
    if (!section || !section.label) continue;
    const instruction = clean(section.instruction);
    missing.push({
      label: section.label,
      detail: "因为篇幅被整块省去了",
      action: clean(section.retrieve),
      ...(instruction ? { instruction } : {}),
    });
  }

  const byDesign: BudgetRow[] = (report.excludedByTask ?? [])
    .filter((s) => s && s.label)
    .map((s) => ({
      label: s.label,
      detail: "按任务省去（这类资料对写正文没有信息量）",
      action: "",
    }));

  return {
    missing,
    byDesign,
    hasMissing: missing.length > 0,
    hasRetrievable: missing.some((row) => Boolean(row.instruction)),
  };
}

/**
 * 「一次把没装下的都取回来」要发出去的那句话（可直接发送）。
 *
 * 只把**能取回的**那些拼进去（后端给了 `instruction` 的），并在结尾要求它确认读到了哪一段——
 * 否则作者无法判断"它到底补上了没有"。一项都取不回来时返回空串（界面不显示这个按钮）。
 */
export function retrieveAllMessage(notice: BudgetNotice): string {
  const steps = notice.missing
    .map((row) => row.instruction)
    .filter((text): text is string => Boolean(text));
  if (steps.length === 0) return "";
  return [
    "这次上下文里没装下下面这些内容，请先补齐再继续：",
    ...steps.map((text) => `- ${text}`),
    "补齐后先告诉我你读到了哪一段，再按我上一条要求继续。",
  ].join("\n");
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
