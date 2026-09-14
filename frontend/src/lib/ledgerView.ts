/**
 * 账本视图的纯计算逻辑（组件只负责渲染）。
 *
 * 数据来源：服务端在**保存时自动**维护的 `chapterIndex`（抽取式章节摘要）与
 * `writingLedger`（章节事实 / 角色状态 / 伏笔 / 入库日志）。
 */

import type {
  ChapterIndexEntry,
  LedgerChapterFact,
  LedgerCharacterState,
  LedgerForeshadow,
  VnProject,
} from "../types/vn";

export interface LedgerChapterRow {
  /** 可能来自 chapterIndex，也可能是正文兜底（chapterIndex 为空时） */
  entry: ChapterIndexEntry;
  fact?: LedgerChapterFact;
  states: LedgerCharacterState[];
  openForeshadows: number;
}

export interface LedgerOverview {
  chapters: number;
  digested: number;
  states: number;
  openForeshadows: number;
  paidForeshadows: number;
  updatedAt?: string;
}

export function isForeshadowOpen(f: LedgerForeshadow): boolean {
  return f.status !== "paid";
}

/**
 * 章节行：以 chapterIndex 为主序，用正文兜底补齐还没进索引的章节。
 * 「已入库」判定用的是账本里有没有这一章的事实行——服务端按内容指纹增量更新，
 * 所以有行就代表这一章的内容已经被抽进锚点了。
 */
export function buildChapterRows(project: VnProject): LedgerChapterRow[] {
  const index = project.chapterIndex || [];
  const chapters = project.chapters || [];
  const ledger = project.writingLedger || {};

  const facts = new Map<string, LedgerChapterFact>();
  for (const f of ledger.chapterFacts || []) {
    if (f?.chapterId) facts.set(f.chapterId, f);
  }

  const statesByChapter = new Map<string, LedgerCharacterState[]>();
  for (const s of ledger.characterStates || []) {
    const key = s?.chapterId || "";
    if (!key) continue;
    const list = statesByChapter.get(key) || [];
    list.push(s);
    statesByChapter.set(key, list);
  }

  const openByChapter = new Map<string, number>();
  for (const f of ledger.foreshadows || []) {
    if (!isForeshadowOpen(f) || !f?.plantedChapter) continue;
    openByChapter.set(f.plantedChapter, (openByChapter.get(f.plantedChapter) || 0) + 1);
  }

  const rows: LedgerChapterRow[] = [];
  const seen = new Set<string>();
  for (const entry of index) {
    if (!entry?.chapterId) continue;
    seen.add(entry.chapterId);
    rows.push({
      entry,
      fact: facts.get(entry.chapterId),
      states: statesByChapter.get(entry.chapterId) || [],
      openForeshadows: openByChapter.get(entry.chapterId) || 0,
    });
  }
  for (const ch of chapters) {
    if (!ch?.id || seen.has(ch.id)) continue;
    rows.push({
      entry: {
        chapterId: ch.id,
        title: ch.title,
        hash: "",
        synopsis: ch.synopsis,
      },
      fact: facts.get(ch.id),
      states: statesByChapter.get(ch.id) || [],
      openForeshadows: openByChapter.get(ch.id) || 0,
    });
  }
  return rows;
}

/** 按角色聚合状态历史（时间顺序，最后一条=最近状态），按记录条数降序。 */
export function groupCharacterStates(
  project: VnProject
): Array<[string, LedgerCharacterState[]]> {
  const states = project.writingLedger?.characterStates || [];
  const byChar = new Map<string, LedgerCharacterState[]>();
  for (const s of states) {
    const name = s?.characterName || s?.characterId || "未命名";
    const list = byChar.get(name) || [];
    list.push(s);
    byChar.set(name, list);
  }
  return [...byChar.entries()].sort((a, b) => b[1].length - a[1].length);
}

export function summarizeLedger(project: VnProject): LedgerOverview {
  const rows = buildChapterRows(project);
  const ledger = project.writingLedger || {};
  const foreshadows = ledger.foreshadows || [];
  const open = foreshadows.filter(isForeshadowOpen).length;
  return {
    chapters: rows.length,
    digested: rows.filter((r) => Boolean(r.fact)).length,
    states: (ledger.characterStates || []).length,
    openForeshadows: open,
    paidForeshadows: foreshadows.length - open,
    updatedAt: ledger.updatedAt,
  };
}

/** 章节是否"内容变了但还没重新入库"（只有服务端能算指纹，这里用启发式兜底）。 */
export function isChapterPending(row: LedgerChapterRow): boolean {
  return !row.fact;
}
