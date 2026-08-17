import { describe, expect, it } from "vitest";
import { joinTranscripts } from "./speechInput";

describe("speechInput", () => {
  it("joins final parts and interim tail", () => {
    expect(joinTranscripts(["你好", "世界"], "")).toBe("你好世界");
    expect(joinTranscripts(["你好"], "世界")).toBe("你好世界");
    expect(joinTranscripts([], "临时")).toBe("临时");
  });

  it("trims outer whitespace but keeps word gaps", () => {
    expect(joinTranscripts([" 你好 ", " 世界 "], " ！ ")).toBe("你好  世界！");
  });

  it("returns empty when nothing spoken", () => {
    expect(joinTranscripts([], "")).toBe("");
    expect(joinTranscripts(["  "], "  ")).toBe("");
  });
});
