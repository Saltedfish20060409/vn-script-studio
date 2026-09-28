/**
 * 「本次运行」这堆元信息的**折叠态压缩**与折叠偏好。
 *
 * 症状（作者反馈）：Agent 页面底部那一坨说明——「讨论 · 仅讨论未改工程 · 工艺关 · 参考
 * 作品信息·写作规则·角色卡·角色关系·设定 bible（世界观 / 大纲 / 背景）·时间线 等 11 项」
 * 「本次上下文 13,578 字（上限 48,000）」「依据 4 项（点开看它读到的原文摘录）」
 * 「⚙ 资料 AI 会参考你的设定与资料（点开可以少给它一些）」——不读也要占着对话区的高度。
 * 它们是**可核对的凭据**（作者据此判断"它到底读到了什么"），所以不删，只收起来。
 *
 * 折叠态保留什么（这是本文件的唯一判断，写成纯函数好测）：
 * - 保留"改变了这次行为"的短标签：任务、结果（有没有写进工程）、工艺档、自检、写后闸、
 *   预取/视角次数、被摘掉的资料项数；
 * - 收起纯清单：「参考 …」只留项数；上下文只在**接近上限或被裁**时才说上限，
 *   平时压成「语境 13,578 字」。
 * - **告警绝不折叠**：被裁过（有资料没装下）、写后闸未过、本次不带 N 项——这些要作者当场
 *   看见，折叠态也必须出现（这一条由调用方保证，见 AgentChat 的 budgetInfo/excluded）。
 */

/** 折叠态摘要的输入。字段名沿用 AgentChat 里那几个短标签的语义。 */
export type RunInfoBits = {
  taskName?: string;
  resultBit?: string;
  craftShort?: string;
  reviewShort?: string;
  gateShort?: string;
  prefetchShort?: string;
  lensShort?: string;
  /** 本次带了几项资料（`budgetReport.includedSections.length`） */
  refCount?: number;
  /** `contextUsage(meta).text`，例如 "本次上下文 13,578 字（上限 48,000）" */
  contextText?: string;
  contextTruncated?: boolean;
  contextNearLimit?: boolean;
  /** `includedDetails` 的条数（「依据 N 项」） */
  evidenceCount?: number;
  /** 本次主动摘掉的资料块数（>0 时必须显示，属于告警） */
  excludedCount?: number;
};

const CONTEXT_RE = /^本次上下文\s*([\d,]+)\s*字/;

/**
 * 上下文那句的折叠写法。
 *
 * 被裁 / 接近上限时**原样保留**（作者必须知道上限与"没装下"），否则只留用量。
 */
export function compactContextUsage(usage: {
  text: string;
  truncated?: boolean;
  nearLimit?: boolean;
}): string {
  const text = (usage.text || "").trim();
  if (!text) return "";
  if (usage.truncated) return `${text} · 有资料没装下`;
  if (usage.nearLimit) return `${text} · 接近上限`;
  const m = text.match(CONTEXT_RE);
  return m ? `语境 ${m[1]} 字` : text;
}

/** 折叠态那一行。空字段自动跳过，全空时返回空串（调用方据此不渲染）。 */
export function compactRunInfo(bits: RunInfoBits): string {
  const parts: string[] = [];
  if (bits.taskName) parts.push(bits.taskName);
  if (bits.resultBit) parts.push(bits.resultBit);
  if (bits.craftShort) parts.push(bits.craftShort);
  if (bits.reviewShort) parts.push(bits.reviewShort);
  if (bits.gateShort) parts.push(bits.gateShort);
  if (bits.prefetchShort) parts.push(bits.prefetchShort);
  if (bits.lensShort) parts.push(bits.lensShort);
  if (bits.refCount && bits.refCount > 0) parts.push(`参考 ${bits.refCount} 项`);
  const ctx = compactContextUsage({
    text: bits.contextText || "",
    truncated: bits.contextTruncated,
    nearLimit: bits.contextNearLimit,
  });
  if (ctx) parts.push(ctx);
  if (bits.evidenceCount && bits.evidenceCount > 0) parts.push(`依据 ${bits.evidenceCount} 项`);
  if (bits.excludedCount && bits.excludedCount > 0) parts.push(`不带 ${bits.excludedCount} 项`);
  return parts.filter(Boolean).join(" · ");
}

const OPEN_KEY = "vnss-agent-runinfo-open-v1";

/**
 * 折叠偏好：**默认收起**。
 *
 * 默认值是这次改动的重点——作者反馈"这些文字说明比较占对话的可见范围"，而它们是按需核对的
 * 凭据，不是每轮都要读的东西。落盘是为了尊重"我就想一直看着"的人（展开一次就一直展开）。
 */
export function readRunInfoOpen(): boolean {
  try {
    return localStorage.getItem(OPEN_KEY) === "1";
  } catch {
    // 隐私模式 / 无 localStorage（含单测的 node 环境）：按默认收起处理
    return false;
  }
}

export function writeRunInfoOpen(open: boolean): void {
  try {
    localStorage.setItem(OPEN_KEY, open ? "1" : "0");
  } catch {
    /* 存不下也无所谓：只影响下次进来是不是展开 */
  }
}
