import { describe, expect, it } from "vitest";
import { jsonModeWarning, supportsJsonMode, type PresetLike } from "./modelCapabilities";

const PRESETS: PresetLike[] = [
  { id: "deepseek-flash", model: "deepseek-flash", json_mode: true },
  { id: "deepseek-flash-think", model: "deepseek-flash-think", json_mode: false },
  { id: "claude-opus-5", model: "claude-opus-5", json_mode: false },
  { id: "claude-sonnet", model: "claude-sonnet-4-8", json_mode: false },
  { id: "local-ollama", model: "qwen3:8b", json_mode: false },
];

describe("supportsJsonMode", () => {
  it("按模型名精确判断", () => {
    expect(supportsJsonMode(PRESETS, "deepseek-flash")).toBe(true);
    expect(supportsJsonMode(PRESETS, "claude-opus-5")).toBe(false);
    expect(supportsJsonMode(PRESETS, "qwen3:8b")).toBe(false);
  });

  it("大小写与空格不影响判断", () => {
    expect(supportsJsonMode(PRESETS, "  Claude-Opus-5 ")).toBe(false);
  });

  it("手填简写时按前缀兜底（和 backend 的宽松度一致）", () => {
    expect(supportsJsonMode(PRESETS, "claude")).toBe(false);
    expect(supportsJsonMode(PRESETS, "claude-sonnet-4-8")).toBe(false);
  });

  it("没收录的模型一律当作支持（不能擅自把用户的能力改小）", () => {
    expect(supportsJsonMode(PRESETS, "some-unknown-model")).toBe(true);
    expect(supportsJsonMode(PRESETS, "")).toBe(true);
    expect(supportsJsonMode([], "claude-opus-5")).toBe(true);
  });

  it("预设缺 json_mode 字段时按支持处理", () => {
    expect(supportsJsonMode([{ model: "x-1" }], "x-1")).toBe(true);
  });
});

describe("jsonModeWarning", () => {
  it("支持的档位不吭声", () => {
    expect(jsonModeWarning(PRESETS, "deepseek-flash")).toBe("");
  });

  it("不支持的档位给出可读提示，且说清后果", () => {
    const w = jsonModeWarning(PRESETS, "claude-opus-5");
    expect(w).toContain("不支持结构化输出");
    expect(w).toContain("建议换一档");
  });
});
