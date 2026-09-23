/**
 * 读者行为遥测（前端侧）—— 把「玩家在试玩里选了什么」记下来，一次试玩上报一次。
 *
 * 与 `lib/track.ts` 同姿态（沿用既有埋点的隐私与失败处理，不另立一套）：
 * - **fire-and-forget**：上报失败绝不打扰玩家、不弹错、不阻塞播放；
 * - **攒批 + 定量**：一次试玩只在上报队列里占一条，flush 时批量发出去；
 * - **失败丢弃、不重试**：埋点不值得刷请求；
 * - **只记标识符**：库里没有任何自由文本列，选项文案/台词在物理上没有容器可放。
 *
 * 三条从后端源码抄来的硬约束（`backend/app/services/playtest_telemetry.py`）：
 * 1. 每个字符串列都要过 `^[A-Za-z_][A-Za-z0-9_.:-]{0,63}$` —— **中文会落成空串**，
 *    所以选项文案一概不发，只发 menuId / choiceIndex / conditionPassed / seq /
 *    chapterId / label。净化在前端也做一遍（`sanitizeIdentifier`），并统计丢了多少，
 *    而不是只依赖后端兜底。
 * 2. `client_run_id` 必须是 8~64 位 URL 安全随机串（熵不足 → 400），且是幂等键的一半：
 *    `(project_id, client_run_id)` 唯一，重复上报只补缺失的 seq。所以同一次试玩全程
 *    复用同一个 id（这也是「页面隐藏时先发快照、结束时再发全量」能安全重复上报的原因）。
 * 3. 未开启采集时后端返回 **403 `telemetry_disabled`**：这是「工程没开采集」，不是
 *    「上报失败」——识别出来就停掉本次会话的后续上报，绝不刷接口。
 *
 * 关于 `sendBeacon`：`apiFetch` 用 Authorization 头鉴权，而 `sendBeacon` 无法带自定义
 * 头（后端 `get_current_user` 只认 Bearer，不认 cookie）。所以页面隐藏时的兜底用的是
 * **`fetch(..., { keepalive: true })`**：同样是"页面走了也尽量发完"的语义，但能带鉴权头。
 */

import type { PlaytestChoiceIn, PlaytestRecordIn } from "../api/projects";

/**
 * 重新导出上报体类型：调用方（试玩器 / 作者面板）只需要认 `lib/playtestTelemetry`，
 * 不用同时 import 两处。类型导入是编译期擦除的，不会把 api 模块拖进主 chunk。
 */
export type { PlaytestChoiceIn, PlaytestRecordIn };

/* ------------------------------------------------------- 与后端对齐的常量与白名单 */

/** 单次上报的选择条数上限（与后端 `MAX_CHOICES_PER_RUN`、试玩器 2000 步对齐）。 */
export const MAX_CHOICES_PER_RUN = 2000;
/** `chapter_count` 的上限（后端 `_MAX_CHAPTERS`）。 */
export const MAX_CHAPTERS = 5000;

const IDENTIFIER_MAX_LEN = 64;
/** 后端 `_IDENTIFIER_RE`：ASCII 标识符，最长 64。 */
const IDENTIFIER_RE = /^[A-Za-z_][A-Za-z0-9_.:-]{0,63}$/;
/** 后端 `_CLIENT_RUN_RE`：8~64 位 URL 安全字符。 */
const CLIENT_RUN_RE = /^[A-Za-z0-9_-]{8,64}$/;
/** 上报 id 的随机字节数：16 字节 × 6 bit = 96 bit 熵（远高于 64 bit 下限）。 */
const ID_BYTES = 16;
/** 64 个 URL 安全字符 —— 每字节取 6 bit 正好均匀落在 64 个字符上。 */
const ID_ALPHABET =
  "ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghijklmnopqrstuvwxyz0123456789-_";
/** 丢弃的字段名最多回显几个（后端 `_MAX_DROPPED_KEYS`）。 */
const MAX_DROPPED_NAMES = 12;
/** 字段名本身的截断长度（名字也可能被用来夹带内容）。 */
const MAX_DROPPED_NAME_LEN = 40;

/** 队列里最多攒几次待上报的试玩；超出丢最旧的（不丢刚发生的那次）。 */
const QUEUE_LIMIT = 8;

/** 时间窗口（与后端 `_as_datetime` 一致）：太久远 / 太未来的时间只会污染时长统计。 */
const MIN_TIME_MS = Date.UTC(2000, 0, 1);
const MAX_TIME_AHEAD_MS = 24 * 3600 * 1000;

/** 后端 `_CHOICE_KEYS`：只有这些键会落库，别的键一律被丢弃。 */
const CHOICE_KEYS = new Set([
  "seq",
  "chapterId",
  "label",
  "menuId",
  "choiceIndex",
  "conditionPassed",
]);

/**
 * 本地会记、但**故意不发**的键。
 *
 * `condition`（条件表达式）是最常见的一个：它不在后端白名单里，而且属于"正文类字符串"，
 * 发过去只会被丢弃并回显在 `droppedFields` 里。前端在这里先丢掉，既少一次无用的往返，
 * 也让"哪些字段没发出去"这件事在 `dropped.fieldNames` 里可观测。
 */
const LOCAL_ONLY_CHOICE_KEYS = ["condition"];

/* ------------------------------------------------------------------- 随机 id */

/** 只要求用到的两个方法，方便测试注入确定性随机源。 */
export type CryptoLike = {
  randomUUID?: () => string;
  getRandomValues?: (array: Uint8Array) => Uint8Array;
};

function defaultCrypto(): CryptoLike | null {
  const c = (globalThis as { crypto?: CryptoLike }).crypto;
  return c ?? null;
}

/**
 * 生成 `client_run_id`：优先 `crypto.randomUUID()`，退化到 `crypto.getRandomValues`。
 *
 * **没有 `Math.random()` 兜底**：它不保证密码学随机，熵不足会被后端当无效 id 拒掉
 * （400），而"看起来发出去了其实一条都没落库"是最难查的一种失败。没有可用的随机源时
 * 返回空串，调用方据此放弃上报（宁可不记，也不发一个可能是伪造/碰撞的 id）。
 *
 * @param source 随机源；不传用 `globalThis.crypto`，传 `null` 表示"假定没有随机源"
 */
export function createClientRunId(source?: CryptoLike | null): string {
  const c = source === undefined ? defaultCrypto() : source;
  if (!c) return "";
  try {
    if (typeof c.randomUUID === "function") {
      const id = c.randomUUID();
      if (typeof id === "string" && CLIENT_RUN_RE.test(id)) return id;
    }
  } catch {
    /* 退化到 getRandomValues */
  }
  try {
    if (typeof c.getRandomValues === "function") {
      const bytes = c.getRandomValues(new Uint8Array(ID_BYTES));
      let out = "";
      for (let i = 0; i < bytes.length; i++) out += ID_ALPHABET[bytes[i] & 63];
      return out;
    }
  } catch {
    /* 没有可用的随机源 */
  }
  return "";
}

/* ---------------------------------------------------------------------- 净化 */

/**
 * 标识符白名单（前端侧的镜像实现）：不合格就返回空串。
 *
 * 中文、空格、引号、任何文案都会在这里变成空串 —— 与后端 `sanitize_identifier` 同口径，
 * 于是"界面看着发出去了、库里却是空的"不可能发生两次判断不一致的情况。
 */
export function sanitizeIdentifier(value: unknown): string {
  if (typeof value !== "string") return "";
  const text = value.trim();
  if (!text || text.length > IDENTIFIER_MAX_LEN) return "";
  return IDENTIFIER_RE.test(text) ? text : "";
}

function clampCount(value: unknown, max: number): number {
  if (typeof value !== "number" || !Number.isFinite(value)) return 0;
  return Math.max(0, Math.min(max, Math.trunc(value)));
}

function clampChoiceIndex(value: unknown): number {
  if (typeof value !== "number" || !Number.isFinite(value)) return -1;
  return Math.max(-1, Math.min(9999, Math.trunc(value)));
}

/** 时间 → ISO 8601（带时区）；解析不出来或落在可疑窗口外返回空串（后端会当"没报"）。 */
export function isoOrEmpty(value: unknown, now: number = Date.now()): string {
  let ms: number;
  if (value instanceof Date) ms = value.getTime();
  else if (typeof value === "number") ms = value;
  else if (typeof value === "string") ms = Date.parse(value.trim());
  else return "";
  if (!Number.isFinite(ms)) return "";
  if (ms < MIN_TIME_MS || ms > now + MAX_TIME_AHEAD_MS) return "";
  const date = new Date(ms);
  return Number.isFinite(date.getTime()) ? date.toISOString() : "";
}

function pushName(names: string[], key: string): void {
  const name = key.slice(0, MAX_DROPPED_NAME_LEN);
  if (name && !names.includes(name) && names.length < MAX_DROPPED_NAMES) names.push(name);
}

/* ---------------------------------------------------------------- 构造上报体 */

/** 试玩器本地记的一条选择。键名是 camelCase（本地形状），发出去时转成后端要的 snake_case。 */
export type LocalPlaytestChoice = {
  /** 缺省 = 用它在数组里的位置；非法（负数 / 超上限 / 非整数）整条丢弃（与后端同口径） */
  seq?: number;
  chapterId?: string;
  label?: string;
  menuId?: string;
  /** 选项在菜单原始 choices 数组里的下标 */
  choiceIndex?: number;
  /** 本地备注用；不在后端白名单里，不会发出去（见 LOCAL_ONLY_CHOICE_KEYS） */
  condition?: string;
  /** 选中时条件是否成立；缺省 true（与后端 `_as_bool(..., True)` 同口径） */
  conditionPassed?: boolean;
};

export type PlaytestRecordInput = {
  clientRunId?: string;
  startedAt?: string | number | Date;
  endedAt?: string | number | Date;
  chapterCount?: number;
  endingLabel?: string;
  choices?: readonly (LocalPlaytestChoice | null | undefined)[] | null;
};

/** 丢了多少：给"前后端两处都防"留一个可观测的口径。 */
export type PlaytestDropStats = {
  /** 不在后端白名单里、被前端先丢掉的字段名（`condition` 是最常见的命中） */
  fieldNames: string[];
  /** 因为不符合 ASCII 标识符白名单而被清空的字符串个数（中文 label / 章节名都会命中） */
  emptiedValues: number;
  /** 因为 seq 非法而整条丢弃的选择数 */
  rejectedChoices: number;
  /** 超过单次上报上限被截断的选择数 */
  truncatedChoices: number;
};

export type BuildPlaytestResult = {
  payload: PlaytestRecordIn;
  /** 本次真正使用的 client_run_id（输入缺失/非法时新生成；没有随机源时为空串） */
  clientRunId: string;
  /** 实际发出去的选择条数（= `run.choice_count`） */
  choiceCount: number;
  dropped: PlaytestDropStats;
};

export type BuildPlaytestOptions = {
  /** 注入随机源（测试用）；`null` = 假定没有随机源 */
  crypto?: CryptoLike | null;
  /** 注入"现在"（时间窗口校验用，测试用） */
  now?: number;
};

/**
 * 把「选择历史 + 章节推进」构造成上报体 —— **纯函数**，不碰 DOM、不发请求。
 *
 * 输入是普通的 JS 对象数组（试玩器自己攒的），输出是后端要的 snake_case 形状：
 * `{run: {client_run_id, started_at, ended_at, chapter_count, choice_count, ending_label},
 *   choices: [{seq, chapter_id, label, menu_id, choice_index, condition_passed}]}`。
 *
 * 单次试玩的正常路径只调用一次（一次试玩 = 一次请求）。重复 seq 保留最后一条并按 seq
 * 升序（与后端 `sanitize_choices` 同口径），因为幂等合并是按 seq 做的。
 */
export function buildPlaytestRecord(
  input: PlaytestRecordInput,
  opts: BuildPlaytestOptions = {}
): BuildPlaytestResult {
  const now = typeof opts.now === "number" ? opts.now : Date.now();
  const fieldNames: string[] = [];
  let emptiedValues = 0;
  let rejectedChoices = 0;

  const requestedId =
    typeof input.clientRunId === "string" ? input.clientRunId.trim() : "";
  const clientRunId = CLIENT_RUN_RE.test(requestedId)
    ? requestedId
    : createClientRunId(opts.crypto === undefined ? undefined : opts.crypto);

  const raw = Array.isArray(input.choices) ? input.choices : [];
  const truncatedChoices = Math.max(0, raw.length - MAX_CHOICES_PER_RUN);
  const bySeq = new Map<number, PlaytestChoiceIn>();

  raw.slice(0, MAX_CHOICES_PER_RUN).forEach((item, position) => {
    if (!item || typeof item !== "object") {
      rejectedChoices += 1;
      return;
    }
    for (const key of Object.keys(item)) {
      if (!CHOICE_KEYS.has(key) && !LOCAL_ONLY_CHOICE_KEYS.includes(key)) {
        pushName(fieldNames, key);
      }
    }
    for (const key of LOCAL_ONLY_CHOICE_KEYS) {
      if (key in item) pushName(fieldNames, key);
    }

    const rawSeq = (item as { seq?: unknown }).seq;
    const seq =
      rawSeq === undefined
        ? position
        : typeof rawSeq === "number" && Number.isInteger(rawSeq)
          ? rawSeq
          : -1;
    if (seq < 0 || seq > MAX_CHOICES_PER_RUN) {
      rejectedChoices += 1;
      return;
    }

    const chapterId = sanitizeIdentifier(item.chapterId);
    const label = sanitizeIdentifier(item.label);
    const menuId = sanitizeIdentifier(item.menuId);
    for (const [before, after] of [
      [item.chapterId, chapterId],
      [item.label, label],
      [item.menuId, menuId],
    ] as const) {
      if (typeof before === "string" && before.trim() && !after) emptiedValues += 1;
    }

    bySeq.set(seq, {
      seq,
      chapter_id: chapterId,
      label,
      menu_id: menuId,
      choice_index: clampChoiceIndex(item.choiceIndex),
      condition_passed: item.conditionPassed === undefined ? true : Boolean(item.conditionPassed),
    });
  });

  const choices = [...bySeq.values()].sort((a, b) => a.seq - b.seq);

  const startedAt = isoOrEmpty(input.startedAt, now);
  let endedAt = isoOrEmpty(input.endedAt, now);
  if (endedAt && startedAt && Date.parse(endedAt) < Date.parse(startedAt)) {
    endedAt = ""; // 时间倒流：宁可当成"没结束"，也不要污染时长统计（后端也会这么抹掉）
  }

  const endingLabel = sanitizeIdentifier(input.endingLabel);
  if (typeof input.endingLabel === "string" && input.endingLabel.trim() && !endingLabel) {
    emptiedValues += 1;
  }

  return {
    clientRunId,
    choiceCount: choices.length,
    dropped: { fieldNames, emptiedValues, rejectedChoices, truncatedChoices },
    payload: {
      run: {
        client_run_id: clientRunId,
        started_at: startedAt,
        ended_at: endedAt,
        chapter_count: clampCount(input.chapterCount, MAX_CHAPTERS),
        choice_count: choices.length,
        ending_label: endingLabel,
      },
      choices,
    },
  };
}

/* ------------------------------------------------------------- 传输与队列 */

export type PlaytestSendOutcome = "ok" | "disabled" | "error";

export type PlaytestSender = (
  projectId: string,
  payload: PlaytestRecordIn,
  opts: { keepalive: boolean }
) => Promise<PlaytestSendOutcome>;

export type PlaytestFlushOutcome = {
  /** 成功上报的次数 */
  sent: number;
  /** 失败并被丢弃（不重试）的次数 */
  failed: number;
  /** 后端说"没开采集"而放弃的次数（含被连带丢弃的排队项） */
  skipped: number;
  /** true = 这次 flush 之后，本次会话不再上报 */
  disabled: boolean;
};

export type PlaytestEnqueueOutcome = "added" | "merged" | "rejected";

type QueueItem = { projectId: string; payload: PlaytestRecordIn; key: string };

let queue: QueueItem[] = [];
let telemetryDisabled = false;
let sender: PlaytestSender = defaultSender;
let projectsApi: Promise<typeof import("../api/projects")> | null = null;

/** 复用同一个模块 promise：页面隐藏时的兜底上报不用等磁盘再取一次模块。 */
function loadProjectsApi(): Promise<typeof import("../api/projects")> {
  projectsApi ??= import("../api/projects");
  return projectsApi;
}

/**
 * 后端把「没开采集」串行化成 403 + `detail.code === "telemetry_disabled"`。
 *
 * 判定刻意**不依赖 `ApiError` 实例**（结构判断，测试可以直接喂普通对象），而且只认
 * 这一个 code：别的 403（例如不是工程成员）是另一种失败，不该被当成"作者关了开关"。
 */
export function isTelemetryDisabled(error: unknown): boolean {
  if (!error || typeof error !== "object") return false;
  const e = error as { status?: unknown; detail?: unknown; message?: unknown };
  if (e.status !== 403) return false;
  const detail = e.detail;
  if (detail && typeof detail === "object") {
    const code = (detail as { code?: unknown }).code;
    if (typeof code === "string") return code === "telemetry_disabled";
  }
  if (typeof detail === "string" && detail.includes("telemetry_disabled")) return true;
  return typeof e.message === "string" && e.message.includes("telemetry_disabled");
}

async function defaultSender(
  projectId: string,
  payload: PlaytestRecordIn,
  opts: { keepalive: boolean }
): Promise<PlaytestSendOutcome> {
  try {
    const api = await loadProjectsApi();
    await api.recordPlaytest(projectId, payload, { keepalive: opts.keepalive });
    return "ok";
  } catch (e) {
    // 失败绝不重试、绝不打扰玩家：排队项到这里就结束了。
    return isTelemetryDisabled(e) ? "disabled" : "error";
  }
}

/** 注入传输实现（测试用；也可用于把上报转发到别的通道）。传 null 恢复默认。 */
export function setPlaytestSender(next: PlaytestSender | null): void {
  sender = next ?? defaultSender;
}

/** 队列里还有几次待上报的试玩（调试 / 测试用）。 */
export function queuedPlaytestCount(): number {
  return queue.length;
}

/** true = 后端已经明确说过"这个工程没开采集"，本次会话不再上报。 */
export function isPlaytestTelemetryDisabled(): boolean {
  return telemetryDisabled;
}

/**
 * 入队一次试玩上报。
 *
 * 去重按 `(projectId, clientRunId)`：同一次试玩再入队只是**替换**成更新的快照
 * （选择只会越来越多），而不是排两条 —— 后端本来就是幂等的，同一 id 重复上报只补
 * 缺失的 seq。队列超上限时丢最旧的（旧的通常已经发过了）。
 */
export function enqueuePlaytest(
  projectId: string,
  payload: PlaytestRecordIn
): PlaytestEnqueueOutcome {
  if (telemetryDisabled) return "rejected";
  const id = payload?.run?.client_run_id ?? "";
  if (!projectId || !CLIENT_RUN_RE.test(id)) return "rejected";
  const key = `${projectId}:${id}`;
  const at = queue.findIndex((item) => item.key === key);
  if (at >= 0) {
    queue[at] = { projectId, payload, key };
    return "merged";
  }
  if (queue.length >= QUEUE_LIMIT) queue.shift();
  queue.push({ projectId, payload, key });
  return "added";
}

/**
 * 把队列里的上报批量发出去（默认一次试玩只产生一条）。
 *
 * 先把队列清空再发：失败不重试、并发 flush 也不会把同一条发两次。所有 `send` 都在同
 * 一个 tick 里同步启动（含 fetch 调用），所以页面隐藏时触发的 keepalive 兜底能真的
 * 把请求发出去。任何一次返回 `disabled` 就判定工程没开采集，本次会话后续全部停掉。
 */
export async function flushPlaytestQueue(
  opts: { keepalive?: boolean; send?: PlaytestSender } = {}
): Promise<PlaytestFlushOutcome> {
  const send = opts.send ?? sender;
  const batch = queue;
  queue = [];
  if (batch.length === 0) {
    return { sent: 0, failed: 0, skipped: 0, disabled: telemetryDisabled };
  }
  const keepalive = Boolean(opts.keepalive);
  const pending = batch.map((item) => {
    try {
      return Promise.resolve(send(item.projectId, item.payload, { keepalive }));
    } catch (e) {
      return Promise.reject(e);
    }
  });
  const results = await Promise.allSettled(pending);

  let sent = 0;
  let failed = 0;
  let skipped = 0;
  let disabled = false;
  for (const result of results) {
    const outcome: PlaytestSendOutcome = result.status === "fulfilled" ? result.value : "error";
    if (outcome === "ok") sent += 1;
    else if (outcome === "disabled") {
      disabled = true;
      skipped += 1;
    } else failed += 1;
  }
  if (disabled) {
    telemetryDisabled = true;
    // 没开采集时别再攒着：队列里剩余的（含 flush 期间新入队的）一并丢掉。
    skipped += queue.length;
    queue = [];
  }
  return { sent, failed, skipped, disabled };
}

/* --------------------------------------------------------------- 试玩会话 */

/** 一次试玩 = 一个会话（一个 clientRunId）。 */
export type PlaytestSession = {
  readonly projectId: string;
  readonly clientRunId: string;
  /** 记一次选择（seq 按调用顺序自动分配） */
  addChoice(choice: LocalPlaytestChoice): void;
  /** 标记到达过某一章（试玩器一次只演一章，通常只在开演时调一次） */
  markChapter(chapterId: string): void;
  /** 结束这次试玩：构造上报体 → 入队 → 立即 flush 一次（重复调用是空操作） */
  finish(opts?: PlaytestFinishOptions): void;
  /** true = 已经 finish 过 */
  readonly finished: boolean;
};

export type PlaytestFinishOptions = {
  /** 走到的结局 label（只能是 ASCII 标识符；不确定就留空，别编一个） */
  endingLabel?: string;
  /** 页面正在离开时用 true：keepalive fetch 兜底 */
  keepalive?: boolean;
  /** 注入结束时间（测试用） */
  endedAt?: string | number | Date;
};

export type PlaytestSessionOptions = {
  projectId: string;
  /** 开演时所在的章节 id */
  chapterId?: string;
  /** 注入开始时间（测试用） */
  startedAt?: string | number | Date;
  /** 注入随机源（测试用） */
  crypto?: CryptoLike | null;
};

type SessionState = {
  projectId: string;
  clientRunId: string;
  startedAt: string;
  choices: LocalPlaytestChoice[];
  chapters: Set<string>;
  finished: boolean;
};

const liveSessions = new Set<SessionState>();
let hooksInstalled = false;

function snapshot(
  state: SessionState,
  endedAt: string | number | Date | undefined,
  endingLabel?: string
) {
  return buildPlaytestRecord({
    clientRunId: state.clientRunId,
    startedAt: state.startedAt,
    endedAt: endedAt ?? "",
    chapterCount: state.chapters.size,
    endingLabel,
    choices: state.choices,
  });
}

/**
 * 页面隐藏时**先发一份快照，但不结束会话**。
 *
 * 后端幂等（同 client_run_id 重复上报只补缺失的 seq、标量只补空/取较大值），所以
 * "中途发一次、结束时再发全量"是安全的：作者切个标签页再回来接着玩，记录不会断。
 * 快照不带 ended_at —— 这次试玩确实还没结束（没回来就算"未完成"，分析里如实体现）。
 */
function snapshotLiveSessions(): void {
  let anything = false;
  for (const state of liveSessions) {
    if (state.finished) continue;
    if (enqueuePlaytest(state.projectId, snapshot(state, "").payload) !== "rejected") {
      anything = true;
    }
  }
  if (anything) void flushPlaytestQueue({ keepalive: true }).catch(() => undefined);
}

function installFlushHooks(): void {
  if (hooksInstalled) return;
  if (typeof document === "undefined" || typeof window === "undefined") return;
  hooksInstalled = true;
  const onVisibility = () => {
    if (document.visibilityState === "hidden") snapshotLiveSessions();
  };
  document.addEventListener("visibilitychange", onVisibility);
  window.addEventListener("pagehide", snapshotLiveSessions);
}

/**
 * 开始记录一次试玩。
 *
 * 返回 null 表示**不记录**：没给工程 id，或环境里没有可用的随机源（拿不到合法
 * `client_run_id`）。调用方据此静默跳过，绝不退回 `Math.random()`。
 */
export function startPlaytestSession(opts: PlaytestSessionOptions): PlaytestSession | null {
  const projectId = typeof opts?.projectId === "string" ? opts.projectId.trim() : "";
  if (!projectId) return null;
  const clientRunId = createClientRunId(
    opts.crypto === undefined ? undefined : opts.crypto
  );
  if (!clientRunId) return null;

  void loadProjectsApi().catch(() => undefined); // 预热：隐藏时的兜底能立刻发出
  installFlushHooks();

  const state: SessionState = {
    projectId,
    clientRunId,
    startedAt: isoOrEmpty(opts.startedAt ?? Date.now()) || new Date().toISOString(),
    choices: [],
    chapters: new Set<string>(),
    finished: false,
  };
  if (opts.chapterId) state.chapters.add(String(opts.chapterId).trim());
  liveSessions.add(state);

  return {
    projectId,
    clientRunId,
    get finished() {
      return state.finished;
    },
    addChoice(choice) {
      if (state.finished || !choice) return;
      if (choice.chapterId) state.chapters.add(String(choice.chapterId).trim());
      state.choices.push({
        ...choice,
        seq: choice.seq ?? state.choices.length,
      });
    },
    markChapter(chapterId) {
      if (state.finished) return;
      const id = String(chapterId ?? "").trim();
      if (id) state.chapters.add(id);
    },
    finish(finishOpts) {
      if (state.finished) return;
      state.finished = true;
      liveSessions.delete(state);
      const record = snapshot(state, finishOpts?.endedAt ?? Date.now(), finishOpts?.endingLabel);
      if (!record.clientRunId) return;
      if (enqueuePlaytest(state.projectId, record.payload) === "rejected") return;
      void flushPlaytestQueue({ keepalive: Boolean(finishOpts?.keepalive) }).catch(
        () => undefined
      );
    },
  };
}

/** 清空队列 / 关掉"已停上报"标记 / 恢复默认传输。仅测试用。 */
export function resetPlaytestTelemetry(): void {
  queue = [];
  telemetryDisabled = false;
  sender = defaultSender;
  liveSessions.clear();
}
