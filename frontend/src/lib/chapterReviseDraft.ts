/** Persist chapter revise previews so refresh doesn't lose the对照 panel. */

export type ChapterReviseDraft = {
  chapterId: string;
  revisedText: string;
  originalText: string;
  chapterTitle?: string;
  diagnosisMd?: string;
  savedAt: number;
};

const KEY = "vnss-chapter-revise-draft-v1";
export const REVISE_DRAFT_EVENT = "vnss-revise-draft-changed";
export const OPEN_REVISE_REVIEW_EVENT = "vnss-open-revise-review";

type Store = Record<string, Record<string, ChapterReviseDraft>>;

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
    /* quota / private mode */
  }
}

function emitChanged(projectId: string, chapterId: string | null) {
  try {
    window.dispatchEvent(
      new CustomEvent(REVISE_DRAFT_EVENT, {
        detail: { projectId, chapterId },
      })
    );
  } catch {
    /* ignore */
  }
}

export function getChapterReviseDraft(
  projectId: string,
  chapterId: string
): ChapterReviseDraft | null {
  if (!projectId || !chapterId) return null;
  const d = readStore()[projectId]?.[chapterId];
  if (!d?.revisedText || !d.chapterId) return null;
  return d;
}

export function saveChapterReviseDraft(
  projectId: string,
  draft: Omit<ChapterReviseDraft, "savedAt"> & { savedAt?: number }
): ChapterReviseDraft | null {
  if (!projectId || !draft.chapterId || !(draft.revisedText || "").trim()) {
    return null;
  }
  const store = readStore();
  if (!store[projectId]) store[projectId] = {};
  const next: ChapterReviseDraft = {
    chapterId: draft.chapterId,
    revisedText: draft.revisedText,
    originalText: draft.originalText || "",
    chapterTitle: draft.chapterTitle,
    // Cap diagnosis to keep localStorage light
    diagnosisMd: (draft.diagnosisMd || "").slice(0, 8000) || undefined,
    savedAt: draft.savedAt || Date.now(),
  };
  store[projectId][draft.chapterId] = next;
  // Keep at most 8 chapter drafts per project
  const entries = Object.entries(store[projectId]).sort(
    (a, b) => (b[1].savedAt || 0) - (a[1].savedAt || 0)
  );
  if (entries.length > 8) {
    store[projectId] = Object.fromEntries(entries.slice(0, 8));
  }
  writeStore(store);
  emitChanged(projectId, draft.chapterId);
  return next;
}

export function clearChapterReviseDraft(projectId: string, chapterId: string): void {
  if (!projectId || !chapterId) return;
  const store = readStore();
  if (!store[projectId]?.[chapterId]) return;
  delete store[projectId][chapterId];
  if (store[projectId] && !Object.keys(store[projectId]).length) {
    delete store[projectId];
  }
  writeStore(store);
  emitChanged(projectId, chapterId);
}

/** Ask AgentChat to open the对照 panel for this chapter's saved draft. */
export function requestOpenReviseReview(projectId: string, chapterId: string): void {
  try {
    window.dispatchEvent(
      new CustomEvent(OPEN_REVISE_REVIEW_EVENT, {
        detail: { projectId, chapterId },
      })
    );
  } catch {
    /* ignore */
  }
}
