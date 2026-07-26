import type { AgentChatMessage } from "./types.js";

/** Split Story Bible outline into beat lines */
export function parseOutlineBeats(outline: string): string[] {
  if (!outline?.trim()) return [];
  return outline
    .replace(/\r\n/g, "\n")
    .split("\n")
    .map((l) => l.replace(/^[\s\-*\d.、)）]+/, "").trim())
    .filter((l) => l.length >= 4);
}

function scoreBeat(beat: string, tokens: string[]): number {
  if (!tokens.length) return 0;
  const h = beat.toLowerCase();
  let s = 0;
  for (const tok of tokens) {
    if (h.includes(tok.toLowerCase())) s += tok.length >= 2 ? 2 : 1;
  }
  return s;
}

/** Pick outline beats relevant to the user ask / selection */
export function selectOutlineBeats(
  outline: string | undefined,
  tokens: string[],
  max = 5
): string[] {
  const beats = parseOutlineBeats(outline ?? "");
  if (!beats.length) return [];
  if (!tokens.length) return beats.slice(0, Math.min(3, max));
  return beats
    .map((b) => ({ b, score: scoreBeat(b, tokens) }))
    .filter((x) => x.score > 0)
    .sort((a, b) => b.score - a.score)
    .slice(0, max)
    .map((x) => x.b);
}

export interface ChatMemoryBundle {
  /** Compressed older turns for system context */
  memoryBlock: string;
  /** Recent turns to send as chat messages */
  recentMessages: AgentChatMessage[];
  summarizedCount: number;
}

const DEFAULT_KEEP = 16;
const SUMMARIZE_AFTER = 22;

/**
 * Extractive rolling chat memory — no LLM.
 * Older turns become short bullets; recent stay verbatim for the API.
 */
export function compressChatHistory(
  messages: AgentChatMessage[],
  opts?: { keepRecent?: number; summarizeAfter?: number; priorMemory?: string }
): ChatMemoryBundle {
  const keep = opts?.keepRecent ?? DEFAULT_KEEP;
  const threshold = opts?.summarizeAfter ?? SUMMARIZE_AFTER;
  const usable = messages.filter(
    (m) => m.role === "user" || m.role === "assistant"
  );

  if (usable.length <= threshold) {
    return {
      memoryBlock: opts?.priorMemory?.trim() || "",
      recentMessages: usable.slice(-keep),
      summarizedCount: 0,
    };
  }

  const older = usable.slice(0, Math.max(0, usable.length - keep));
  const recent = usable.slice(-keep);
  const bullets = older.map((m, i) => {
    const role = m.role === "user" ? "你" : "编辑";
    const text = m.content.replace(/\s+/g, " ").trim().slice(0, 100);
    return `${i + 1}. [${role}] ${text}${m.content.length > 100 ? "…" : ""}`;
  });

  const prior = opts?.priorMemory?.trim();
  const memoryBlock = [
    prior ? `（既有记忆）\n${prior}` : "",
    `（更早对话节选 ×${bullets.length}）\n${bullets.join("\n")}`,
  ]
    .filter(Boolean)
    .join("\n\n");

  return {
    memoryBlock: memoryBlock.slice(0, 3500),
    recentMessages: recent,
    summarizedCount: older.length,
  };
}
