/**
 * 「这次它读了多少」——把 `contextMeta` 说成人话（纯函数，便于单测）。
 *
 * 为什么值得单独做：作者最容易被 AI 的"失忆"坑到的地方不是模型笨，而是**上下文被裁过
 * 却没人告诉他**——AI 没读到整章正文时会写出前后矛盾的东西，作者只会觉得"它怎么忘了"。
 * 后端已经把三个关键量放在 `contextMeta` 里（`charsUsed` / `budgetChars` / `truncated`），
 * 这里负责把它们拼成一句可核对的话，并诚实区分两件事：
 *
 * - **用满了**（接近预算上限）：说明资料装不下，作者该考虑精简设定或分章；
 * - **被裁过**（`truncated`）：说明有内容被截断/整块让位，界面上要提示"可以让它用工具取"。
 *
 * 纪律：缺的字段就不说，**不把未知说成 0**（旧后端没有 budgetChars/truncated 时，
 * 只显示已用量，不显示"上限 0"）。
 */
import type { AgentContextMeta } from "../types/vn";

export type ContextUsage = {
  /** 例如 "本次上下文 12,480 字（上限 48,000）"（无数据时为空串） */
  text: string;
  /** 被裁过：需要在界面上单独提示 */
  truncated: boolean;
  /** 用量是否接近上限（≥80%）——用于给出"装不下了"的提示 */
  nearLimit: boolean;
  /** 一句话提示（可能要动作：精简资料 / 让它用工具取） */
  hint: string;
};

function fmt(n: number): string {
  return Math.round(n).toLocaleString("en-US");
}

/** 从 contextMeta 里读用量；缺失字段按"未知"处理。 */
export function contextUsage(meta?: AgentContextMeta | null): ContextUsage {
  const used = typeof meta?.charsUsed === "number" && meta.charsUsed >= 0 ? meta.charsUsed : null;
  const budget =
    typeof meta?.budgetChars === "number" && meta.budgetChars > 0 ? meta.budgetChars : null;
  const truncated = meta?.truncated === true;

  if (used === null) {
    return { text: "", truncated, nearLimit: false, hint: "" };
  }

  const text = budget
    ? `本次上下文 ${fmt(used)} 字（上限 ${fmt(budget)}）`
    : `本次上下文 ${fmt(used)} 字`;
  const ratio = budget ? used / budget : 0;
  const nearLimit = budget !== null && ratio >= 0.8;

  let hint = "";
  if (truncated) {
    hint =
      "这次有资料没装下（正文被截过或整块让位）。需要那段前情时，直接让它「用 get_chapter 取第 N 章」，" +
      "它就能读到；也可以在「资料」里摘掉用不上的块，把位置让给正文。";
  } else if (nearLimit) {
    hint = "上下文已经接近上限：再加设定/参考文档就要开始让位了。";
  }
  return { text, truncated, nearLimit, hint };
}
