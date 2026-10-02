import { describe, expect, it } from "vitest";
import {
  applyWriteDraftScope,
  inferDefaultWriteScope,
  inferWriteOpFromText,
  mapIntentToTurnRoute,
  selectionReplaceEnabled,
} from "./agentTurnRoute";

describe("mapIntentToTurnRoute", () => {
  it("write_to_script → continue；有选区 → rewrite", () => {
    expect(mapIntentToTurnRoute({ kind: "write_to_script" })).toEqual({
      capability: "write",
      writeOp: "continue",
    });
    expect(
      mapIntentToTurnRoute({ kind: "write_to_script" }, { selection: "选区" })
    ).toEqual({ capability: "write", writeOp: "rewrite" });
  });

  it("write_to_script + 话术 → P5 writeOp", () => {
    expect(
      mapIntentToTurnRoute(
        { kind: "write_to_script" },
        { instruction: "把这段扩写细一点" }
      ).writeOp
    ).toBe("expand");
    expect(
      mapIntentToTurnRoute(
        { kind: "write_to_script" },
        { instruction: "缩写这一段，只留钩子" }
      ).writeOp
    ).toBe("condense");
    expect(
      mapIntentToTurnRoute(
        { kind: "write_to_script" },
        { instruction: "按硬汉风格做风格迁移" }
      ).writeOp
    ).toBe("style_transfer");
  });

  it("targeted_revise → write/rewrite", () => {
    expect(mapIntentToTurnRoute({ kind: "targeted_revise" })).toEqual({
      capability: "write",
      writeOp: "rewrite",
    });
  });

  it("critique / ingest / chat", () => {
    expect(mapIntentToTurnRoute({ kind: "critique_only" }).capability).toBe(
      "critique"
    );
    expect(mapIntentToTurnRoute({ kind: "settings_ingest" }).capability).toBe(
      "ingest"
    );
    expect(mapIntentToTurnRoute({ kind: "chat" }).capability).toBe("chat");
  });

  it("chapter_revise 旁路；chapter_polish 进 turn polish", () => {
    expect(mapIntentToTurnRoute({ kind: "chapter_revise" }).bypassTurn).toBe(
      true
    );
    expect(mapIntentToTurnRoute({ kind: "chapter_polish" })).toEqual({
      capability: "write",
      writeOp: "polish",
    });
  });
});

describe("inferWriteOpFromText", () => {
  it("识别四类 P5 话术", () => {
    expect(inferWriteOpFromText("再润一版")).toBe("polish");
    expect(inferWriteOpFromText("扩写这场雨戏")).toBe("expand");
    expect(inferWriteOpFromText("压缩一下")).toBe("condense");
    expect(inferWriteOpFromText("换成冷硬风格")).toBe("style_transfer");
    expect(inferWriteOpFromText("接着写")).toBe(null);
  });
});

describe("write draft scope", () => {
  it("有选区默认 selection_replace", () => {
    expect(
      inferDefaultWriteScope({
        originalText: "前文选区后文",
        revisedText: "新",
        selection: "选区",
      })
    ).toBe("selection_replace");
  });

  it("无选区默认追加", () => {
    expect(
      inferDefaultWriteScope({
        originalText: "旧章全文内容足够长",
        revisedText: "全新一段续写内容",
      })
    ).toBe("chapter_append");
  });

  it("selection_replace 无选区时禁用", () => {
    expect(selectionReplaceEnabled("正文", "")).toBe(false);
    expect(selectionReplaceEnabled("正文含选区", "选区")).toBe(true);
  });

  it("applyWriteDraftScope 三态", () => {
    expect(
      applyWriteDraftScope({
        scope: "chapter_append",
        originalText: "A",
        revisedText: "B",
      })
    ).toBe("A\n\nB");
    expect(
      applyWriteDraftScope({
        scope: "chapter_replace",
        originalText: "A",
        revisedText: "B",
      })
    ).toBe("B");
    expect(
      applyWriteDraftScope({
        scope: "selection_replace",
        originalText: "前中后",
        revisedText: "X",
        selection: "中",
      })
    ).toBe("前X后");
  });
});
