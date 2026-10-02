import { describe, expect, it, beforeEach } from "vitest";
import {
  classifyWriteApplyBlocked,
  isAgentTurnDefault,
  isClassicReviseUiEnabled,
  isLegacyAgentToolsEnabled,
  isLegacyAgentWriteEnabled,
  resolveWritingSurface,
  setAgentTurnDefault,
  setClassicReviseUiEnabled,
  setLegacyAgentToolsEnabled,
  setLegacyAgentWriteEnabled,
  shouldUseAgentTurnForWrite,
  writeApplyBlockedMessage,
} from "./agentTurnFlags";

function memoryStorage(): Storage {
  const map = new Map<string, string>();
  return {
    get length() {
      return map.size;
    },
    clear() {
      map.clear();
    },
    getItem(key: string) {
      return map.has(key) ? map.get(key)! : null;
    },
    key(index: number) {
      return [...map.keys()][index] ?? null;
    },
    removeItem(key: string) {
      map.delete(key);
    },
    setItem(key: string, value: string) {
      map.set(key, String(value));
    },
  };
}

describe("agentTurnFlags", () => {
  let storage: Storage;

  beforeEach(() => {
    storage = memoryStorage();
  });

  it("默认：turn 开、工具环关、旧 write 关、经典对照关", () => {
    expect(isAgentTurnDefault(storage)).toBe(true);
    expect(isLegacyAgentToolsEnabled(storage)).toBe(false);
    expect(isLegacyAgentWriteEnabled(storage)).toBe(false);
    expect(isClassicReviseUiEnabled(storage)).toBe(false);
    expect(shouldUseAgentTurnForWrite(storage)).toBe(true);
  });

  it("B6：可打开经典改稿对照", () => {
    setClassicReviseUiEnabled(true, storage);
    expect(isClassicReviseUiEnabled(storage)).toBe(true);
  });

  it("B1：开旧 write 后写作不走 turn", () => {
    setLegacyAgentWriteEnabled(true, storage);
    expect(shouldUseAgentTurnForWrite(storage)).toBe(false);
    setAgentTurnDefault(false, storage);
    expect(shouldUseAgentTurnForWrite(storage)).toBe(false);
  });

  it("可开关工具环入口", () => {
    setLegacyAgentToolsEnabled(true, storage);
    expect(isLegacyAgentToolsEnabled(storage)).toBe(true);
  });

  it("vnss-write-mode → writing_surface：仅 prose|rpy", () => {
    expect(resolveWritingSurface(storage)).toBe("prose");
    storage.setItem("vnss-write-mode", "rpy");
    expect(resolveWritingSurface(storage)).toBe("script");
    storage.setItem("vnss-write-mode", "mixed");
    expect(resolveWritingSurface(storage)).toBe("prose");
  });

  it("classifyWriteApplyBlocked：无草稿 / busy / 可写", () => {
    expect(classifyWriteApplyBlocked(null, false)).toBe("no_draft");
    expect(classifyWriteApplyBlocked({ chapterId: "ch1" }, true)).toBe("busy");
    expect(classifyWriteApplyBlocked({ chapterId: "ch1" }, false)).toBe(null);
    expect(writeApplyBlockedMessage("busy")).toMatch(/处理中/);
    expect(writeApplyBlockedMessage("no_draft")).toMatch(/丢弃/);
  });
});
