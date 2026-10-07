import { describe, expect, it } from "vitest";
import { readFileSync } from "node:fs";
import { resolve } from "node:path";
import { textHasEngineSyntax, PROSE_ENGINE_REJECT_MSG } from "./proseEngineSyntax";

const ROOT = resolve(__dirname, "../../..");
const FIXTURE = resolve(ROOT, "shared/test-fixtures/engine_syntax_cases.json");

type Fixture = {
  reject: Array<{ id: string; text: string; hit: string }>;
  allow: Array<{ id: string; text?: string; source?: string }>;
  known_false_positives: Array<{ id: string; text: string; rule: string }>;
  messages: { append_replace: string };
};

function loadFixture(): Fixture {
  return JSON.parse(readFileSync(FIXTURE, "utf-8")) as Fixture;
}

function resolveSource(source: string): string | null {
  const [pathPart, pointer] = source.split("#");
  const abs = resolve(ROOT, pathPart);
  try {
    const data = JSON.parse(readFileSync(abs, "utf-8")) as Record<string, unknown>;
    let cur: unknown = data;
    for (const key of pointer.split(".")) {
      cur = (cur as Record<string, unknown>)[key];
    }
    if (typeof cur !== "string") throw new Error(`bad source ${source}`);
    return cur;
  } catch (err) {
    const code = (err as NodeJS.ErrnoException)?.code;
    if (code === "ENOENT") return null; // 盲测跑次未入库时跳过，避免 CI 假红
    throw err;
  }
}

describe("proseEngineSyntax shared fixture", () => {
  it("reject cases hit expected rule", () => {
    for (const row of loadFixture().reject) {
      expect(textHasEngineSyntax(row.text), row.id).toBe(row.hit);
    }
  });

  it("allow cases including W08/W09 sources are zero-hit", () => {
    for (const row of loadFixture().allow) {
      const text = row.text ?? (row.source ? resolveSource(row.source) : "");
      if (text === null) continue;
      expect(textHasEngineSyntax(text), row.id).toBeNull();
    }
  });

  it("known_false_positives still hit (documented)", () => {
    for (const row of loadFixture().known_false_positives) {
      expect(textHasEngineSyntax(row.text), row.id).toBe(row.rule);
    }
  });

  it("reject message frozen", () => {
    expect(loadFixture().messages.append_replace).toBe(PROSE_ENGINE_REJECT_MSG);
  });
});
