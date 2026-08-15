import type { Location, SceneChapter, ScriptBlock } from "../types/vn";

export type OccurrenceHitKind = "scene" | "text";

export interface LocationOccurrenceHit {
  blockIndex: number;
  kind: OccurrenceHitKind;
  evidence: string;
}

export interface LocationChapterOccurrence {
  chapterId: string;
  chapterTitle: string;
  hits: LocationOccurrenceHit[];
}

/** Align with backend map_extract_smart._normalize_key */
export function normalizeSceneKey(s: string): string {
  return (s || "").trim().toLowerCase().replace(/\s+/g, " ");
}

function truncate(s: string, max = 48): string {
  const t = s.replace(/\s+/g, " ").trim();
  if (t.length <= max) return t;
  return `${t.slice(0, max - 1)}…`;
}

function textNeedles(loc: Location): string[] {
  const out: string[] = [];
  const seen = new Set<string>();
  const push = (raw?: string) => {
    const t = (raw || "").trim();
    if (t.length < 2) return;
    const key = t.toLowerCase();
    if (seen.has(key)) return;
    seen.add(key);
    out.push(t);
  };
  push(loc.name);
  // "车站1" style place names from map UI — also probe base label
  const base = (loc.name || "").replace(/[\d\s]+$/u, "").trim();
  if (base && base !== loc.name) push(base);
  for (const tag of loc.tags || []) push(tag);
  return out;
}

function findTextNeedle(text: string, needles: string[]): string | null {
  if (!text || needles.length === 0) return null;
  for (const n of needles) {
    if (text.includes(n)) return n;
  }
  return null;
}

function scanBlock(
  block: ScriptBlock,
  blockIndex: number,
  tagKey: string,
  needles: string[]
): LocationOccurrenceHit | null {
  if (block.type === "scene" && tagKey) {
    const imgKey = normalizeSceneKey(block.image);
    if (imgKey && imgKey === tagKey) {
      return {
        blockIndex,
        kind: "scene",
        evidence: `scene ${block.image}`,
      };
    }
  }
  if (block.type === "dialogue" || block.type === "narration") {
    const hit = findTextNeedle(block.text, needles);
    if (hit) {
      return {
        blockIndex,
        kind: "text",
        evidence: truncate(block.text),
      };
    }
  }
  return null;
}

/**
 * Runtime scan: which chapters mention this location via scene imageTag
 * and/or place name / alias tags in dialogue & narration.
 */
export function findLocationOccurrences(
  location: Location,
  chapters: SceneChapter[]
): LocationChapterOccurrence[] {
  const tagKey = location.imageTag
    ? normalizeSceneKey(location.imageTag)
    : "";
  const needles = textNeedles(location);
  if (!tagKey && needles.length === 0) return [];

  const result: LocationChapterOccurrence[] = [];
  for (const ch of chapters) {
    const hits: LocationOccurrenceHit[] = [];
    ch.blocks.forEach((block, blockIndex) => {
      const hit = scanBlock(block, blockIndex, tagKey, needles);
      if (hit) hits.push(hit);
    });
    if (hits.length === 0) continue;
    result.push({
      chapterId: ch.id,
      chapterTitle: ch.title || ch.id,
      hits,
    });
  }
  return result;
}

/** Prefer first scene hit, else first text hit — for list subtitle. */
export function primaryEvidence(
  occ: LocationChapterOccurrence
): LocationOccurrenceHit {
  return occ.hits.find((h) => h.kind === "scene") ?? occ.hits[0];
}

export type PlaceNeedle = {
  text: string;
  locationId: string;
};

/** Longest-first needles for highlighting place names / scene tags in script text. */
export function buildPlaceNeedles(locations: Location[]): PlaceNeedle[] {
  const best = new Map<string, PlaceNeedle>();
  const consider = (text: string, locationId: string) => {
    const t = text.trim();
    if (t.length < 2) return;
    const key = t.toLowerCase();
    const prev = best.get(key);
    if (!prev || t.length > prev.text.length) {
      best.set(key, { text: t, locationId });
    }
  };
  for (const loc of locations) {
    for (const n of textNeedles(loc)) consider(n, loc.id);
    if (loc.imageTag?.trim()) {
      const tag = loc.imageTag.trim();
      consider(tag, loc.id);
      const bare = tag.replace(/^bg\s+/i, "").trim();
      if (bare !== tag) consider(bare, loc.id);
    }
  }
  return [...best.values()].sort((a, b) => b.text.length - a.text.length);
}

export type ScriptToken =
  | { type: "text"; value: string }
  | { type: "place"; value: string; locationId: string };

export function tokenizeScriptLine(
  line: string,
  needles: PlaceNeedle[]
): ScriptToken[] {
  if (!line) return [{ type: "text", value: "" }];
  if (needles.length === 0) return [{ type: "text", value: line }];

  const tokens: ScriptToken[] = [];
  let i = 0;
  while (i < line.length) {
    let hit: PlaceNeedle | null = null;
    for (const n of needles) {
      if (line.startsWith(n.text, i)) {
        hit = n;
        break;
      }
    }
    if (hit) {
      tokens.push({
        type: "place",
        value: hit.text,
        locationId: hit.locationId,
      });
      i += hit.text.length;
      continue;
    }
    let j = i + 1;
    while (j < line.length) {
      let starts = false;
      for (const n of needles) {
        if (line.startsWith(n.text, j)) {
          starts = true;
          break;
        }
      }
      if (starts) break;
      j += 1;
    }
    tokens.push({ type: "text", value: line.slice(i, j) });
    i = j;
  }
  return tokens;
}

/** Which place token owns this caret/click offset in full script text. */
export function placeTokenAtOffset(
  text: string,
  needles: PlaceNeedle[],
  offset: number
): Extract<ScriptToken, { type: "place" }> | null {
  const normalized = (text ?? "").replace(/\r\n/g, "\n");
  const pos = Math.max(0, Math.min(offset, normalized.length));
  const lines = normalized.split("\n");
  let cursor = 0;
  for (const line of lines) {
    const lineStart = cursor;
    const lineEnd = cursor + line.length;
    if (pos >= lineStart && pos <= lineEnd) {
      const col = pos - lineStart;
      let c = 0;
      for (const tok of tokenizeScriptLine(line, needles)) {
        const next = c + tok.value.length;
        // Strictly inside the token — trailing edge (col === next) must NOT
        // count, or clicking blank space after a lone place name jumps away.
        if (col >= c && col < next && tok.type === "place") {
          return tok;
        }
        c = next;
      }
      return null;
    }
    cursor = lineEnd + 1;
  }
  return null;
}
