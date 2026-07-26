import type { Character, ScriptBlock } from "../types/vn";

export function blocksToEditable(
  blocks: ScriptBlock[],
  characters: Character[]
): string {
  return blocks
    .map((b) => {
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
          return `"${b.text}"`;
        case "dialogue": {
          const c = characters.find((x) => x.id === b.characterId);
          return `${c?.defineName ?? b.characterId} "${b.text}"`;
        }
        case "menu": {
          const head = `menu ${b.id}:`;
          const prompt = b.prompt ? `  "${b.prompt}"` : "";
          const choices = b.choices
            .map((ch) => `  "${ch.text}":\n    jump ${ch.jump ?? "start"}`)
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
    })
    .join("\n");
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
    const dialogueMatch = trimmed.match(
      /^([A-Za-z_][A-Za-z0-9_]*)\s+"(.*)"\s*$/
    );
    if (dialogueMatch) {
      blocks.push({
        type: "dialogue",
        characterId: dialogueMatch[1],
        text: dialogueMatch[2],
      });
      i += 1;
      continue;
    }
    const narrMatch = trimmed.match(/^"(.*)"\s*$/);
    if (narrMatch) {
      blocks.push({ type: "narration", text: narrMatch[1] });
      i += 1;
      continue;
    }
    if (trimmed.startsWith("menu")) {
      const menuId =
        trimmed.match(/^menu\s+([A-Za-z0-9_]+)\s*:/)?.[1] ?? `menu_${i}`;
      const choices: { text: string; jump?: string }[] = [];
      let prompt: string | undefined;
      i += 1;
      while (i < lines.length) {
        const mline = lines[i];
        if (
          mline.length > 0 &&
          !mline.startsWith(" ") &&
          !mline.startsWith("\t")
        ) {
          break;
        }
        const mt = mline.trim();
        if (!mt) {
          i += 1;
          continue;
        }
        const p = mt.match(/^"(.*)"\s*$/);
        if (p && !choices.length && !prompt) {
          prompt = p[1];
          i += 1;
          continue;
        }
        const c = mt.match(/^"(.*)"\s*:/);
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
              (nested.length > 0 &&
                !nested.startsWith(" ") &&
                !nested.startsWith("\t"))
            ) {
              break;
            }
            i += 1;
          }
          choices.push({ text: c[1], jump });
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
  return blocks.length
    ? blocks
    : [{ type: "label", id: "start", name: "start" }];
}
