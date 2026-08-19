import { normalizeMapStyle } from "./mapCatalog";
import type { StoryBible, VnProject } from "../types/vn";

export function uid(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
}

/**
 * Client-side project normalization — ensures required fields exist so the
 * UI never crashes on partially-loaded server payloads. The server performs
 * the authoritative normalization; this is just a defensive mirror.
 */
export function normalizeProject(
  raw: Partial<VnProject> & { title?: string }
): VnProject {
  const bible: StoryBible = {
    world: raw.bible?.world ?? raw.lore ?? "",
    background: raw.bible?.background ?? "",
    outline: raw.bible?.outline ?? "",
    themes: raw.bible?.themes ?? "",
    notes: raw.bible?.notes ?? "",
  };

  return {
    id: raw.id || uid("proj"),
    title: raw.title || "未命名剧本",
    logline: raw.logline,
    genre: raw.genre,
    characters: raw.characters ?? [],
    chapters:
      raw.chapters && raw.chapters.length > 0
        ? raw.chapters
        : [
            {
              id: "ch1",
              title: "第一章",
              prose: "",
              blocks: [{ type: "label", id: "start", name: "start" }],
            },
          ],
    lore: bible.world,
    bible,
    locations: raw.locations ?? [],
    locationLinks: raw.locationLinks ?? [],
    mapStyle: normalizeMapStyle(raw.mapStyle),
    customMapElements: raw.customMapElements ?? [],
    mapStrokes: raw.mapStrokes ?? [],
    characterLinks: raw.characterLinks ?? [],
    timeline: raw.timeline ?? [],
    variables: raw.variables ?? [],
    sprites: raw.sprites ?? [],
    snapshots: raw.snapshots ?? [],
    chapterIndex: raw.chapterIndex,
    writingLedger: raw.writingLedger,
    harnessRuns: raw.harnessRuns,
    writingMentors: raw.writingMentors,
    authorLenses: raw.authorLenses,
    analysisMeta: raw.analysisMeta,
    voiceReports: raw.voiceReports,
    shareId: raw.shareId,
    updatedAt: raw.updatedAt || new Date().toISOString(),
  };
}

export function emptyProject(title: string): VnProject {
  return normalizeProject({ id: uid("proj"), title, chapters: [] });
}

/** Very small plain-text → chapter importer for client-side previews. */
export function projectFromPlainText(title: string, text: string): VnProject {
  const paragraphs = text
    .replace(/\r\n/g, "\n")
    .split(/\n{2,}/)
    .map((p) => p.trim())
    .filter(Boolean);
  const blocks = paragraphs.length
    ? paragraphs.map((p) => ({ type: "narration" as const, text: p }))
    : [{ type: "narration" as const, text: text.trim() }];
  return normalizeProject({
    id: uid("proj"),
    title,
    chapters: [
      {
        id: "ch1",
        title: "第一章",
        prose: text,
        blocks: [{ type: "label", id: "start", name: "start" }, ...blocks],
      },
    ],
  });
}
