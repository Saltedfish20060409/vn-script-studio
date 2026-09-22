/**
 * 生成 Noto Sans SC 的 @font-face CSS（只留 woff2）。
 *
 * 为什么需要这个脚本，而不是直接 import "@fontsource/noto-sans-sc/400.css"：
 *  @fontsource 那份 CSS 每条规则都同时给 woff2 与 woff 两个来源，
 *  构建会把**两种格式都打进 dist**。而 .woff 是 2016 年前的老格式，
 *  现代浏览器一律走 woff2 —— 等于白白多带一倍体积。
 *  这里把同一条规则的 woff2 挑出来重写，dist 只多一份 woff2。
 *
 * 为什么是「分片」而不是整份字体：
 *   Noto Sans SC 整包 65k 字形，按 @fontsource 的分片（每片带 unicode-range）
 *   才能让浏览器**只下载页面上真正出现的字**所对应的片 —— 就是"只加载用到的字段"。
 *   （整份 chinese-simplified 单文件是 1.09MB/字重，且必须整份下载。）
 *
 * 用法：node scripts/gen-cjk-font-css.mjs
 * 依赖包升级后请重跑；src/lib/cjkFonts.test.ts 会在 CSS 与包不一致时报错。
 */
import fs from "node:fs";
import path from "node:path";
import { fileURLToPath } from "node:url";

const HERE = path.dirname(fileURLToPath(import.meta.url));
const ROOT = path.join(HERE, "..");
const PKG = path.join(ROOT, "node_modules", "@fontsource", "noto-sans-sc");
const OUT = path.join(ROOT, "src", "styles", "fonts-noto-sans-sc.css");

/** 应用实际用到的字重：正文 400 / 标题 600·700（650→700、550→600 由浏览器就近取） */
export const WEIGHTS = [400, 600, 700];

const HEAD = `/*
 * Noto Sans SC —— 由 scripts/gen-cjk-font-css.mjs 生成，请勿手改。
 *
 * 中文原本走 Google Fonts（国内常被墙，且多一次外部依赖）。这里改为自托管，
 * 并按**分片 + unicode-range** 引用：浏览器只下载页面上真正出现的字所在的片，
 * 不是一次性拉整份字体（整份 1.09MB/字重）。
 * 只保留 woff2 来源（woff 是老格式，构建时白占体积）。
 * 字重 ${WEIGHTS.join(" / ")}：正文 400、标题 600/700。
 */
`;

/** 从 @fontsource 的分片 CSS 里抽出 (unicode-range, woff2 文件名) */
function parsePkgCss(weight) {
  const file = path.join(PKG, `${weight}.css`);
  const css = fs.readFileSync(file, "utf8");
  const blocks = css.match(/@font-face\s*\{[^}]*\}/g) ?? [];
  const out = [];
  for (const b of blocks) {
    const woff2 = b.match(/url\(\.\/files\/([^)]+\.woff2)\)/);
    const range = b.match(/unicode-range:\s*([^;]+);/);
    if (!woff2 || !range) continue;
    out.push({ file: woff2[1].trim(), range: range[1].trim() });
  }
  return out;
}

function build() {
  const parts = [HEAD];
  let total = 0;
  for (const w of WEIGHTS) {
    const rules = parsePkgCss(w);
    if (!rules.length) throw new Error(`包里没解析到 ${w} 字重的分片：${PKG}`);
    total += rules.length;
    parts.push(`/* ---- weight ${w}：${rules.length} 片 ---- */`);
    for (const r of rules) {
      parts.push(
        "@font-face{font-family:'Noto Sans SC';font-style:normal;" +
          `font-weight:${w};font-display:swap;` +
          `src:url("@fontsource/noto-sans-sc/files/${r.file}") format("woff2");` +
          `unicode-range:${r.range};}`
      );
    }
    parts.push("");
  }
  return { css: parts.join("\n"), blocks: total };
}

export function generate() {
  return build();
}

const isMain =
  process.argv[1] && fileURLToPath(import.meta.url) === path.resolve(process.argv[1]);

if (isMain) {
  const { css, blocks } = build();
  fs.writeFileSync(OUT, css, "utf8");
  const kb = Math.round(Buffer.byteLength(css) / 1024);
  console.log(`wrote ${path.relative(ROOT, OUT)}：${blocks} 条 @font-face，${kb} KB`);
}
