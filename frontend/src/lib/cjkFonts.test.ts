import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

/**
 * 中文字体（Noto Sans SC）护栏。
 *
 * 背景：中文原本走 Google Fonts（国内常被墙）。现在自托管，但**不能整份打包**——
 * 整包 65k 字形、1.09MB/字重，必须按 unicode-range 分片，浏览器才会"只下载页面上
 * 真正出现的字所在的片"。生成脚本是 scripts/gen-cjk-font-css.mjs，
 * 这里守住三件容易悄悄坏掉的事：
 *   1. 分片文件真的存在（包升级后文件名变了，构建会失败——但要在测试里先报出来）；
 *   2. 每条规则都得有 unicode-range（丢了就退化成"一次拉全部"）；
 *   3. 不许混进 .woff（老格式，构建时白占一倍体积）。
 */

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(HERE, "..", "..");
const CSS = path.join(ROOT, "src", "styles", "fonts-noto-sans-sc.css");
const PKG = path.join(ROOT, "node_modules", "@fontsource", "noto-sans-sc");
const WEIGHTS = [400, 600, 700];

const css = fs.readFileSync(CSS, "utf8");
const rules = (css.match(/@font-face\s*\{[^}]*\}/g) ?? []).map((r) => {
  const file = r.match(/url\("([^"]+)"\)/)?.[1] ?? "";
  const weight = Number(r.match(/font-weight:\s*(\d+)/)?.[1] ?? 0);
  const range = r.match(/unicode-range:\s*([^;}]+)/)?.[1] ?? "";
  return { file, weight, range };
});

describe("中文字体分片", () => {
  it("覆盖应用真正用到的字重（正文 400 / 标题 600·700）", () => {
    const got = [...new Set(rules.map((r) => r.weight))].sort();
    expect(got).toEqual(WEIGHTS);
  });

  it("每条规则都有 unicode-range —— 否则就退化成整份下载", () => {
    const missing = rules.filter((r) => !r.range.startsWith("U+"));
    expect(missing, `缺 unicode-range 的规则：${missing.length} 条`).toEqual([]);
  });

  it("只引用 woff2（.woff 是老格式，会把体积翻倍）", () => {
    expect(css.includes(".woff)")).toBe(false);
    expect(rules.every((r) => r.file.endsWith(".woff2"))).toBe(true);
  });

  it("被引用的分片文件真的存在于依赖包里", () => {
    const missing = rules
      .map((r) => r.file.replace("@fontsource/noto-sans-sc/files/", ""))
      .filter((f) => !fs.existsSync(path.join(PKG, "files", f)));
    expect(missing, `包升级后文件名可能变了：${missing.slice(0, 3).join(", ")}`).toEqual([]);
  });

  it("与依赖包当前的分片一一对应（包升级后要重跑生成脚本）", () => {
    for (const w of WEIGHTS) {
      const pkgCss = fs.readFileSync(path.join(PKG, `${w}.css`), "utf8");
      const pkgFiles = [...pkgCss.matchAll(/url\(\.\/files\/([^)]+\.woff2)\)/g)]
        .map((m) => m[1])
        .sort();
      const ours = rules
        .filter((r) => r.weight === w)
        .map((r) => r.file.replace("@fontsource/noto-sans-sc/files/", ""))
        .sort();
      expect(ours, `${w} 字重与包不一致，请运行 node scripts/gen-cjk-font-css.mjs`).toEqual(
        pkgFiles
      );
    }
  });

  it("字体族名与 CSS 变量里的引用一致（写错就静默回退系统字体）", () => {
    const globals = fs.readFileSync(path.join(ROOT, "src", "styles", "globals.css"), "utf8");
    expect(globals).toContain('"Noto Sans SC"');
    expect(css).toContain("font-family:'Noto Sans SC'");
  });
});
