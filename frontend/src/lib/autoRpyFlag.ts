/**
 * P5-B：正文档写入成功后是否自动 generate_rpy_from_prose。
 * 存 localStorage，默认开；关则只提示、不自动调 LLM。
 */

const KEY = "vnss-auto-rpy-after-prose-write-v1";

type StorageLike = Pick<Storage, "getItem" | "setItem">;

function defaultStorage(): StorageLike | null {
  try {
    if (typeof globalThis === "undefined") return null;
    const g = globalThis as { localStorage?: StorageLike };
    return g.localStorage ?? null;
  } catch {
    return null;
  }
}

/** 默认 true（未写入 key 时）。 */
export function isAutoRpyAfterProseWriteEnabled(
  storage: StorageLike | null = defaultStorage()
): boolean {
  if (!storage) return true;
  const raw = storage.getItem(KEY);
  if (raw === null || raw === undefined || raw === "") return true;
  return raw === "1" || raw === "true";
}

export function setAutoRpyAfterProseWriteEnabled(
  on: boolean,
  storage: StorageLike | null = defaultStorage()
): void {
  if (!storage) return;
  storage.setItem(KEY, on ? "1" : "0");
}
