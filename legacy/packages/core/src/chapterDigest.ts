import type { Character, SceneChapter, ScriptBlock, VnProject } from "./types.js";

export interface ChapterDigest {
  chapterId: string;
  title: string;
  hash: string;
  synopsis: string;
  speakers: string[];
  /** Extractive beat summary for long-form index */
  beatSummary: string;
  openHook: string;
  closeHook: string;
}

function lineFromBlock(
  b: ScriptBlock,
  charMap: Map<string, Character>
): string | null {
  switch (b.type) {
    case "narration":
      return `旁白: ${b.text}`;
    case "dialogue": {
      const name = charMap.get(b.characterId)?.displayName ?? b.characterId;
      return `${name}: ${b.text}`;
    }
    case "menu":
      return `选项: ${b.choices.map((c) => c.text).join(" / ")}`;
    case "raw":
      return b.code.trim() ? b.code : null;
    case "scene":
      return `[scene ${b.image}]`;
    case "label":
      return `[label ${b.name}]`;
    default:
      return null;
  }
}

function collectLines(
  chapter: SceneChapter,
  characters: Character[]
): { lines: string[]; speakers: string[] } {
  const map = new Map(characters.map((c) => [c.id, c]));
  const lines: string[] = [];
  const speakers = new Set<string>();
  for (const b of chapter.blocks) {
    if (b.type === "dialogue") {
      const name = map.get(b.characterId)?.displayName ?? b.characterId;
      speakers.add(name);
    }
    const line = lineFromBlock(b, map);
    if (line) lines.push(line);
  }
  return { lines, speakers: [...speakers] };
}

/** Cheap content fingerprint for cache invalidation */
export function chapterContentHash(chapter: SceneChapter): string {
  const n = chapter.blocks.length;
  const tail = chapter.blocks
    .slice(-3)
    .map((b) => JSON.stringify(b))
    .join("|");
  const syn = chapter.synopsis ?? "";
  return `${chapter.id}:${n}:${syn.length}:${hashStr(tail + syn + chapter.title)}`;
}

function hashStr(s: string): string {
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return (h >>> 0).toString(36);
}

/**
 * Local extractive chapter digest — no server / no LLM.
 * Uses synopsis + open/close hooks + speaker list.
 */
export function makeChapterDigest(
  chapter: SceneChapter,
  characters: Character[]
): ChapterDigest {
  const { lines, speakers } = collectLines(chapter, characters);
  const open = lines.slice(0, 3).join(" / ");
  const close = lines.slice(-4).join(" / ");
  const beatParts = [
    chapter.synopsis?.trim() || "",
    speakers.length ? `出场: ${speakers.join("、")}` : "",
    open ? `起: ${clip(open, 160)}` : "",
    close && close !== open ? `迄: ${clip(close, 200)}` : "",
  ].filter(Boolean);

  return {
    chapterId: chapter.id,
    title: chapter.title,
    hash: chapterContentHash(chapter),
    synopsis: chapter.synopsis?.trim() || "",
    speakers,
    beatSummary: beatParts.join(" · ") || "（空章）",
    openHook: clip(open, 120),
    closeHook: clip(close, 160),
  };
}

export function digestAllChapters(project: VnProject): ChapterDigest[] {
  return project.chapters.map((ch) =>
    makeChapterDigest(ch, project.characters)
  );
}

function clip(s: string, n: number): string {
  const t = s.replace(/\s+/g, " ").trim();
  if (t.length <= n) return t;
  return `${t.slice(0, n - 1)}…`;
}

function scoreText(hay: string, tokens: string[]): number {
  if (!tokens.length || !hay) return 0;
  const h = hay.toLowerCase();
  let s = 0;
  for (const tok of tokens) {
    if (h.includes(tok.toLowerCase())) s += tok.length >= 3 ? 3 : 2;
  }
  return s;
}

/** Format other-chapter digests for Agent context (prefer digest over raw dump). */
export function formatChapterDigestIndex(
  digests: ChapterDigest[],
  opts: {
    focusId?: string;
    tokens?: string[];
    /** include extractive body for high-score chapters */
    maxRelatedExcerpts?: number;
  } = {}
): { indexLines: string[]; relatedBlocks: string[]; included: string[] } {
  const tokens = opts.tokens ?? [];
  const included: string[] = [`章摘要×${digests.length}`];
  const indexLines = digests.map((d, i) => {
    const mark = d.chapterId === opts.focusId ? "◀当前" : "";
    return `${i + 1}. ${d.title}${mark} — ${clip(d.beatSummary, 100)}`;
  });

  const ranked = digests
    .filter((d) => d.chapterId !== opts.focusId)
    .map((d) => ({
      d,
      score: scoreText(
        `${d.title} ${d.synopsis} ${d.beatSummary} ${d.speakers.join(" ")}`,
        tokens
      ),
    }))
    .sort((a, b) => b.score - a.score);

  const relatedBlocks: string[] = [];
  const maxEx = opts.maxRelatedExcerpts ?? 3;
  let excerpted = 0;
  for (const { d, score } of ranked) {
    if (score >= 4 && excerpted < maxEx) {
      relatedBlocks.push(
        `### ${d.title}（摘要 score=${score}）\n${d.beatSummary}\n迄钩子: ${d.closeHook || "（无）"}`
      );
      included.push(`摘要章:${d.title}`);
      excerpted++;
    } else {
      relatedBlocks.push(`### ${d.title}\n${clip(d.beatSummary, 140)}`);
    }
  }

  return { indexLines, relatedBlocks, included };
}
