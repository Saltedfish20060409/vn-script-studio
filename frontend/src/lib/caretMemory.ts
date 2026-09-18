/**
 * 「上次停在这里」：记住你在这个剧本/这一章/这种稿（剧本 or RPY）里停笔的位置。
 *
 * 为什么不做"自动恢复光标"：线上数据里 90% 的章节不到一屏，自动跳光标对多数人是多余的，
 * 还会抢焦点（打开页面就把光标塞进正文，想先往前读两段的人会很烦）。
 * 所以这里只存位置 + 给一个「↩ 上次停在这里」的按钮，你要回去才回去。
 *
 * 存在 localStorage：跟"上次打开的剧本/章节"（workspacePersist）一样是**本设备**的记忆，
 * 不占后端、不参与多端合并。
 */

const KEY = "vnss-caret-memory-v1";
/** 最多记这么多条（按时间新的保留），别让 localStorage 无限长 */
export const MAX_CARET_ENTRIES = 60;
/** 超过这个时间的记录不再提示（一个月前停在哪，提示也没意义） */
export const MAX_CARET_AGE_MS = 30 * 24 * 60 * 60 * 1000;
/** 停在开头几个字符不算"停笔位置"（多半是刚打开还没写） */
export const MIN_CARET_OFFSET = 5;

export type CaretRecord = { offset: number; at: number };
export type CaretMap = Record<string, CaretRecord>;

/** 同一章在"剧本"和"RPY"是两份稿，位置要分开记。 */
export function caretKey(projectId: string, chapterId: string, mode: string): string {
  return `${projectId}|${chapterId}|${mode}`;
}

/** 记一条位置；超出上限时丢掉最旧的。 */
export function putCaret(
  map: CaretMap,
  key: string,
  offset: number,
  at: number = Date.now()
): CaretMap {
  const next: CaretMap = { ...map, [key]: { offset: Math.max(0, Math.floor(offset)), at } };
  const keys = Object.keys(next);
  if (keys.length <= MAX_CARET_ENTRIES) return next;
  const keep = keys
    .sort((a, b) => next[b].at - next[a].at)
    .slice(0, MAX_CARET_ENTRIES);
  const trimmed: CaretMap = {};
  for (const k of keep) trimmed[k] = next[k];
  return trimmed;
}

/**
 * 读一条位置：过期、太靠前、或者正文已经变短（位置越界）都当作"没有"。
 * 宁可少提示，也别把光标塞到一个不存在的位置上。
 */
export function readCaret(
  map: CaretMap,
  key: string,
  opts: { textLength: number; now?: number; maxAgeMs?: number; minOffset?: number }
): number | null {
  const rec = map[key];
  if (!rec) return null;
  const now = opts.now ?? Date.now();
  const maxAge = opts.maxAgeMs ?? MAX_CARET_AGE_MS;
  const minOffset = opts.minOffset ?? MIN_CARET_OFFSET;
  if (!Number.isFinite(rec.offset) || !Number.isFinite(rec.at)) return null;
  if (now - rec.at > maxAge) return null;
  if (rec.offset < minOffset) return null;
  if (rec.offset > opts.textLength) return null;
  return rec.offset;
}

/** 从 localStorage 读整张表（坏数据一律丢掉，不抛）。 */
export function loadCaretMap(storage?: Pick<Storage, "getItem"> | null): CaretMap {
  let store = storage ?? null;
  if (!storage) {
    try {
      store = window.localStorage;
    } catch {
      store = null;
    }
  }
  if (!store) return {};
  try {
    const raw = store.getItem(KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || typeof parsed !== "object") return {};
    const out: CaretMap = {};
    for (const [k, v] of Object.entries(parsed as Record<string, unknown>)) {
      const rec = v as Partial<CaretRecord>;
      if (typeof rec?.offset === "number" && typeof rec?.at === "number") {
        out[k] = { offset: rec.offset, at: rec.at };
      }
    }
    return out;
  } catch {
    return {};
  }
}

export function saveCaretMap(map: CaretMap, storage?: Pick<Storage, "setItem"> | null): void {
  let store = storage ?? null;
  if (!storage) {
    try {
      store = window.localStorage;
    } catch {
      store = null;
    }
  }
  try {
    store?.setItem(KEY, JSON.stringify(map));
  } catch {
    /* 隐私模式下写不进去也不该崩 */
  }
}

/** 记住"这个位置"最省事的一步到位版本（供组件调用）。 */
export function rememberCaret(
  projectId: string,
  chapterId: string,
  mode: string,
  offset: number
): void {
  if (!projectId || !chapterId) return;
  saveCaretMap(putCaret(loadCaretMap(), caretKey(projectId, chapterId, mode), offset));
}
