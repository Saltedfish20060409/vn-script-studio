import type { Character, ScriptBlock } from "../types/vn";

function escapeQuote(text: string): string {
  return text.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
}

function unescapeQuote(text: string): string {
  return text.replace(/\\"/g, '"').replace(/\\\\/g, "\\");
}

function blockToEditableChunk(b: ScriptBlock, characters: Character[]): string {
  switch (b.type) {
    case "label":
      return `label ${b.name}:`;
    case "scene":
      return `scene ${b.image}${b.transition ? ` with ${b.transition}` : ""}`;
    case "show":
      return `show ${b.image}${b.at ? ` at ${b.at}` : ""}`;
    case "hide":
      return `hide ${b.image}`;
    case "narration":
      return `"${escapeQuote(b.text)}"`;
    case "dialogue": {
      const c = characters.find((x) => x.id === b.characterId);
      // Prefer the stable defineName when present; fall back to characterId so
      // a blanked defineName never collapses the line into a narration block.
      const who = c?.defineName || b.characterId;
      return `${who} "${escapeQuote(b.text)}"`;
    }
    case "menu": {
      const head = `menu ${b.id}:`;
      const prompt = b.prompt ? `  "${escapeQuote(b.prompt)}"` : "";
      const choices = b.choices
        .map((ch) => `  "${escapeQuote(ch.text)}":\n    jump ${ch.jump ?? "start"}`)
        .join("\n");
      return [head, prompt, choices].filter(Boolean).join("\n");
    }
    case "jump":
      return `jump ${b.target}`;
    case "return":
      return "return";
    case "comment":
      return `# ${b.text}`;
    case "raw":
      return b.code;
    default:
      return "";
  }
}

export function blocksToEditable(
  blocks: ScriptBlock[],
  characters: Character[]
): string {
  return blocks.map((b) => blockToEditableChunk(b, characters)).join("\n");
}

/** Character range of a block inside `blocksToEditable` output. */
export function blockTextRange(
  blocks: ScriptBlock[],
  characters: Character[],
  blockIndex: number
): { start: number; end: number } | null {
  if (blockIndex < 0 || blockIndex >= blocks.length) return null;
  let start = 0;
  for (let i = 0; i < blockIndex; i++) {
    start += blockToEditableChunk(blocks[i], characters).length + 1; // join('\n')
  }
  const chunk = blockToEditableChunk(blocks[blockIndex], characters);
  return { start, end: start + chunk.length };
}

export function editableToBlocks(text: string): ScriptBlock[] {
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  const blocks: ScriptBlock[] = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const trimmed = line.trim();
    if (!trimmed) {
      i += 1;
      continue;
    }
    if (trimmed.startsWith("#")) {
      blocks.push({ type: "comment", text: trimmed.slice(1).trim() });
      i += 1;
      continue;
    }
    const labelMatch = trimmed.match(/^label\s+([A-Za-z0-9_]+)\s*:/);
    if (labelMatch) {
      blocks.push({ type: "label", id: labelMatch[1], name: labelMatch[1] });
      i += 1;
      continue;
    }
    const sceneMatch = trimmed.match(/^scene\s+(.+?)(?:\s+with\s+(\S+))?$/);
    if (sceneMatch) {
      blocks.push({
        type: "scene",
        image: sceneMatch[1].trim(),
        transition: sceneMatch[2],
      });
      i += 1;
      continue;
    }
    const showMatch = trimmed.match(/^show\s+(.+?)(?:\s+at\s+(\S+))?$/);
    if (showMatch) {
      blocks.push({
        type: "show",
        image: showMatch[1].trim(),
        at: showMatch[2],
      });
      i += 1;
      continue;
    }
    if (trimmed.startsWith("hide ")) {
      blocks.push({ type: "hide", image: trimmed.slice(5).trim() });
      i += 1;
      continue;
    }
    if (trimmed.startsWith("jump ")) {
      blocks.push({ type: "jump", target: trimmed.slice(5).trim() });
      i += 1;
      continue;
    }
    if (trimmed === "return") {
      blocks.push({ type: "return" });
      i += 1;
      continue;
    }
    // Match a quoted string allowing escaped quotes inside: "...\"...".
    const quoted = String.raw`(?:\\.|[^"\\])*`;
    const dialogueMatch = trimmed.match(
      new RegExp(`^([A-Za-z_][A-Za-z0-9_]*)\\s+"(${quoted})"\\s*$`)
    );
    if (dialogueMatch) {
      blocks.push({
        type: "dialogue",
        characterId: dialogueMatch[1],
        text: unescapeQuote(dialogueMatch[2]),
      });
      i += 1;
      continue;
    }
    const narrMatch = trimmed.match(new RegExp(`^"(${quoted})"\\s*$`));
    if (narrMatch) {
      blocks.push({ type: "narration", text: unescapeQuote(narrMatch[1]) });
      i += 1;
      continue;
    }
    if (trimmed.startsWith("menu")) {
      const menuId = trimmed.match(/^menu\s+([A-Za-z0-9_]+)\s*:/)?.[1] ?? `menu_${i}`;
      const choices: { text: string; jump?: string }[] = [];
      let prompt: string | undefined;
      i += 1;
      while (i < lines.length) {
        const mline = lines[i];
        if (mline.length > 0 && !mline.startsWith(" ") && !mline.startsWith("\t")) {
          break;
        }
        const mt = mline.trim();
        if (!mt) {
          i += 1;
          continue;
        }
        const p = mt.match(new RegExp(`^"(${quoted})"\\s*$`));
        if (p && !choices.length && !prompt) {
          prompt = unescapeQuote(p[1]);
          i += 1;
          continue;
        }
        const c = mt.match(new RegExp(`^"(${quoted})"\\s*:`));
        if (c) {
          let jump: string | undefined;
          i += 1;
          while (i < lines.length) {
            const nested = lines[i];
            if (nested.trim().startsWith("jump ")) {
              jump = nested.trim().slice(5).trim();
              i += 1;
              break;
            }
            if (
              nested.trim().startsWith('"') ||
              (nested.length > 0 && !nested.startsWith(" ") && !nested.startsWith("\t"))
            ) {
              break;
            }
            i += 1;
          }
          choices.push({ text: unescapeQuote(c[1]), jump });
          continue;
        }
        i += 1;
      }
      blocks.push({ type: "menu", id: menuId, prompt, choices });
      continue;
    }
    blocks.push({ type: "raw", code: line });
    i += 1;
  }
  return blocks.length ? blocks : [{ type: "label", id: "start", name: "start" }];
}
