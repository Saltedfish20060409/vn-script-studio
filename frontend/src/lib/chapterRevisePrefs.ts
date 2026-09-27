/** Per-chapter revise preferences (local, UX-facing). */

/**
 * 改稿方向。
 *
 * 前三档是"作者没细说时的省事方向"；`follow_note` 表示**不做任何固定方向**、以作者自己的
 * 说明为准。加它是因为实测反馈：真实需求常常不落在那三类里（"很多时候并不符合说的这三种
 * 情况，所以不太有用，更多时候看 Agent 理解"），而提示词里「回炉指引」是无条件拼进去的，
 * 固定方向会跟作者的说明打架。详见 `backend/app/core/chapter_revise.py` 的 `_MODE_HINTS`。
 */
export type ReviseMode = "cut_lecture" | "human_warmth" | "light_touch" | "follow_note";

/** 「就照我说的改」：不选固定方向。 */
export const FOLLOW_NOTE_MODE: ReviseMode = "follow_note";

export type ChapterRevisePrefs = {
  mode?: ReviseMode;
  /** Names / phrases the user asked not to touch */
  lockedNames?: string[];
  /** Soft signal: user often kept original paragraphs */
  preferKeepOriginal?: boolean;
  /** Free-form notes from short commands */
  notes?: string[];
  /**
   * 作者选了「以后直接照我说的改，不再问」→ `false`。
   * 未设置（`undefined`）表示还没表态过，仍然问一次。
   */
  askMode?: boolean;
  updatedAt?: number;
};

const KEY = "vnss-chapter-revise-prefs-v1";

type Store = Record<string, Record<string, ChapterRevisePrefs>>;

function readStore(): Store {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return {};
    const data = JSON.parse(raw) as Store;
    return data && typeof data === "object" ? data : {};
  } catch {
    return {};
  }
}

function writeStore(store: Store): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(store));
  } catch {
    /* ignore */
  }
}

export function getChapterRevisePrefs(
  projectId: string,
  chapterId: string
): ChapterRevisePrefs {
  const store = readStore();
  return { ...(store[projectId]?.[chapterId] || {}) };
}

export function setChapterRevisePrefs(
  projectId: string,
  chapterId: string,
  patch: Partial<ChapterRevisePrefs>
): ChapterRevisePrefs {
  const store = readStore();
  if (!store[projectId]) store[projectId] = {};
  const next: ChapterRevisePrefs = {
    ...store[projectId][chapterId],
    ...patch,
    updatedAt: Date.now(),
  };
  if (patch.lockedNames) {
    next.lockedNames = Array.from(
      new Set(
        [...(store[projectId][chapterId]?.lockedNames || []), ...patch.lockedNames]
          .map((s) => s.trim())
          .filter(Boolean)
      )
    ).slice(0, 24);
  }
  if (patch.notes) {
    next.notes = Array.from(
      new Set(
        [...(store[projectId][chapterId]?.notes || []), ...patch.notes]
          .map((s) => s.trim())
          .filter(Boolean)
      )
    ).slice(-12);
  }
  store[projectId][chapterId] = next;
  writeStore(store);
  return next;
}

export const REVISE_MODE_OPTIONS: Array<{
  id: ReviseMode;
  title: string;
  blurb: string;
}> = [
  {
    id: "cut_lecture",
    title: "只去说明书",
    blurb: "砍问答课、导览、OS 标签；尽量保留你原来的语感。",
  },
  {
    id: "human_warmth",
    title: "加强人味",
    blurb: "去说明书，并加强毛边、对视与相处感（默认）。",
  },
  {
    id: "light_touch",
    title: "轻润不改结构",
    blurb: "只动硬伤与假选择，节拍和大段旁白尽量不动。",
  },
];

export function prefsToNoteSuffix(prefs: ChapterRevisePrefs): string {
  const bits: string[] = [];
  if (prefs.lockedNames?.length) {
    bits.push(`别动这些称呼/角色：${prefs.lockedNames.join("、")}`);
  }
  if (prefs.preferKeepOriginal) {
    bits.push("用户倾向保留原文气氛，少改大段旁白");
  }
  if (prefs.notes?.length) {
    bits.push(...prefs.notes.slice(-4));
  }
  return bits.length ? `【本章偏好】${bits.join("；")}` : "";
}

/**
 * 这次改章：**要不要问方向、以及用什么方向**。
 *
 * 抽成纯函数是因为这条规则最容易写歪，而本仓没有组件测试可用（`vitest` 只跑
 * `src/**` 下的纯函数，见 vitest.config.ts）。规则：**四个"不用问"的信号有一个成立就不问**
 * —— 调用方明确要求不问 / 作者勾过「不再问」/ 作者已在弹窗里写了说明 / 话里已点明方向；
 * 都不成立时才问一次（保留既有的"主动改章时确认一下"）。
 *
 * 方向按优先级取：话里点的 > 作者自己写的说明（或已勾不再问 → `follow_note`）> 记着的旧方向
 * > `human_warmth`。**不能拿旧方向去压他这次说的话**——那正是"三选一不太有用"的根因。
 */
export function resolveRevisePlan(input: {
  /** 从自然语言里识别出的方向（`agentIntent` 给的）。 */
  modeFromSpeech?: ReviseMode;
  /** 弹窗里作者自己写的改法。 */
  customNote?: string;
  /** 调用方已决定不问（例如「再润」走 polish 分支）。 */
  skipModePicker?: boolean;
  prefs: ChapterRevisePrefs;
}): { openPicker: boolean; mode: ReviseMode } {
  const { prefs } = input;
  const optedOut = prefs.askMode === false;
  const hasCustom = Boolean(input.customNote?.trim());
  const modeFromSpeech = input.modeFromSpeech;

  const skip =
    Boolean(input.skipModePicker) || optedOut || hasCustom || Boolean(modeFromSpeech);
  if (!skip) {
    // 问的时候 mode 用不上（由弹窗决定），这里给一个稳定值
    return { openPicker: true, mode: prefs.mode ?? "human_warmth" };
  }
  const wantsFollowNote = hasCustom || optedOut;
  const mode =
    modeFromSpeech ?? (wantsFollowNote ? FOLLOW_NOTE_MODE : prefs.mode || "human_warmth");
  return { openPicker: false, mode };
}
