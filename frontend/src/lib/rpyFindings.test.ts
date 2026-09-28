import { describe, expect, it } from "vitest";
import type { RpyFinding } from "../api/projects";
import { rpyFindingLines, summarizeRpyFindings } from "./rpyFindings";

function finding(severity: RpyFinding["severity"], message: string): RpyFinding {
  return { code: "x", severity, message, line: 1 };
}

describe("summarizeRpyFindings", () => {
  it("没有结论时说通过（假阳性方向：干净工程不该被说成有问题）", () => {
    const s = summarizeRpyFindings([]);
    expect(s.ok).toBe(true);
    expect(s.errors).toBe(0);
    expect(s.headline).toContain("没有发现问题");
    expect(s.lines).toEqual([]);
  });

  it("null（体检请求失败）与空数组同口径：不吓唬作者", () => {
    expect(summarizeRpyFindings(null).ok).toBe(true);
    expect(summarizeRpyFindings(undefined).lines).toEqual([]);
  });

  it("有 error 时不 ok，并在标题里报数", () => {
    const s = summarizeRpyFindings([
      finding("error", "跳转目标不存在"),
      finding("warn", "没有 label start"),
    ]);
    expect(s.ok).toBe(false);
    expect(s.errors).toBe(1);
    expect(s.warnings).toBe(1);
    expect(s.headline).toContain("1 项");
    expect(s.headline).toContain("卡住");
  });

  it("只有 warn 时仍然 ok（提示不等于故障）", () => {
    const s = summarizeRpyFindings([finding("warn", "说话人没有 define")]);
    expect(s.ok).toBe(true);
    expect(s.headline).toContain("没有会崩的问题");
  });

  it("列表先严重后轻微，并带前缀图标", () => {
    const lines = rpyFindingLines([
      finding("info", "疑似 %s"),
      finding("warn", "提示"),
      finding("error", "会崩"),
    ]);
    expect(lines.map((l) => l.level)).toEqual(["error", "warn", "info"]);
    expect(lines[0].text.startsWith("⛔ ")).toBe(true);
    expect(lines[1].text.startsWith("⚠️ ")).toBe(true);
    expect(lines[2].text.startsWith("· ")).toBe(true);
  });
});
