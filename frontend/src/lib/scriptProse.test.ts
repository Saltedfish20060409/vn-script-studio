import { describe, expect, it } from "vitest";
import { blocksToProse, proseFingerprint, rpyIsStale } from "./scriptProse";
import type { Character, ScriptBlock } from "../types/vn";

const chars: Character[] = [
  { id: "lx", defineName: "lx", displayName: "林夏" },
];

const blocks: ScriptBlock[] = [
  { type: "label", id: "start", name: "start" },
  { type: "scene", image: "bg station" },
  { type: "narration", text: "雨声在空荡的站厅里回荡。" },
  { type: "dialogue", characterId: "lx", text: "末班车已经开走了……" },
];

describe("scriptProse", () => {
  it("renders a readable manuscript and skips labels", () => {
    const prose = blocksToProse(blocks, chars);
    expect(prose).toContain("[场景：bg station]");
    expect(prose).toContain("雨声在空荡的站厅里回荡。");
    expect(prose).toContain("林夏：末班车已经开走了……");
    expect(prose).not.toContain("label start");
  });

  it("marks rpy stale only after prose drifts", () => {
    const hash = proseFingerprint("hello");
    expect(rpyIsStale({ prose: "hello", rpyFromProseHash: hash })).toBe(false);
    expect(rpyIsStale({ prose: "hello!", rpyFromProseHash: hash })).toBe(true);
    expect(rpyIsStale({ prose: "hello" })).toBe(false);
  });
});
