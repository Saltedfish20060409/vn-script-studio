import { afterEach, beforeEach, describe, expect, it } from "vitest";
import { DEBUG_LEDGER_LABEL, isDebugLedgerEnabled } from "./debugFlags";

function installMemoryStorage() {
  const store = new Map<string, string>();
  const mem = {
    getItem: (k: string) => (store.has(k) ? store.get(k)! : null),
    setItem: (k: string, v: string) => {
      store.set(k, String(v));
    },
    removeItem: (k: string) => {
      store.delete(k);
    },
    clear: () => store.clear(),
  };
  Object.defineProperty(globalThis, "localStorage", {
    value: mem,
    configurable: true,
  });
  return mem;
}

describe("debugFlags", () => {
  beforeEach(() => {
    installMemoryStorage();
  });

  afterEach(() => {
    try {
      localStorage.removeItem("vn.debugLedger");
    } catch {
      /* ignore */
    }
  });

  it("ledger debug is off by default", () => {
    expect(isDebugLedgerEnabled()).toBe(false);
  });

  it("enables when vn.debugLedger=1", () => {
    localStorage.setItem("vn.debugLedger", "1");
    expect(isDebugLedgerEnabled()).toBe(true);
  });

  it("exposes a debug label", () => {
    expect(DEBUG_LEDGER_LABEL).toContain("调试");
  });
});
