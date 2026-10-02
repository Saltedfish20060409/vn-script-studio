/**
 * P4.5：生产代码禁止调用 chapterProse(（须用 storedProse / scriptPreview）。
 * 白名单：定义文件 + 测试。
 */
import { describe, expect, it } from "vitest";
import { readdirSync, readFileSync, statSync } from "node:fs";
import { dirname, join, relative, resolve } from "node:path";
import { fileURLToPath } from "node:url";

const HERE = dirname(fileURLToPath(import.meta.url));
const SRC = resolve(HERE, "..");

const ALLOW_FILES = new Set([
  "lib/scriptProse.ts",
  "lib/scriptProse.test.ts",
  "lib/chapterProseWiring.test.ts",
]);

function walk(dir: string, out: string[] = []): string[] {
  for (const name of readdirSync(dir)) {
    if (name === "node_modules" || name.startsWith(".")) continue;
    const full = join(dir, name);
    const st = statSync(full);
    if (st.isDirectory()) walk(full, out);
    else if (/\.(ts|tsx)$/.test(name)) out.push(full);
  }
  return out;
}

describe("chapterProse 生产调用白名单", () => {
  it("frontend/src 内 chapterProse( 只能出现在白名单文件", () => {
    const offenders: string[] = [];
    for (const file of walk(SRC)) {
      const rel = relative(SRC, file).replace(/\\/g, "/");
      if (ALLOW_FILES.has(rel)) continue;
      if (rel.endsWith(".test.ts") || rel.endsWith(".test.tsx")) continue;
      const src = readFileSync(file, "utf-8");
      if (/chapterProse\s*\(/.test(src)) offenders.push(rel);
    }
    expect(offenders, `禁止在生产代码调用 chapterProse(：${offenders.join(", ")}`).toEqual(
      []
    );
  });
});
