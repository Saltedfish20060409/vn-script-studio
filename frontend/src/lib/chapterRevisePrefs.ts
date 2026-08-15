/** Per-chapter revise preferences (local, UX-facing). */

export type ReviseMode = "cut_lecture" | "human_warmth" | "light_touch";

export type ChapterRevisePrefs = {
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
