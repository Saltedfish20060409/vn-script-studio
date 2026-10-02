import { describe, expect, it } from "vitest";
import {
  critiqueIssuesToMarkHints,
  parseCritiquePayload,
} from "./critiquePayload";

describe("parseCritiquePayload", () => {
  it("解析 structured JSON", () => {
    const raw = JSON.stringify({
      summary: "偏说明书",
      issues: [
        {
          code: "expo",
          severity: "warn",
          quote: "正如你所知",
          reason: "说明书腔",
          suggestion: "改动作",
        },
      ],
    });
    const out = parseCritiquePayload(raw);
    expect(out?.summary).toBe("偏说明书");
    expect(out?.issues).toHaveLength(1);
    expect(critiqueIssuesToMarkHints(out!.issues)[0].quote).toBe("正如你所知");
  });

  it("非 JSON → null", () => {
    expect(parseCritiquePayload("随便聊聊")).toBeNull();
  });
});
