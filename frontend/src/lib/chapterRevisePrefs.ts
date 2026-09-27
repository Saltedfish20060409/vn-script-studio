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
  /** 作者在方向选择器里点过的方向（**只作记录**，不再参与"这次用什么方向"的判断）。 */
  mode?: ReviseMode;
  /** Names / phrases the user asked not to touch */
  lockedNames?: string[];
  /** Soft signal: user often kept original paragraphs */
  preferKeepOriginal?: boolean;
  /** Free-form notes from short commands */
  notes?: string[];
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
 * 这次改章用什么方向。
 *
 * **规则只有一条：话里点过方向就听他的，否则一律 `follow_note`（以他的说明为准）。**
 *
 * 为什么这么简：改章方向选择器过去会在每次改章前自动弹出，逼作者在三选一里挑一个。
 * 作者的原话是"那三种很多时候并不符合我想改的，弹窗很多余"——而且那三种方向**本来就能
 * 用话直接说出来**（`agentIntent` 认「只去说明书 / 轻润 / 人味」这些词），所以弹窗只是
 * 多余的一层。现在选择器改由「选个方向」这类**显式**说法打开（见 `agentIntent` 的
 * `revise_pick`），平时不再拦人。
 *
 * 刻意**不**参与判断的两样东西（都是这次删掉的，写在注释里免得被加回来）：
 * - `prefs.mode`（上次点过的方向）：拿它当默认会把作者重新钉在某个固定方向上，
 *   而他这次想改的往往不是那一类；
 * - 「以后不再问」开关：既然默认就不问了，这个开关没有意义。
 */
export function resolveReviseMode(modeFromSpeech?: ReviseMode): ReviseMode {
  return modeFromSpeech ?? FOLLOW_NOTE_MODE;
}
