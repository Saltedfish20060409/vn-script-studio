/**
 * 多变体展示：**没测量的信号不显示成 0**。
 *
 * 这是界面上最容易骗人的一处：后端拿不到 logprobs 时置信度是 `null`，
 * 如果前端用 `Number(x ?? 0).toFixed(2)` 渲染，作者会看到"置信度 0.00"，
 * 于是以为"模型完全没把握"——而事实是"这次没测"。测试把这条钉死。
 */
import { describe, expect, it } from "vitest";

import type { MarkVariantRow } from "../api/projects";
import {
  hasProblems,
  selectionSummary,
  variantBadge,
  variantTitle,
} from "./markVariants";

function row(over: Partial<MarkVariantRow> = {}): MarkVariantRow {
  return { variantIndex: 0, rank: 1, ...over };
}

describe("variantBadge", () => {
  it("第一顺位标推荐，其余标顺位", () => {
    expect(variantBadge(row({ variantIndex: 1, rank: 1, recommended: true }), 1)).toBe(
      "推荐 · 第 2 版"
    );
    expect(variantBadge(row({ variantIndex: 0, rank: 2, recommended: false }), 1)).toBe("第 1 版");
  });

  it("后端没给 ranking 时退回按位置命名（旧后端/单版路径）", () => {
    expect(variantBadge(undefined, 2)).toBe("第 2 版");
  });
});

describe("variantTitle", () => {
  it("列出已有的证据", () => {
    const title = variantTitle(
      row({ score: 0.8123, consensus: 0.5, temperature: 0.55, chars: 120 })
    );
    expect(title).toContain("综合 0.81");
    expect(title).toContain("一致度 0.50");
    expect(title).toContain("温度 0.55");
    expect(title).toContain("120 字");
  });

  it("置信度缺失时一个字都不提（不是 0.00）", () => {
    const title = variantTitle(row({ score: 0.9, certainty: null }));
    expect(title).not.toContain("置信度");
    expect(title).not.toContain("0.00");
  });

  it("置信度存在时列出，并标注样本过短", () => {
    const title = variantTitle(row({ certainty: { composite: 0.42, thin: true } }));
    expect(title).toContain("置信度 0.42");
    expect(title).toContain("仅供参考");
  });

  it("有问题时把问题写进提示", () => {
    const title = variantTitle(row({ problems: ["丢了原文里的专名：林夏"] }));
    expect(title).toContain("丢了原文里的专名");
  });
});

describe("selectionSummary", () => {
  it("优先用后端的取舍说明", () => {
    expect(selectionSummary("本次取舍依据：确定性检查。", undefined)).toBe(
      "本次取舍依据：确定性检查。"
    );
  });

  it("多版但没有说明时如实说后端没带这个字段", () => {
    expect(selectionSummary(undefined, [row(), row({ variantIndex: 1, rank: 2 })])).toContain(
      "没有给出取舍说明"
    );
  });

  it("单版时不显示任何取舍文案", () => {
    expect(selectionSummary(undefined, [row()])).toBe("");
    expect(selectionSummary(undefined, undefined)).toBe("");
  });
});

describe("hasProblems", () => {
  it("有/无问题的判定", () => {
    expect(hasProblems(row({ problems: ["长度失控"] }))).toBe(true);
    expect(hasProblems(row({ problems: [] }))).toBe(false);
    expect(hasProblems(undefined)).toBe(false);
  });
});
