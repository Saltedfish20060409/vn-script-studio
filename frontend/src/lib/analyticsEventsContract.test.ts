/**
 * FE/BE analytics 事件名契约：FE EVENTS 必须 ⊆ 后端白名单字符串。
 */
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { describe, expect, it } from "vitest";
import { EVENTS } from "./track";

function backendEventNameStrings(py: string): Set<string> {
  // 常量赋值：PLAYTEST_OPENED = "playtest_opened"
  const names = new Set<string>();
  for (const m of py.matchAll(/^\s*[A-Z0-9_]+\s*=\s*"([a-z0-9_]+)"/gm)) {
    names.add(m[1]);
  }
  return names;
}

describe("analytics event whitelist sync", () => {
  it("EVENTS 每个值都在后端事件常量里", () => {
    const py = readFileSync(
      resolve(__dirname, "../../../backend/app/core/analytics.py"),
      "utf8"
    );
    const names = backendEventNameStrings(py);
    expect(names.size).toBeGreaterThan(5);
    for (const v of Object.values(EVENTS)) {
      expect(names.has(v), `missing backend event: ${v}`).toBe(true);
    }
  });
});
