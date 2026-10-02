/**
 * ADR 0001 Writing Turn 前端开关（P1 / P3）。
 *
 * - turn 默认开：写作走 `/agent/turn`
 * - 经典责编工具环默认关：不作为写作默认路径；开了才强调 `/agent/stream`
 * - 经典写作通道：B1 回滚时强制走 `/agent/write`
 * - 经典改稿对照（B6）：默认关；写作草稿走气泡轻确认，开了才默认弹左右对照
 *
 * 存 localStorage，不进工程数据（符合「API 可 breaking、工程数据不可破」）。
 */

const TURN_DEFAULT_KEY = "vnss-agent-turn-default-v1";
const LEGACY_TOOLS_KEY = "vnss-agent-legacy-tools-v1";
const LEGACY_WRITE_KEY = "vnss-agent-legacy-write-v1";
const CLASSIC_REVISE_UI_KEY = "vnss-agent-classic-revise-ui-v1";
const WRITE_MODE_KEY = "vnss-write-mode";

type StorageLike = Pick<Storage, "getItem" | "setItem" | "clear">;

function defaultStorage(): StorageLike | null {
  try {
    if (typeof globalThis === "undefined") return null;
    const g = globalThis as { localStorage?: StorageLike };
    return g.localStorage ?? null;
  } catch {
    return null;
  }
}

function readBool(
  key: string,
  defaultValue: boolean,
  storage?: StorageLike | null
): boolean {
  const store = storage === undefined ? defaultStorage() : storage;
  if (!store) return defaultValue;
  try {
    const raw = store.getItem(key);
    if (raw == null) return defaultValue;
    if (raw === "1" || raw === "true") return true;
    if (raw === "0" || raw === "false") return false;
    return defaultValue;
  } catch {
    return defaultValue;
  }
}

function writeBool(key: string, value: boolean, storage?: StorageLike | null): void {
  const store = storage === undefined ? defaultStorage() : storage;
  if (!store) return;
  try {
    store.setItem(key, value ? "1" : "0");
  } catch {
    /* ignore quota / private mode */
  }
}

/** 写作默认走 Writing Turn（ADR：AGENT_TURN_DEFAULT）。 */
export function isAgentTurnDefault(storage?: StorageLike | null): boolean {
  return readBool(TURN_DEFAULT_KEY, true, storage);
}

export function setAgentTurnDefault(
  on: boolean,
  storage?: StorageLike | null
): void {
  writeBool(TURN_DEFAULT_KEY, on, storage);
}

/**
 * 经典责编工具环（`/agent/stream`）是否作为可用入口强调。
 * 默认 false：写作主路径不走工具环；chat 在 P4 前仍可能内部调用 stream，但 UI 标注为高级。
 */
export function isLegacyAgentToolsEnabled(storage?: StorageLike | null): boolean {
  return readBool(LEGACY_TOOLS_KEY, false, storage);
}

export function setLegacyAgentToolsEnabled(
  on: boolean,
  storage?: StorageLike | null
): void {
  writeBool(LEGACY_TOOLS_KEY, on, storage);
}

/** B1：强制写作走旧 `/agent/write`（绕过 turn）。 */
export function isLegacyAgentWriteEnabled(storage?: StorageLike | null): boolean {
  return readBool(LEGACY_WRITE_KEY, false, storage);
}

export function setLegacyAgentWriteEnabled(
  on: boolean,
  storage?: StorageLike | null
): void {
  writeBool(LEGACY_WRITE_KEY, on, storage);
}

/**
 * B6：经典改稿对照面板是否作为写作草稿默认呈现。
 * 默认 false（P3）：草稿流式进气泡 + 轻确认写入；开了才默认弹左右对照。
 */
export function isClassicReviseUiEnabled(storage?: StorageLike | null): boolean {
  return readBool(CLASSIC_REVISE_UI_KEY, false, storage);
}

export function setClassicReviseUiEnabled(
  on: boolean,
  storage?: StorageLike | null
): void {
  writeBool(CLASSIC_REVISE_UI_KEY, on, storage);
}

/** 写作请求应走 turn 还是旧 write。 */
export function shouldUseAgentTurnForWrite(storage?: StorageLike | null): boolean {
  if (isLegacyAgentWriteEnabled(storage)) return false;
  return isAgentTurnDefault(storage);
}

/**
 * `vnss-write-mode` → API `writing_surface`。
 * 只有两种：prose | rpy（无 mixed/auto/preview）；其它脏值按 prose。
 */
export type WritingSurface = "prose" | "script";

export function resolveWritingSurface(storage?: StorageLike | null): WritingSurface {
  const store = storage === undefined ? defaultStorage() : storage;
  try {
    return store?.getItem(WRITE_MODE_KEY) === "rpy" ? "script" : "prose";
  } catch {
    return "prose";
  }
}

/**
 * 轻确认写入闸：无草稿 / busy 时禁止落库。
 * UI 用返回值决定 setError；勿静默 return。
 */
export function classifyWriteApplyBlocked(
  draft: unknown,
  busy: boolean
): "no_draft" | "busy" | null {
  if (!draft) return "no_draft";
  if (busy) return "busy";
  return null;
}

export function writeApplyBlockedMessage(reason: "no_draft" | "busy"): string {
  if (reason === "busy") return "正在处理中，请稍后再写入。";
  return "草稿已写入或已丢弃。";
}
