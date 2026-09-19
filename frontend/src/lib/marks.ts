/**
 * 写作页「标记批改」的标记模型（纯逻辑，便于测试）。
 *
 * 作者在正文里选中一段 → 标记 → 让 AI 只改这一处。
 *
 * 为什么要存 quote + 前后文，而不只存 offset：正文随时会被编辑，**偏移必然漂移**。
 * 所以定位一律走"引用 + 上下文"重新找（findMarkRange），找不到就标成 stale 让人确认，
 * 绝不"按旧偏移硬改"——那会把改动落在别的地方。
 */

export type MarkIntent = "rewrite" | "advice";

/** pending=待处理 / suggested=已有结果待决定 / accepted=已写入正文 / rejected=不要 / stale=定位失效 */
export type MarkStatus = "pending" | "suggested" | "accepted" | "rejected" | "stale";

export type Mark = {
  id: string;
  chapterId: string;
  /** 选中原文 */
  quote: string;
  /** 前后各一段（定位用；也顺手当上下文给模型） */
  prefix: string;
  suffix: string;
  /** 作者写的要求，可留空 */
  instruction: string;
  intent: MarkIntent;
  status: MarkStatus;
  /** 改写结果（intent=rewrite 且已处理） */
  replacement?: string;
  /** 建议（intent=advice） */
  advice?: string;
  /** 处理失败的原因 */
  error?: string;
  createdAt: number;
  /** 已接受的标记：记下实际写入的位置，便于"撤回这一条" */
  appliedAt?: number;
};

const CONTEXT_CHARS = 24;

export function newMarkId(): string {
  return `mk-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
}

/** 取出选区两侧的上下文（给模型当"上文/下文"，也用于重新定位）。 */
export function markContext(
  text: string,
  from: number,
  to: number,
  ctx: number = CONTEXT_CHARS
): { quote: string; prefix: string; suffix: string } {
  const start = Math.max(0, Math.min(from, text.length));
  const end = Math.max(start, Math.min(to, text.length));
  return {
    quote: text.slice(start, end),
    prefix: text.slice(Math.max(0, start - ctx), start),
    suffix: text.slice(end, Math.min(text.length, end + ctx)),
  };
}

/**
 * 建一个标记。选区为空（或只有空白）时返回 null —— 空标记没有意义。
 */
export function createMark(opts: {
  text: string;
  from: number;
  to: number;
  chapterId: string;
  intent?: MarkIntent;
  instruction?: string;
  now?: number;
}): Mark | null {
  const { quote, prefix, suffix } = markContext(opts.text, opts.from, opts.to);
  if (!quote.trim()) return null;
  return {
    id: newMarkId(),
    chapterId: opts.chapterId,
    quote,
    prefix,
    suffix,
    instruction: (opts.instruction ?? "").trim(),
    intent: opts.intent ?? "rewrite",
    status: "pending",
    createdAt: opts.now ?? Date.now(),
  };
}

/**
 * 在当前正文里重新定位一个标记。
 * 优先"上文+原文+下文"整段唯一命中，其次原文唯一命中，最后退回首次出现。
 * 都找不到 → null（调用方标成 stale，让人来确认）。
 */
export function findMarkRange(text: string, mark: Mark): { from: number; to: number } | null {
  const quote = mark.quote;
  if (!quote) return null;

  const withContext = `${mark.prefix}${quote}${mark.suffix}`;
  if (mark.prefix || mark.suffix) {
    const idx = text.indexOf(withContext);
    if (idx >= 0 && text.indexOf(withContext, idx + 1) < 0) {
      const from = idx + mark.prefix.length;
      return { from, to: from + quote.length };
    }
  }

  const first = text.indexOf(quote);
  if (first < 0) return null;
  const second = text.indexOf(quote, first + 1);
  if (second < 0) return { from: first, to: first + quote.length };
  // 多处命中：用上下文挑最近的那个；仍不确定时取第一处（并在 UI 上让用户先"跳转"确认）
  if (mark.prefix) {
    const byPrefix = text.indexOf(`${mark.prefix}${quote}`);
    if (byPrefix >= 0) {
      const from = byPrefix + mark.prefix.length;
      return { from, to: from + quote.length };
    }
  }
  return { from: first, to: first + quote.length };
}

/** 是否还能在当前正文里定位到（用于把失效标记标出来）。 */
export function isLocatable(text: string, mark: Mark): boolean {
  return findMarkRange(text, mark) !== null;
}

/**
 * 标记**现在**在正文里的位置。
 *
 * 已接受的标记要找的是**改写后的那段**——原文已经被替换掉了，用 quote 找必然找不到，
 * 那会导致刚接受完卡片就失去锚点（连带「撤回这次改动」也点不到）。
 * 前/后文没被这次改动碰过，所以拿它们 + 改写稿定位是准的。
 */
export function currentMarkRange(text: string, mark: Mark): { from: number; to: number } | null {
  if (mark.status === "accepted" && mark.replacement) {
    return findMarkRange(text, { ...mark, quote: mark.replacement });
  }
  return findMarkRange(text, mark);
}

/**
 * 把标记的改写结果写进正文。
 * 返回新正文与这次改动的区间（区间用于"跳转/高亮/撤回"）；定位失败返回 null。
 */
export function applyMark(
  text: string,
  mark: Mark,
  replacementOverride?: string
): { text: string; from: number; to: number } | null {
  const replacement = replacementOverride ?? mark.replacement ?? "";
  const range = findMarkRange(text, mark);
  if (!range) return null;
  const next = text.slice(0, range.from) + replacement + text.slice(range.to);
  return { text: next, from: range.from, to: range.from + replacement.length };
}

/**
 * 撤回一次已应用的改动：把改后的文本换回原文（用同样的定位方式反着找）。
 * 找不到（用户后来又改过）返回 null。
 */
export function revertMark(
  text: string,
  mark: Mark,
  replacementOverride?: string
): { text: string; from: number; to: number } | null {
  const replacement = replacementOverride ?? mark.replacement ?? "";
  if (!replacement) return null;
  const inverse: Mark = { ...mark, quote: replacement };
  return applyMark(text, inverse, mark.quote);
}

/** 把正文里已经定位不到的标记标成 stale；已定位到的从 stale 恢复成 pending/suggested。 */
export function refreshMarks(text: string, marks: Mark[]): Mark[] {
  let changed = false;
  const next = marks.map((m) => {
    if (m.status === "accepted" || m.status === "rejected") return m;
    const locatable = isLocatable(text, m);
    if (!locatable && m.status !== "stale") {
      changed = true;
      return { ...m, status: "stale" as MarkStatus };
    }
    if (locatable && m.status === "stale") {
      changed = true;
      return { ...m, status: (m.replacement || m.advice ? "suggested" : "pending") as MarkStatus };
    }
    return m;
  });
  return changed ? next : marks;
}

export function pendingMarks(marks: Mark[]): Mark[] {
  return marks.filter((m) => m.status === "pending" || m.status === "suggested");
}

export function markStats(marks: Mark[]) {
  return {
    total: marks.length,
    pending: marks.filter((m) => m.status === "pending" || m.status === "suggested").length,
    accepted: marks.filter((m) => m.status === "accepted").length,
    stale: marks.filter((m) => m.status === "stale").length,
  };
}

/** 面板/按钮上显示的短引用：压缩空白并截断。 */
export function shortQuote(quote: string, max = 28): string {
  const flat = quote.replace(/\s+/g, " ").trim();
  return flat.length > max ? `${flat.slice(0, max)}…` : flat;
}

// ---------------------------------------------------------------------------
// 存储（localStorage：本设备的"工作台便签"，改完即销，不进工程数据）
// ---------------------------------------------------------------------------

const STORE_KEY = "vnss-marks-v1";
/** 每条最多留这么多（超了丢最旧的），别让 localStorage 无限长 */
export const MAX_MARKS_PER_CHAPTER = 80;

type MarkMap = Record<string, Mark[]>;

export function chapterKey(projectId: string, chapterId: string): string {
  return `${projectId}|${chapterId}`;
}

function readAll(storage?: Pick<Storage, "getItem"> | null): MarkMap {
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
    const raw = store.getItem(STORE_KEY);
    if (!raw) return {};
    const parsed = JSON.parse(raw) as unknown;
    if (!parsed || typeof parsed !== "object") return {};
    const out: MarkMap = {};
    for (const [key, value] of Object.entries(parsed as Record<string, unknown>)) {
      if (!Array.isArray(value)) continue;
      const marks = value.filter(
        (m): m is Mark =>
          !!m && typeof m === "object" && typeof (m as Mark).quote === "string" && !!(m as Mark).id
      );
      if (marks.length) out[key] = marks;
    }
    return out;
  } catch {
    return {};
  }
}

function writeAll(map: MarkMap, storage?: Pick<Storage, "setItem"> | null): void {
  let store = storage ?? null;
  if (!storage) {
    try {
      store = window.localStorage;
    } catch {
      store = null;
    }
  }
  try {
    store?.setItem(STORE_KEY, JSON.stringify(map));
  } catch {
    /* 隐私模式下写不进去也不该崩 */
  }
}

export function loadMarks(
  projectId: string,
  chapterId: string,
  storage?: Pick<Storage, "getItem"> | null
): Mark[] {
  if (!projectId || !chapterId) return [];
  return readAll(storage)[chapterKey(projectId, chapterId)] ?? [];
}

export function saveMarks(
  projectId: string,
  chapterId: string,
  marks: Mark[],
  storage?: (Pick<Storage, "getItem"> & Pick<Storage, "setItem">) | null
): void {
  if (!projectId || !chapterId) return;
  const map = readAll(storage);
  const key = chapterKey(projectId, chapterId);
  const kept = marks
    .slice()
    .sort((a, b) => a.createdAt - b.createdAt)
    .slice(-MAX_MARKS_PER_CHAPTER);
  if (kept.length) map[key] = kept;
  else delete map[key];
  writeAll(map, storage);
}
