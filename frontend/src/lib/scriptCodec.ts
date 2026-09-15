import type { Character, IfBranch, MenuChoice, ScriptBlock } from "../types/vn";

function escapeQuote(text: string): string {
  return text.replace(/\\/g, "\\\\").replace(/"/g, '\\"');
}

function unescapeQuote(text: string): string {
  return text.replace(/\\"/g, '"').replace(/\\\\/g, "\\");
}

/** Indent every line of a chunk by `spaces` (used for nested menu bodies). */
function indentBlock(chunk: string, spaces: number): string {
  const pad = " ".repeat(spaces);
  return chunk
    .split("\n")
    .map((l) => (l ? pad + l : l))
    .join("\n");
}

function num(value: unknown): string | null {
  if (value === undefined || value === null || value === "") return null;
  const n = typeof value === "number" ? value : Number(value);
  if (!Number.isFinite(n)) return null;
  return String(n);
}

/** 变量赋值右侧的渲染：数字/布尔裸写，字符串带引号。 */
function literal(value: unknown): string {
  if (typeof value === "boolean") return value ? "true" : "false";
  if (typeof value === "number") return String(value);
  const text = String(value ?? "").trim();
  if (!text) return "0";
  if (/^-?\d+(?:\.\d+)?$/.test(text)) return text;
  if (text === "true" || text === "false") return text;
  return `"${escapeQuote(text)}"`;
}

function parseLiteral(raw: string): number | boolean | string {
  const t = raw.trim();
  if (!t) return 0;
  if (t === "true") return true;
  if (t === "false") return false;
  if (/^-?\d+(?:\.\d+)?$/.test(t)) return Number(t);
  const q = t.match(/^"((?:\\.|[^"\\])*)"$/);
  if (q) return unescapeQuote(q[1]);
  return t;
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
    case "music": {
      const fade = num(b.fade);
      if (b.action === "stop") return `stop music${fade ? ` fadeout ${fade}` : ""}`;
      return `play music ${b.file || ""}${fade ? ` fadein ${fade}` : ""}`.trim();
    }
    case "sound": {
      const vol = num(b.volume);
      if (b.action === "stop") return "stop sound";
      return `play sound ${b.file || ""}${vol ? ` volume ${vol}` : ""}`.trim();
    }
    case "voice":
      return b.action === "stop" ? "stop voice" : `voice ${b.file || ""}`.trim();
    case "wait": {
      const s = num(b.seconds);
      return s ? `wait ${s}` : "wait";
    }
    case "camera": {
      if (b.at) return `camera at ${b.at}`;
      const parts = ["camera"];
      const zoom = num(b.zoom);
      const x = num(b.x);
      const y = num(b.y);
      if (zoom) parts.push(`zoom ${zoom}`);
      if (x) parts.push(`x ${x}`);
      if (y) parts.push(`y ${y}`);
      return parts.join(" ");
    }
    case "effect": {
      const d = num(b.duration);
      return `effect ${b.kind}${d ? ` ${d}` : ""}`.trim();
    }
    case "set":
      return `set ${b.key} ${b.op || "="} ${literal(b.value)}`;
    case "if": {
      const head: string[] = [];
      b.branches.forEach((branch, i) => {
        const cond = (branch.condition || "").trim();
        const keyword = i === 0 ? "if" : cond ? "elif" : "else";
        head.push(`${keyword}${cond ? ` ${cond}` : ""}:`);
        const body = branch.blocks
          .map((nb) => indentBlock(blockToEditableChunk(nb, characters), 4))
          .join("\n");
        head.push(body || "    pass");
      });
      return head.join("\n");
    }
    case "menu": {
      // `menu menu:` is broken output: id "menu" is the parser's sentinel for
      // "no explicit id", so render it as a bare `menu:`.
      const label = b.id && b.id !== "menu" ? ` ${b.id}` : "";
      const head = `menu${label}:`;
      const prompt = b.prompt ? `  "${escapeQuote(b.prompt)}"` : "";
      const choices = b.choices
        .map((ch) => {
          const cond = (ch.condition || "").trim();
          const decl = `  "${escapeQuote(ch.text)}"${cond ? ` if ${cond}` : ""}:`;
          // A choice with no jump target must NOT be rendered as `jump start`
          // (that fabricates a self-loop out of a linear fallback menu).
          let body: string;
          if (ch.jump) {
            body = `    jump ${ch.jump}`;
          } else if (ch.blocks?.length) {
            body = ch.blocks
              .map((nb) => indentBlock(blockToEditableChunk(nb, characters), 4))
              .join("\n");
          } else {
            body = "    pass";
          }
          return `${decl}\n${body}`;
        })
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

const QUOTED = String.raw`(?:\\.|[^"\\])*`;

function indentOf(line: string): number {
  const m = line.match(/^[ \t]*/);
  return m ? m[0].replace(/\t/g, "    ").length : 0;
}

/** 把一行渲染成块；不认识的语法回落成 raw（保持原有的"作者可写任意 Ren'Py"能力）。 */
function parseLine(trimmed: string, raw: string, characters: Character[]): ScriptBlock {
  if (trimmed.startsWith("#")) {
    return { type: "comment", text: trimmed.slice(1).trim() };
  }
  const labelMatch = trimmed.match(/^label\s+([A-Za-z0-9_]+)\s*:/);
  if (labelMatch) return { type: "label", id: labelMatch[1], name: labelMatch[1] };

  const sceneMatch = trimmed.match(/^scene\s+(.+?)(?:\s+with\s+(\S+))?$/);
  if (sceneMatch) {
    return {
      type: "scene",
      image: sceneMatch[1].trim(),
      transition: sceneMatch[2],
    };
  }
  const showMatch = trimmed.match(/^show\s+(.+?)(?:\s+at\s+(\S+))?$/);
  if (showMatch) {
    return { type: "show", image: showMatch[1].trim(), at: showMatch[2] };
  }
  if (trimmed.startsWith("hide ")) {
    return { type: "hide", image: trimmed.slice(5).trim() };
  }

  // ---- 音频指令 ----
  const playMatch = trimmed.match(
    /^play\s+(music|sound)\s+(\S+)(?:\s+(fadein|volume)\s+([\d.]+))?$/
  );
  if (playMatch) {
    const [, channel, file, opt, optVal] = playMatch;
    if (channel === "music") {
      return {
        type: "music",
        action: "play",
        file,
        fade: opt === "fadein" ? Number(optVal) : undefined,
      };
    }
    return {
      type: "sound",
      action: "play",
      file,
      volume: opt === "volume" ? Number(optVal) : undefined,
    };
  }
  const stopMatch = trimmed.match(/^stop\s+(music|sound|voice)(?:\s+fadeout\s+([\d.]+))?$/);
  if (stopMatch) {
    const [, channel, fade] = stopMatch;
    if (channel === "music") {
      return { type: "music", action: "stop", fade: fade ? Number(fade) : undefined };
    }
    if (channel === "sound") return { type: "sound", action: "stop" };
    return { type: "voice", action: "stop" };
  }
  const voiceMatch = trimmed.match(/^voice\s+(\S+)$/);
  if (voiceMatch) return { type: "voice", action: "play", file: voiceMatch[1] };

  // ---- 等待 / 镜头 / 特效 ----
  const waitMatch = trimmed.match(/^wait(?:\s+([\d.]+))?$/);
  if (waitMatch) {
    return { type: "wait", seconds: waitMatch[1] ? Number(waitMatch[1]) : undefined };
  }
  const cameraAtMatch = trimmed.match(/^camera\s+at\s+(\S+)$/);
  if (cameraAtMatch) return { type: "camera", at: cameraAtMatch[1] };
  if (trimmed === "camera" || trimmed.startsWith("camera ")) {
    const zoom = trimmed.match(/\bzoom\s+(-?[\d.]+)/)?.[1];
    const x = trimmed.match(/(?:^|\s)x\s+(-?[\d.]+)/)?.[1];
    const y = trimmed.match(/(?:^|\s)y\s+(-?[\d.]+)/)?.[1];
    return {
      type: "camera",
      zoom: zoom !== undefined ? Number(zoom) : undefined,
      x: x !== undefined ? Number(x) : undefined,
      y: y !== undefined ? Number(y) : undefined,
    };
  }
  const effectMatch = trimmed.match(/^effect\s+([A-Za-z_]+)(?:\s+([\d.]+))?$/);
  if (effectMatch) {
    return {
      type: "effect",
      kind: effectMatch[1],
      duration: effectMatch[2] ? Number(effectMatch[2]) : undefined,
    };
  }

  // ---- 变量赋值 ----
  const setMatch = trimmed.match(/^set\s+([A-Za-z_][A-Za-z0-9_]*)\s*(\+=|-=|=)\s*(.+)$/);
  if (setMatch) {
    return {
      type: "set",
      key: setMatch[1],
      op: setMatch[2] as "=" | "+=" | "-=",
      value: parseLiteral(setMatch[3]),
    };
  }

  if (trimmed.startsWith("jump ")) {
    return { type: "jump", target: trimmed.slice(5).trim() };
  }
  if (trimmed === "return") return { type: "return" };

  const dialogueMatch = trimmed.match(
    new RegExp(`^([A-Za-z_][A-Za-z0-9_]*)\\s+"(${QUOTED})"\\s*$`)
  );
  if (dialogueMatch) {
    return {
      type: "dialogue",
      characterId: dialogueMatch[1],
      text: unescapeQuote(dialogueMatch[2]),
    };
  }
  const narrMatch = trimmed.match(new RegExp(`^"(${QUOTED})"\\s*$`));
  if (narrMatch) {
    return { type: "narration", text: unescapeQuote(narrMatch[1]) };
  }
  void characters;
  return { type: "raw", code: raw };
}

/**
 * 解析一段行（含缩进语义）。`baseIndent` 之下、缩进小于它的第一行即结束。
 * 支持嵌套：menu 选项正文、if/elif/else 分支。
 */
function parseBlocks(
  lines: string[],
  start: number,
  end: number,
  baseIndent: number,
  characters: Character[]
): { blocks: ScriptBlock[]; next: number } {
  const blocks: ScriptBlock[] = [];
  let i = start;
  while (i < end) {
    const line = lines[i];
    const trimmed = line.trim();
    if (!trimmed) {
      i += 1;
      continue;
    }
    const indent = indentOf(line);
    if (indent < baseIndent) break;
    // 注释在任何缩进下都按注释处理（作者常把注释缩进对齐代码）
    if (trimmed.startsWith("#")) {
      blocks.push({ type: "comment", text: trimmed.slice(1).trim() });
      i += 1;
      continue;
    }
    if (indent > baseIndent) {
      // 意外缩进：当作上一块的延续内容交给 raw，避免静默丢字
      blocks.push({ type: "raw", code: line });
      i += 1;
      continue;
    }

    // ---- if / elif / else 链 ----
    const ifMatch = trimmed.match(/^if\s+(.+?)\s*:\s*$/);
    if (ifMatch) {
      const branches: IfBranch[] = [];
      let keywordCond: string | undefined = ifMatch[1].trim();
      let cursor = i + 1;
      for (;;) {
        // 分支正文缩进 4 空格（与 Ren'Py 一致，也与序列化侧 indentBlock(...,4) 对齐）
        const parsed = parseBlocks(lines, cursor, end, baseIndent + 4, characters);
        branches.push({ condition: keywordCond, blocks: parsed.blocks });
        cursor = parsed.next;
        // 连续空行跳过后再看是否是 elif/else
        let probe = cursor;
        while (probe < end && !lines[probe].trim()) probe += 1;
        if (probe >= end || indentOf(lines[probe]) !== baseIndent) break;
        const nextTrim = lines[probe].trim();
        const elif = nextTrim.match(/^elif\s+(.+?)\s*:\s*$/);
        if (elif) {
          keywordCond = elif[1].trim();
          cursor = probe + 1;
          continue;
        }
        if (/^else\s*:\s*$/.test(nextTrim)) {
          keywordCond = undefined;
          cursor = probe + 1;
          continue;
        }
        break;
      }
      blocks.push({ type: "if", branches });
      // 收尾时跳过 if 链后面的空行由外层继续处理
      i = cursor;
      continue;
    }
    if (/^elif\b/.test(trimmed) || /^else\s*:\s*$/.test(trimmed)) {
      // 没有配对的 if（作者误写）：保留原样，别把内容吞掉
      blocks.push({ type: "raw", code: line });
      i += 1;
      continue;
    }

    // ---- menu ----
    if (trimmed.startsWith("menu")) {
      // id "menu" is the shared sentinel for "no explicit id" (matches the
      // backend parser), so a bare `menu:` round-trips as `menu:` again —
      // never as `menu menu:` or a synthetic `menu_<n>:`.
      const menuId = trimmed.match(/^menu\s+([A-Za-z0-9_]+)\s*:/)?.[1] ?? "menu";
      const choices: MenuChoice[] = [];
      let prompt: string | undefined;
      let cursor = i + 1;
      const choiceIndent = baseIndent + 2;
      while (cursor < end) {
        const mline = lines[cursor];
        const mtrim = mline.trim();
        if (!mtrim) {
          cursor += 1;
          continue;
        }
        const mIndent = indentOf(mline);
        if (mIndent < choiceIndent) break;
        // 选项声明："文本" [if 条件]:
        const decl = mtrim.match(
          new RegExp(`^"(${QUOTED})"\\s*(?:if\\s+(.+?))?\\s*:\\s*$`)
        );
        if (!decl) {
          // 还没出现选项时的裸字符串 = 菜单提示语
          const p = mtrim.match(new RegExp(`^"(${QUOTED})"\\s*$`));
          if (p && !choices.length && !prompt) {
            prompt = unescapeQuote(p[1]);
            cursor += 1;
            continue;
          }
          cursor += 1;
          continue;
        }
        const condition = decl[2] ? decl[2].trim() : undefined;
        const parsed = parseBlocks(lines, cursor + 1, end, choiceIndent + 2, characters);
        cursor = parsed.next;
        // 选项正文里的单个 `jump X` 仍然折叠成 jump 目标（保持既有导出行为）
        const bodyBlocks = parsed.blocks;
        if (
          bodyBlocks.length === 1 &&
          bodyBlocks[0].type === "jump" &&
          !condition
        ) {
          choices.push({ text: unescapeQuote(decl[1]), jump: bodyBlocks[0].target });
        } else if (bodyBlocks.length === 1 && bodyBlocks[0].type === "raw" && bodyBlocks[0].code.trim() === "pass") {
          choices.push({
            text: unescapeQuote(decl[1]),
            ...(condition ? { condition } : {}),
          });
        } else if (bodyBlocks.length === 1 && bodyBlocks[0].type === "jump") {
          choices.push({
            text: unescapeQuote(decl[1]),
            jump: bodyBlocks[0].target,
            ...(condition ? { condition } : {}),
          });
        } else {
          choices.push({
            text: unescapeQuote(decl[1]),
            ...(condition ? { condition } : {}),
            ...(bodyBlocks.length ? { blocks: bodyBlocks } : {}),
          });
        }
      }
      blocks.push({ type: "menu", id: menuId, prompt, choices });
      i = cursor;
      continue;
    }

    blocks.push(parseLine(trimmed, line, characters));
    i += 1;
  }
  return { blocks, next: i };
}

export function editableToBlocks(text: string): ScriptBlock[] {
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  const { blocks } = parseBlocks(lines, 0, lines.length, 0, []);
  return blocks.length ? blocks : [{ type: "label", id: "start", name: "start" }];
}
