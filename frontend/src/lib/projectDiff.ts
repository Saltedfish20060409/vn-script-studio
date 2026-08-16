import type { VnProject } from "../types/vn";

/** Top-level fields the frontend edits directly (server-side merge whitelist). */
const SECTION_KEYS = [
  "title",
  "logline",
  "genre",
  "characters",
  "lore",
  "bible",
  "locations",
  "locationLinks",
  "mapStyle",
  "customMapElements",
  "mapStrokes",
  "characterLinks",
  "timeline",
  "variables",
  "sprites",
] as const;

export type ProjectDiff = {
  /** Chapters whose content differs from the last-known server version. */
  chapterIds: string[];
  /** Non-chapter top-level fields that differ. */
  sections: string[];
  /**
   * True when anything changed. When true but both lists are empty, the caller
   * should fall back to a full-save (no reliable base snapshot).
   */
  hasChanges: boolean;
};

/**
 * Diff the current project against the last snapshot that was persisted on the
 * server. Used for collaboration stage B chapter-scoped saves: the client only
 * declares the chapters / sections it actually modified, so concurrent edits
 * to other chapters survive on the server.
 *
 * JSON serialization is the comparison basis — the project model is normalized
 * on both ends, so field order is stable.
 */
export function diffProjectAgainst(
  base: VnProject | null,
  next: VnProject
): ProjectDiff {
  if (!base || base.id !== next.id) {
    // No trustworthy base — let the caller do a full save.
    return { chapterIds: [], sections: [], hasChanges: true };
  }

  const chapterIds: string[] = [];
  const baseCh = new Map(base.chapters.map((c) => [c.id, c]));
  const nextCh = new Map(next.chapters.map((c) => [c.id, c]));

  for (const [id, bc] of baseCh) {
    const nc = nextCh.get(id);
    if (!nc || JSON.stringify(bc) !== JSON.stringify(nc)) chapterIds.push(id);
  }
  for (const [id] of nextCh) {
    if (!baseCh.has(id)) chapterIds.push(id);
  }

  const sections: string[] = [];
  const baseRecord = base as unknown as Record<string, unknown>;
  const nextRecord = next as unknown as Record<string, unknown>;
  for (const key of SECTION_KEYS) {
    const b = baseRecord[key] ?? null;
    const n = nextRecord[key] ?? null;
    if (JSON.stringify(b) !== JSON.stringify(n)) sections.push(key);
  }

  return { chapterIds, sections, hasChanges: chapterIds.length > 0 || sections.length > 0 };
}
