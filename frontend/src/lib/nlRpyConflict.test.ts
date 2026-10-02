import { describe, expect, it } from "vitest";
import { detectNlRpyConflict, nlRpyConflictLabel } from "./nlRpyConflict";
import { proseFingerprint } from "./scriptProse";

describe("detectNlRpyConflict", () => {
  it("双变 → both", () => {
    const prose = "雨下了。";
    const ch = {
      id: "c",
      title: "t",
      prose: "雨下了，很大。",
      blocks: [{ type: "narration" as const, text: "别的" }],
      nlRpyMap: {
        version: 1,
        proseFingerprint: proseFingerprint(prose),
        blocksFingerprint: proseFingerprint(
          JSON.stringify([{ type: "narration", text: "旧" }])
        ),
        segments: [],
      },
    };
    expect(detectNlRpyConflict(ch)).toBe("both");
    expect(nlRpyConflictLabel("both")).toMatch(/选择/);
  });
});
