/**
 * 设定条目的纯逻辑：批量导入解析、关键字文本互转、新建。
 *
 * 抽出来是因为"导入时怎么切条目"是这类编辑器最容易出错的地方
 * （切错了用户就得手工重排几百条），值得用测试钉住。
 */

import type { LoreEntry, LoreLink } from "../types/vn";

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

// ---------------------------------------------------------------------------
// 触发词推荐
//
// 为什么要做：评论里的原话是「真的别做太复杂…不知道该怎么填」。
// 「触发词」这个词本身就让普通作者犯难——它其实是"别人提问时可能怎么称呼这条设定"。
// 所以导入后不该丢一个空输入框让作者自己想，而是**替他把候选词挑出来**，
// 他只要点一下「这条问的时候会叫它什么」的勾。
// ---------------------------------------------------------------------------

/** 从标题里剥掉"条目名后缀"，剩下的往往就是别人会用的简称（青云门 → 青云）。 */
const TITLE_SUFFIXES = [
  "门", "派", "宗", "教", "会", "团", "馆", "院", "城", "镇", "村", "山", "湖",
  "岛", "国", "军", "部", "司", "案", "录", "志", "典", "谱", "卷", "事", "记",
];

/** 从正文里抽可能被当成叫法的词：书名号/引号里的、以及重复出现的专名。 */
function termsFromBody(body: string): string[] {
  const out: string[] = [];
  const bracketed = body.match(/[《【「“]([^》】」”]{2,12})[》】」”]/g) ?? [];
  for (const raw of bracketed) {
    const t = raw.replace(/^[《【「“]|[》】」”]$/g, "").trim();
    if (t) out.push(t);
  }
  return out;
}

/**
 * 给一条设定推荐候选触发词（含去重、按可信度排序）。
 *
 * 顺序即优先级：标题本身 → 标题去掉后缀的简称 → 正文里的书名号/引号专名。
 * 只给「看起来像叫法」的词，不硬塞正文里的普通词——推荐错了比不推荐更烦人。
 */
export function suggestKeywords(title: string, body = "", limit = 5): string[] {
  const out: string[] = [];
  const push = (t: string) => {
    const v = t.trim();
    if (v.length < 2 || v.length > 12) return;
    if (!out.includes(v)) out.push(v);
  };

  const t = (title ?? "").trim();
  push(t);
  // 标题里的书名号/引号内容优先（「夺魂案」→ 夺魂案）
  for (const raw of t.match(/[《【「“]([^》】」”]{2,12})[》】」”]/g) ?? []) {
    push(raw.replace(/^[《【「“]|[》】」”]$/g, ""));
  }
  for (const suffix of TITLE_SUFFIXES) {
    if (t.length > suffix.length + 1 && t.endsWith(suffix)) {
      push(t.slice(0, t.length - suffix.length));
      break;
    }
  }
  for (const term of termsFromBody(body ?? "")) push(term);
  return out.slice(0, limit);
}

export type LoreImportDraft = {
  title: string;
  body: string;
  /** 去掉后缀的简称等候选，供作者点选 */
  suggested: string[];
  /** 作者已选中的触发词（默认 = 解析出来 + 推荐词） */
  keywords: string[];
  /** 是否导入这一条（预览里可以逐条取消） */
  include: boolean;
};

/** 导入预览里的一条：给作者看「会变成什么」，并让他勾选/改标题与触发词。 */
export function draftFromImport(p: ParsedImport): LoreImportDraft {
  const suggested = suggestKeywords(p.title, p.body);
  const keywords = [...p.keywords];
  for (const s of suggested) if (!keywords.includes(s)) keywords.push(s);
  return { title: p.title, body: p.body, keywords, suggested, include: true };
}

/** 预览里点一下触发词：加上 / 去掉。 */
export function toggleKeyword(keywords: string[], word: string): string[] {
  return keywords.includes(word)
    ? keywords.filter((k) => k !== word)
    : [...keywords, word];
}

/** 预览确认 → 真正要写入的条目参数（过滤掉取消勾选的、去掉空标题的）。 */
export function draftsToImports(
  drafts: LoreImportDraft[]
): Array<{ title: string; body: string; keywords: string[] }> {
  return drafts
    .filter((d) => d.include && d.title.trim())
    .map((d) => ({
      title: d.title.trim(),
      body: d.body,
      keywords: d.keywords.filter((k) => k.trim()),
    }));
}

// ---------------------------------------------------------------------------
// 实体链接（条目 → 角色 / 地点 / 章节）
//
// 为什么要做：条目原来只有触发词，等于孤岛——提问里没出现那个词就永远进不来。
// 作者其实知道"这条设定讲的是谁、在哪"；让他点一下，检索就能沿边走一步
// （命中条目带出关联角色，命中角色带出点名它的条目）。
// ---------------------------------------------------------------------------

export type LoreLinkOption = {
  toType: LoreLink["toType"];
  toId: string;
  /** 界面显示名 */
  label: string;
  /** 分组标题：角色 / 地点 / 章节 */
  group: string;
};

const GROUP_LABEL: Record<LoreLink["toType"], string> = {
  character: "角色",
  location: "地点",
  chapter: "章节",
};

/** 可供关联的实体清单（按项目当前内容生成；角色/地点/章节各自成组）。 */
export function loreLinkOptions(project: {
  characters?: Array<{ id: string; displayName?: string }>;
  locations?: Array<{ id: string; name?: string }>;
  chapters?: Array<{ id: string; title?: string }>;
}): LoreLinkOption[] {
  const out: LoreLinkOption[] = [];
  for (const c of project.characters ?? []) {
    if (!c?.id) continue;
    out.push({ toType: "character", toId: c.id, label: c.displayName || c.id, group: GROUP_LABEL.character });
  }
  for (const l of project.locations ?? []) {
    if (!l?.id) continue;
    out.push({ toType: "location", toId: l.id, label: l.name || l.id, group: GROUP_LABEL.location });
  }
  for (const ch of project.chapters ?? []) {
    if (!ch?.id) continue;
    out.push({ toType: "chapter", toId: ch.id, label: ch.title || ch.id, group: GROUP_LABEL.chapter });
  }
  return out;
}

/** 已关联的边 → 显示名（找不到实体时退回 id，避免界面上出现空白）。 */
export function loreLinkLabel(link: LoreLink, options: LoreLinkOption[]): string {
  return (
    options.find((o) => o.toType === link.toType && o.toId === link.toId)?.label ?? link.toId
  );
}

/** 点一下：没关联就加上，已关联就去掉。 */
export function toggleLoreLink(links: LoreLink[] | undefined, next: LoreLink): LoreLink[] {
  const list = links ?? [];
  const hit = list.find((l) => l.toType === next.toType && l.toId === next.toId);
  if (hit) return list.filter((l) => !(l.toType === next.toType && l.toId === next.toId));
  return [...list, next];
}

/** 去掉指向已删实体的边（保存前清一遍，免得上下文里带出"关联到不存在的东西"）。 */
export function pruneLoreLinks(
  links: LoreLink[] | undefined,
  options: LoreLinkOption[]
): LoreLink[] {
  return (links ?? []).filter((l) =>
    options.some((o) => o.toType === l.toType && o.toId === l.toId)
  );
}

