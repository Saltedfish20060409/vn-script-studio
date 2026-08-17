import type { ScriptBlock, VnProject } from "../types/vn";

/** One chapter's dialogue activity for a single character. */
export interface ArcChapterPoint {
  chapterId: string;
  title: string;
  /** dialogue lines by this character in this chapter (incl. menu inline blocks) */
  lines: number;
}

export interface CharacterArc {
  id: string;
  displayName: string;
  defineName: string;
  color: string;
  /** total dialogue lines across the whole novel */
  totalLines: number;
  /** chapters where the character has at least one line */
  activeChapters: number;
  chapterSeries: ArcChapterPoint[];
  /** timeline events whose title/summary mention this character */
  timelineEvents: { title: string; when: string }[];
  /** -1 when the character never speaks */
  firstSeenIndex: number;
  lastSeenIndex: number;
  /** longest run of consecutive chapters (after first appearance) with no lines */
  gapChapters: number;
}

export interface CharacterArcsResult {
  characters: CharacterArc[];
  chapters: { id: string; title: string }[];
  maxLines: number;
  totalChapters: number;
}

function countDialogue(blocks: ScriptBlock[], counts: Map<string, number>): void {
  for (const b of blocks) {
    if (b.type === "dialogue" && b.characterId) {
      counts.set(b.characterId, (counts.get(b.characterId) ?? 0) + 1);
    } else if (b.type === "menu") {
      for (const c of b.choices) {
        if (c.blocks) countDialogue(c.blocks, counts);
      }
    }
  }
}

function mentionsCharacter(text: string, names: string[]): boolean {
  const t = text.toLowerCase();
  return names.some((n) => n && t.includes(n.toLowerCase()));
}

export function computeCharacterArcs(project: VnProject): CharacterArcsResult {
  const chapters = project.chapters.map((c) => ({ id: c.id, title: c.title }));

  // per-chapter dialogue counts
  const perChapter: Map<string, Map<string, number>> = new Map();
  for (const ch of project.chapters) {
    const counts = new Map<string, number>();
    countDialogue(ch.blocks, counts);
    perChapter.set(ch.id, counts);
  }

  const timeline = project.timeline ?? [];

  const arcs: CharacterArc[] = project.characters.map((c) => {
    const series: ArcChapterPoint[] = [];
    let totalLines = 0;
    let firstSeenIndex = -1;
    let lastSeenIndex = -1;
    project.chapters.forEach((ch, i) => {
      const lines = perChapter.get(ch.id)?.get(c.id) ?? 0;
      if (lines > 0) {
        if (firstSeenIndex < 0) firstSeenIndex = i;
        lastSeenIndex = i;
      }
      totalLines += lines;
      series.push({ chapterId: ch.id, title: ch.title, lines });
    });

    // longest gap after first appearance
    let gapChapters = 0;
    if (firstSeenIndex >= 0) {
      let run = 0;
      for (let i = firstSeenIndex + 1; i < project.chapters.length; i++) {
        if (series[i].lines > 0) {
          gapChapters = Math.max(gapChapters, run);
          run = 0;
        } else {
          run += 1;
        }
      }
      gapChapters = Math.max(gapChapters, run);
    }

    const names = [c.displayName, c.defineName].filter(Boolean);
    const events = timeline
      .filter((t) => mentionsCharacter(`${t.title} ${t.summary ?? ""}`, names))
      .map((t) => ({ title: t.title, when: t.when ?? "" }));

    return {
      id: c.id,
      displayName: c.displayName,
      defineName: c.defineName,
      color: c.color ?? "#6b7280",
      totalLines,
      activeChapters: series.filter((p) => p.lines > 0).length,
      chapterSeries: series,
      timelineEvents: events,
      firstSeenIndex,
      lastSeenIndex,
      gapChapters,
    };
  });

  // order by total lines desc
  arcs.sort((a, b) => b.totalLines - a.totalLines || a.displayName.localeCompare(b.displayName));
  const maxLines = Math.max(1, ...arcs.map((a) => a.totalLines));

  return { characters: arcs, chapters, maxLines, totalChapters: chapters.length };
}
