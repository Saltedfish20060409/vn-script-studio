import { describe, expect, it } from "vitest";
import {
  auditConstraints,
  classifyConstraint,
  detectConstraintConflicts,
  splitConstraintLines,
} from "./constraintAudit";

describe("约束体检（前端即时版，规则与后端一致）", () => {
  it("切行、去掉列表符号与序号", () => {
    expect(splitConstraintLines("1. 必须用第一人称\n- 尽量短句\n\n· 世界观是多雨的城市")).toEqual([
      "必须用第一人称",
      "尽量短句",
      "世界观是多雨的城市",
    ]);
  });

  it("分层：必须/不要/禁止 = 硬，尽量/建议 = 软，其余是背景", () => {
    expect(classifyConstraint("必须用第一人称")).toBe("hard");
    expect(classifyConstraint("禁止解释超自然机制")).toBe("hard");
    expect(classifyConstraint("尽量短句")).toBe("soft");
    expect(classifyConstraint("主角叫林越")).toBe("info");
  });

  it("同一维度上的互斥说法会被指出来", () => {
    const conflicts = detectConstraintConflicts(["不要解释超自然", "要把设定讲清楚"]);
    expect(conflicts).toHaveLength(1);
    expect(conflicts[0].topic).toBe("是否解释超自然");
    expect(conflicts[0].hint).toBeTruthy();
  });

  it("人称冲突：硬规则与世界观句子之间也能抓到", () => {
    const audit = auditConstraints({
      bibleText: "必须用第一人称\n全知视角交代所有人的想法\n多雨的城市",
      hasStyleSamples: false,
    });
    const topics = audit.conflicts.map((c) => c.topic);
    expect(topics.includes("叙述人称") || topics.includes("视角信息量")).toBe(true);
  });

  it("一致的约束不报冲突", () => {
    expect(detectConstraintConflicts(["尽量短句", "克制，少形容词"])).toEqual([]);
  });

  it("有硬规则但没有样例 → 提醒补样例", () => {
    const audit = auditConstraints({ bibleText: "必须用第一人称", hasStyleSamples: false });
    expect(audit.needsSamples).toBe(true);
    expect(audit.notes.join()).toContain("样例");
    const withSamples = auditConstraints({ bibleText: "必须用第一人称", hasStyleSamples: true });
    expect(withSamples.needsSamples).toBe(false);
  });

  it("硬规则过多会被提醒", () => {
    const audit = auditConstraints({
      bibleText: Array.from({ length: 12 }, (_, i) => `必须遵守第${i}条`).join("\n"),
      hasStyleSamples: true,
    });
    expect(audit.notes.join()).toContain("偏多");
  });

  it("设定条目贡献「说明」那部分", () => {
    const audit = auditConstraints({
      entryTexts: ["雨工：必须保持称呼为「雨工」。", "蒸汽：世界观里的动力来源"],
      hasStyleSamples: true,
    });
    expect(audit.hard.some((r) => r.includes("必须保持称呼"))).toBe(true);
    expect(audit.info.some((r) => r.includes("动力来源"))).toBe(true);
  });
});
