/**
 * 设定条目的纯逻辑：批量导入解析、关键字文本互转、新建。
 *
 * 抽出来是因为"导入时怎么切条目"是这类编辑器最容易出错的地方
 * （切错了用户就得手工重排几百条），值得用测试钉住。
 */

import type { LoreEntry } from "../types/vn";

let seq = 0;

function newId(): string {
  seq += 1;
  return `le-${Date.now().toString(36)}-${seq}`;
}

export function newLoreEntry(over: Partial<LoreEntry> = {}): LoreEntry {
  return {
    id: newId(),
    title: "",
    body: "",
    keywords: [],
    ...over,
  };
}

/** 关键字编辑框：数组 ↔ 文本（用顿号/逗号/空格分隔都能认）。 */
export function keywordsToText(keywords?: string[]): string {
  return (keywords ?? []).join("、");
}

export function parseKeywords(text: string): string[] {
  const out: string[] = [];
  for (const raw of (text ?? "").split(/[、,，;；\s]+/)) {
    const t = raw.trim();
    if (t && !out.includes(t)) out.push(t);
  }
  return out;
}

const KEYWORD_LINE = /^\s*(?:关键词|關鍵詞|keywords?|触发词|觸發詞)\s*[:：]\s*(.*)$/i;
const HEADING = /^\s*#{1,6}\s+(.*)$/;

export type ParsedImport = { title: string; body: string; keywords: string[] };

/**
 * 批量导入：把粘贴的大段设定切成条目。
 *
 * 切分规则（按优先级）：
 * 1. `# 标题` 这类 markdown 标题开新条目；
 * 2. 否则**空行**分段，每段第一行当标题；
 * 3. 段内以 `关键词：a、b` 开头的一行会被当作触发词（并从正文里去掉）。
 *
 * 为什么以空行为界：百万字设定通常是从 Word / Notion 直接贴过来的，
 * 标题层级未必规整，但"一条一块、块间空行"是最常见的写法。
 */
export function parseLoreImport(text: string): ParsedImport[] {
  const lines = (text ?? "").replace(/\r\n?/g, "\n").split("\n");
  const blocks: string[][] = [];
  let cur: string[] = [];
  const flush = () => {
    if (cur.some((l) => l.trim())) blocks.push(cur);
    cur = [];
  };
  for (const line of lines) {
    if (HEADING.test(line)) {
      flush();
      cur = [line];
      continue;
    }
    if (!line.trim()) {
      flush();
      continue;
    }
    cur.push(line);
  }
  flush();

  const out: ParsedImport[] = [];
  for (const block of blocks) {
    let title = "";
    const bodyLines: string[] = [];
    const keywords: string[] = [];
    let first = true;
    for (const line of block) {
      const head = line.match(HEADING);
      if (first) {
        title = (head ? head[1] : line).trim().replace(/^[【[]|[】\]]$/g, "");
        first = false;
        continue;
      }
      const kw = line.match(KEYWORD_LINE);
      if (kw) {
        for (const k of parseKeywords(kw[1])) {
          if (!keywords.includes(k)) keywords.push(k);
        }
        continue;
      }
      if (head) {
        bodyLines.push(head[1].trim());
        continue;
      }
      bodyLines.push(line);
    }
    if (!title) continue;
    out.push({ title, body: bodyLines.join("\n").trim(), keywords });
  }
  return out;
}

/** 导入结果 → 真条目（标题去重时追加序号，避免两条同名看着像 bug）。 */
export function importToEntries(parsed: ParsedImport[], existing: LoreEntry[] = []): LoreEntry[] {
  const used = new Set(existing.map((e) => e.title));
  return parsed.map((p) => {
    let title = p.title;
    if (used.has(title)) {
      let n = 2;
      while (used.has(`${title} (${n})`)) n += 1;
      title = `${title} (${n})`;
    }
    used.add(title);
    return newLoreEntry({ title, body: p.body, keywords: p.keywords });
  });
}
