import type { Character, ScriptBlock } from "../types/vn";

/** FNV-1a-ish fingerprint so we can tell if prose drifted after RPY generate. */
export function proseFingerprint(text: string): string {
  const s = text.replace(/\r\n/g, "\n").trim();
  let h = 2166136261;
  for (let i = 0; i < s.length; i++) {
    h ^= s.charCodeAt(i);
    h = Math.imul(h, 16777619);
  }
  return (h >>> 0).toString(16);
}

function who(characters: Character[], characterId: string): string {
  const c = characters.find((x) => x.id === characterId);
  return c?.displayName || c?.defineName || characterId;
}

function walk(blocks: ScriptBlock[], characters: Character[], out: string[]): void {
  for (const b of blocks) {
    switch (b.type) {
      case "scene":
        out.push(`[场景：${b.image}]`);
        break;
      case "show":
        out.push(`[出现：${b.image}]`);
        break;
      case "hide":
        out.push(`[消失：${b.image}]`);
        break;
      case "narration":
        if (b.text.trim()) out.push(b.text.trim());
        break;
      case "dialogue":
        if (b.text.trim()) out.push(`${who(characters, b.characterId)}：${b.text.trim()}`);
        break;
      case "menu": {
        if (b.prompt?.trim()) out.push(`选项：${b.prompt.trim()}`);
        for (const ch of b.choices) {
          if (ch.text.trim()) out.push(`- ${ch.text.trim()}`);
          if (ch.blocks?.length) walk(ch.blocks, characters, out);
        }
        break;
      }
      case "raw":
        if (b.code.trim()) out.push(b.code.trim());
        break;
      default:
        break;
    }
  }
}

/** Readable manuscript from structured blocks (seed empty prose). */
export function blocksToProse(
  blocks: ScriptBlock[] | undefined,
  characters: Character[]
): string {
  const out: string[] = [];
  walk(blocks ?? [], characters, out);
  return out.join("\n\n");
}

/** 存盘正文档（可空）。可编辑区只应填这个，不要回落 blocks。 */
export function storedProse(
  chapter: { prose?: string } | undefined
): string {
  if (!chapter) return "";
  return chapter.prose || "";
}

/** 脚本档投影成可读稿（供只读「脚本预览」；禁止无感写进 prose）。 */
export function scriptPreview(
  chapter: { blocks?: ScriptBlock[] } | undefined,
  characters: Character[]
): string {
  if (!chapter) return "";
  return blocksToProse(chapter.blocks, characters);
}

/**
 * @deprecated P4.5：生产路径请用 `storedProse` / `scriptPreview`。
 * 别名保留以免漏网 import 立刻炸；wiring 守卫禁止生产代码新调用。
 */
export function chapterProse(
  chapter: { prose?: string; blocks: ScriptBlock[] } | undefined,
  characters: Character[]
): string {
  const stored = storedProse(chapter).trim();
  if (stored) return storedProse(chapter);
  return scriptPreview(chapter, characters);
}

export function rpyIsStale(
  chapter: { prose?: string; rpyFromProseHash?: string } | undefined
): boolean {
  if (!chapter) return false;
  const prose = (chapter.prose || "").trim();
  if (!prose || !chapter.rpyFromProseHash) return false;
  return proseFingerprint(prose) !== chapter.rpyFromProseHash;
}
