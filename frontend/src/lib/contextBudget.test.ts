/**
 * 「这次没装下什么」的显示口径。
 *
 * 三条要钉住的：
 * 1. **两类原因不混**：篇幅没装下（要处理）≠ 按任务省去（设计如此）；
 * 2. **每行都能照着做**：动作来自后端的 `retrieve`，前端不自己编工具名；
 * 3. **没有就不显示**：没被裁过时 `hasMissing` 为 false，界面那一块整块不出现。
 */
import { describe, expect, it } from "vitest";

import type { AgentBudgetReport } from "../types/vn";
import { budgetNotice, includedSummary } from "./contextBudget";

function report(over: Partial<AgentBudgetReport> = {}): AgentBudgetReport {
  return {
    usedChars: 12000,
    budgetChars: 48000,
    usageRatio: 0.25,
    droppedSections: [],
    trimmedParts: [],
    excludedByTask: [],
    includedSections: [],
    truncated: false,
    ...over,
  };
}

describe("budgetNotice", () => {
  it("没有报告时返回空（界面不显示这一段）", () => {
    expect(budgetNotice(undefined).hasMissing).toBe(false);
    expect(budgetNotice(null).byDesign).toEqual([]);
  });

  it("没被裁过时 hasMissing 为 false（不当成「0 项」显示）", () => {
    const out = budgetNotice(report());
    expect(out.hasMissing).toBe(false);
    expect(out.missing).toEqual([]);
  });

  it("正文被截断时给出字数与取回动作", () => {
    const out = budgetNotice(
      report({
        truncated: true,
        trimmedParts: [
          {
            kind: "focus",
            label: "当前章正文（第一章）",
            detail: "只带了末尾 24,000 / 60,000 字",
            retrieve: "让它用 get_chapter 读「第一章」的完整正文",
            keptChars: 24000,
            totalChars: 60000,
          },
        ],
      })
    );
    expect(out.hasMissing).toBe(true);
    expect(out.missing[0].label).toBe("当前章正文（第一章）");
    expect(out.missing[0].detail).toContain("24,000");
    expect(out.missing[0].action).toContain("get_chapter");
  });

  it("整块让位的资料给出「因为篇幅」的说明 + 取回方式", () => {
    const out = budgetNotice(
      report({
        truncated: true,
        droppedSections: [
          { key: "referenceDocs", label: "上传的参考资料", retrieve: "重新上传这份资料" },
        ],
      })
    );
    expect(out.missing[0].detail).toContain("篇幅");
    expect(out.missing[0].action).toContain("重新上传");
  });

  it("按任务省去的单独一列，且不混进「没装下」", () => {
    const out = budgetNotice(
      report({
        excludedByTask: [
          { key: "sprites", label: "立绘" },
          { key: "variables", label: "变量 / 状态机" },
        ],
      })
    );
    expect(out.hasMissing).toBe(false);
    expect(out.byDesign.map((r) => r.label)).toEqual(["立绘", "变量 / 状态机"]);
    // 文案要说清"这不是没装下，是这类资料对写正文没用"
    expect(out.byDesign[0].detail).toContain("信息量");
    expect(out.byDesign[0].action).toBe("");
  });

  it("缺 detail 时用 kept/total 兜底；缺 label 的行直接丢掉", () => {
    const out = budgetNotice(
      report({
        truncated: true,
        trimmedParts: [
          { kind: "middle", label: "上下文中段", detail: "", retrieve: "缩小范围", keptChars: 100, totalChars: 900 },
          { kind: "x", label: "", detail: "无标题行", retrieve: "" },
        ],
      })
    );
    expect(out.missing).toHaveLength(1);
    expect(out.missing[0].detail).toContain("100");
    expect(out.missing[0].detail).toContain("900");
  });
});

describe("includedSummary", () => {
  it("用后端给的人话名拼一行（不再靠正则过滤中文串）", () => {
    const summary = includedSummary(
      report({
        includedSections: [
          { key: "characters", label: "角色卡" },
          { key: "lore", label: "设定条目" },
          { key: "focus", label: "当前章" },
        ],
      })
    );
    expect(summary).toBe("参考 角色卡·设定条目·当前章");
  });

  it("太多项时截断并写明总数", () => {
    const many = Array.from({ length: 9 }, (_, i) => ({ key: `k${i}`, label: `块${i}` }));
    const summary = includedSummary(report({ includedSections: many }), 3);
    expect(summary).toBe("参考 块0·块1·块2 等 9 项");
  });

  it("没有资料时返回空串", () => {
    expect(includedSummary(report())).toBe("");
    expect(includedSummary(undefined)).toBe("");
  });
});
