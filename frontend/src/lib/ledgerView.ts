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

/** 一条伏笔带"埋了多久 / 什么时候回收"，供面板直接显示。 */
export type ForeshadowRow = {
  id: string;
  hook: string;
  status: string;
  /** 埋在第几章（标题） */
  plantedLabel: string;
  /** 已回收时：回收于第几章（标题） */
  paidLabel: string;
  /** 埋点 →（回收章｜最新章）隔了几章；算不出为 null */
  ageChapters: number | null;
  note: string;
};

/**
 * 伏笔清单：补上"埋了多久、回收于第几章"。
 *
 * 为什么界面也要算：账本里只存 open/paid 时，作者看不出"这条已经埋了 20 章还没收"——
 * 而长篇最需要盯的就是这个。后端 `foreshadow_report` 是同一套算法（硬锚块用它提醒模型）。
 */
export function foreshadowRows(project: VnProject): ForeshadowRow[] {
  const foreshadows = project.writingLedger?.foreshadows || [];
  if (!foreshadows.length) return [];

  const order = new Map<string, number>();
  (project.chapters || []).forEach((c, i) => order.set(c.id, i));
  const titleOf = (id?: string) => {
    if (!id) return "";
    const ch = (project.chapters || []).find((c) => c.id === id);
    return ch?.title || id;
  };
  const last = Math.max(0, (project.chapters || []).length - 1);
  const rank = (s?: string) =>
    s === "paid" ? 2 : s === "open" ? 0 : 1;

  return foreshadows
    .map((f, i) => {
      const planted = f.plantedChapter || "";
      const paidIn = f.paidInChapter || "";
      const status = f.status || "open";
      const pIdx = order.get(planted);
      const endIdx = status === "paid" ? order.get(paidIn) ?? last : last;
      return {
        id: f.id || `f${i}`,
        hook: f.hook || "（无描述）",
        status,
        plantedLabel: titleOf(planted),
        paidLabel: paidIn ? titleOf(paidIn) : "",
        ageChapters: pIdx === undefined ? null : Math.max(0, endIdx - pIdx),
        note: f.note || "",
      };
    })
    .sort((a, b) => rank(a.status) - rank(b.status) || (b.ageChapters ?? 0) - (a.ageChapters ?? 0));
}

/** 一句人话概括：未回收几条、其中埋了 5 章以上几条（面板顶部用）。 */
export function foreshadowSummary(rows: ForeshadowRow[]): string {
  const open = rows.filter((r) => r.status !== "paid");
  const stale = open.filter((r) => (r.ageChapters ?? 0) >= 5).length;
  if (!rows.length) return "";
  if (!open.length) return `${rows.length} 条伏笔，全部已回收`;
  return (
    `${rows.length} 条伏笔 · 未回收 ${open.length}` +
    (stale ? `（其中 ${stale} 条埋了 5 章以上）` : "")
  );
}

/** 章节是否"内容变了但还没重新入库"（只有服务端能算指纹，这里用启发式兜底）。 */
export function isChapterPending(row: LedgerChapterRow): boolean {
  return !row.fact;
}
