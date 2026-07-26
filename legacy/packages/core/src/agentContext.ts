import type {
  AgentTaskKind,
  Character,
  Location,
  ScriptBlock,
  VnProject,
} from "./types.js";
import {
  digestAllChapters,
  formatChapterDigestIndex,
} from "./chapterDigest.js";
import { selectOutlineBeats } from "./longformMemory.js";

/** @deprecated Prefer AgentTaskKind from types — kept as alias for imports */
export type AgentTask = AgentTaskKind;

/** Specialized writing tasks — drives both prompt hints and retrieval bias. */
export const AGENT_TASKS: AgentTaskKind[] = [
  "chat",
  "continue",
  "rewrite",
  "polish",
  "branch",
  "outline",
  "voice",
  "consistency",
  "scene",
];

export function isAgentTask(v: unknown): v is AgentTaskKind {
  return typeof v === "string" && (AGENT_TASKS as string[]).includes(v);
}

export interface AgentContextOptions {
  chapterId?: string;
  selection?: string;
  /** Latest user utterance — used for keyword retrieval */
  userMessage?: string;
  task?: AgentTaskKind;
  /** Soft budget for the assembled context string */
  maxChars?: number;
  /** Rolling chat memory (extractive, from client) */
  chatMemory?: string;
}

export interface AgentContextResult {
  text: string;
  /** Human-readable list of what was injected (for UI transparency) */
  included: string[];
  charsUsed: number;
  task: AgentTaskKind;
}

const TASK_HINTS: Record<AgentTaskKind, string> = {
  chat: "本轮模式：自由讨论。可给方案、点评、大纲；仅当用户明确要求写入时再给 actions。设定勿当讲义复述。",
  continue:
    "本轮任务：续写一小段可上演节拍。紧接【当前章末尾】；人设只校准语气。禁止设定宣讲；禁止陌生人连问盘人（一拍一角色 ideally ≤1 问）；信息用环境/失言/残缺感推进。默认 append_script；不要重写前文。",
  rewrite:
    "本轮任务：改写选区。保持剧情意图，砍盘问串与说明书腔，提升画面感与对白张力；append_script 追加改写稿（勿 replace 整章，除非用户要求）。",
  polish:
    "本轮任务：润色。不改情节；重点砍盘问串、问答乒乓、过熟闲聊与套话，打磨对白自然度；append_script 写入。",
  branch:
    "本轮任务：有意义的分支。2～4 个 Ren'Py menu，每项后果不同；选项文案短而有戏剧性，勿在选项里塞设定说明；append_script。",
  outline:
    "本轮任务：场景大纲。规划 3～5 场（冲突/人物/钩子），用戏剧事件而非设定条目来写；先 message；同意后再 update_bible/add_chapter。",
  voice:
    "本轮任务：人设语气审校。对照 voice/bio 找破功句；改写时仍禁止设定宣讲与过熟盘问。",
  consistency:
    "本轮任务：一致性排查。列矛盾与最小改法；报告里可以引用设定，但建议写入正文时仍遵守反倾倒。",
  scene:
    "本轮任务：写完整一小场戏（进场→冲突→收束钩子）。设定溶于表演；对照社交温度与人设惜话程度，勿把冷角色写成访谈主持。append_script。",
};

export function inferAgentTask(message: string): AgentTaskKind {
  const m = message.trim();
  if (/【任务：续写】|^续写|请续写|往下写/.test(m)) return "continue";
  if (/【任务：改写】|改写选区|请改写/.test(m)) return "rewrite";
  if (/【任务：润色】|请润色/.test(m)) return "polish";
  if (/【任务：分支】|生成分支|设计分支|menu/.test(m)) return "branch";
  if (/【任务：大纲】|场景大纲|给出.*大纲/.test(m)) return "outline";
  if (/【任务：语气】|统一语气|人设一致|voice/.test(m)) return "voice";
  if (/【任务：查矛盾】|一致性|矛盾|冲突检查|状态机/.test(m))
    return "consistency";
  if (/【任务：写一场戏】|写一场戏|完整一场|一场戏/.test(m)) return "scene";
  return "chat";
}

export function taskHint(task: AgentTaskKind): string {
  return TASK_HINTS[task];
}

function blocksToPlain(blocks: ScriptBlock[], characters: Character[]): string {
  const map = new Map(characters.map((c) => [c.id, c]));
  return blocks
    .map((b) => {
      switch (b.type) {
        case "label":
          return `[label ${b.name}]`;
        case "scene":
          return `[scene ${b.image}]`;
        case "show":
          return `[show ${b.image}]`;
        case "hide":
          return `[hide ${b.image}]`;
        case "narration":
          return `旁白: ${b.text}`;
        case "dialogue": {
          const name = map.get(b.characterId)?.displayName ?? b.characterId;
          return `${name}: ${b.text}`;
        }
        case "menu":
          return `选项: ${b.choices.map((c) => c.text).join(" / ")}`;
        case "jump":
          return `[jump ${b.target}]`;
        case "comment":
          return `# ${b.text}`;
        case "raw":
          return b.code;
        default:
          return "";
      }
    })
    .filter(Boolean)
    .join("\n");
}

function tokenize(query: string): string[] {
  const lower = query.toLowerCase();
  const tokens = new Set<string>();
  for (const m of lower.matchAll(/[\u4e00-\u9fff]{2,}|[a-z0-9_]{3,}/g)) {
    const t = m[0];
    if (t.length >= 2) tokens.add(t);
    // CJK bigrams for denser matching
    if (/^[\u4e00-\u9fff]+$/.test(t) && t.length >= 3) {
      for (let i = 0; i < t.length - 1; i++) tokens.add(t.slice(i, i + 2));
    }
  }
  return [...tokens].slice(0, 80);
}

function scoreHaystack(hay: string, tokens: string[]): number {
  if (!tokens.length || !hay) return 0;
  const h = hay.toLowerCase();
  let score = 0;
  for (const tok of tokens) {
    if (!h.includes(tok)) continue;
    score += tok.length >= 4 ? 4 : tok.length >= 3 ? 3 : 2;
  }
  return score;
}

function clip(text: string, max: number): string {
  if (text.length <= max) return text;
  return `${text.slice(0, max - 12)}\n…(截断)`;
}

function charCard(c: Character): string {
  return [
    `- ${c.displayName} (${c.defineName})`,
    c.voice ? `  语气: ${c.voice}` : "",
    c.bio ? `  人设: ${c.bio}` : "",
    c.relationships ? `  关系: ${c.relationships}` : "",
  ]
    .filter(Boolean)
    .join("\n");
}

function locCard(l: Location): string {
  return `- ${l.name}${l.imageTag ? ` [${l.imageTag}]` : ""}${
    l.description ? `: ${l.description}` : ""
  }${l.tags?.length ? ` #${l.tags.join("#")}` : ""}`;
}

function chapterTail(plain: string, max: number): string {
  if (plain.length <= max) return plain;
  return `…(前文省略)\n${plain.slice(plain.length - max)}`;
}

function chapterHeadTail(plain: string, max: number): string {
  if (plain.length <= max) return plain;
  const head = Math.floor(max * 0.35);
  const tail = max - head - 20;
  return `${plain.slice(0, head)}\n…(中间省略)…\n${plain.slice(plain.length - tail)}`;
}

/**
 * Build a retrieval-biased project context for long-form Agent use.
 * Prefer: meta + bible digest + chapter index + focus chapter + scored slices.
 */
export function buildAgentContext(
  project: VnProject,
  opts: AgentContextOptions = {}
): AgentContextResult {
  const maxChars = opts.maxChars ?? 12000;
  const task =
    opts.task ??
    (opts.userMessage ? inferAgentTask(opts.userMessage) : "chat");
  const included: string[] = [`模式:${task}`];

  const focusChapter =
    project.chapters.find((c) => c.id === opts.chapterId) ??
    project.chapters[0];

  const askTokens = tokenize(
    [opts.userMessage ?? "", opts.selection ?? ""].join("\n")
  );
  // Only score against the user ask / selection — never seed with every name
  // (that would make every character card match itself).
  const effectiveTokens = askTokens;

  const bible = project.bible;
  const metaLines = [
    `# ${project.title}`,
    project.logline ? `Logline: ${project.logline}` : "",
    project.genre ? `Genre: ${project.genre}` : "",
  ].filter(Boolean);

  const bibleBudget =
    task === "outline" || task === "consistency" ? 2800 : 2000;
  const bibleParts: string[] = [];
  if (bible?.world || project.lore) {
    bibleParts.push(`世界观:\n${clip(bible?.world || project.lore || "", 900)}`);
  }
  if (bible?.background) {
    bibleParts.push(`故事背景:\n${clip(bible.background, 500)}`);
  }
  if (bible?.outline) {
    const relatedBeats = selectOutlineBeats(bible.outline, effectiveTokens, 5);
    if (relatedBeats.length && task !== "outline") {
      bibleParts.push(
        `大纲相关节拍（检索）:\n${relatedBeats.map((b) => `- ${b}`).join("\n")}`
      );
      included.push(`大纲节拍×${relatedBeats.length}`);
    }
    bibleParts.push(
      `大纲:\n${clip(bible.outline, task === "outline" ? 1200 : 500)}`
    );
  }
  if (bible?.themes) bibleParts.push(`主题/基调:\n${clip(bible.themes, 300)}`);
  if (bible?.notes) bibleParts.push(`备忘:\n${clip(bible.notes, 300)}`);
  let bibleBlock = bibleParts.join("\n\n");
  if (bibleBlock.length > bibleBudget) {
    bibleBlock = clip(bibleBlock, bibleBudget);
  }
  if (bibleBlock) included.push("设定bible");

  const digests = digestAllChapters(project);
  const digestFmt = formatChapterDigestIndex(digests, {
    focusId: focusChapter?.id,
    tokens: effectiveTokens,
    maxRelatedExcerpts: task === "consistency" ? 5 : 3,
  });
  included.push(...digestFmt.included.filter((x) => !x.startsWith("章摘要")));

  const indexLines =
    digestFmt.indexLines.length > 0
      ? digestFmt.indexLines
      : project.chapters.map((ch, i) => {
          const mark = focusChapter && ch.id === focusChapter.id ? "◀当前" : "";
          const syn = ch.synopsis ? ` — ${clip(ch.synopsis, 80)}` : "";
          return `${i + 1}. ${ch.title}${mark}${syn}`;
        });
  included.push(`章节目录×${project.chapters.length}`);

  // Score characters
  type Ranked<T> = { item: T; score: number };
  const rankedChars: Ranked<Character>[] = project.characters.map((c) => {
    const hay = `${c.displayName} ${c.defineName} ${c.voice} ${c.bio} ${c.relationships}`;
    let score = scoreHaystack(hay, effectiveTokens);
    if (focusChapter) {
      const plain = blocksToPlain(focusChapter.blocks, project.characters);
      if (
        plain.includes(c.displayName) ||
        plain.includes(c.defineName) ||
        plain.toLowerCase().includes(c.defineName.toLowerCase())
      ) {
        score += 8;
      }
    }
    if (task === "voice" || task === "consistency") score += 2;
    return { item: c, score };
  });
  rankedChars.sort((a, b) => b.score - a.score);

  const charPickCount =
    task === "voice" || task === "consistency"
      ? Math.min(12, rankedChars.length)
      : Math.min(6, rankedChars.length);
  const pickedChars = rankedChars
    .filter((r, i) => r.score > 0 || i < 3)
    .slice(0, charPickCount);
  if (!pickedChars.length && rankedChars.length) {
    pickedChars.push(...rankedChars.slice(0, Math.min(3, rankedChars.length)));
  }

  const locs = project.locations ?? [];
  const rankedLocs: Ranked<Location>[] = locs.map((l) => {
    const hay = `${l.name} ${l.imageTag ?? ""} ${l.description ?? ""} ${(l.tags ?? []).join(" ")}`;
    let score = scoreHaystack(hay, effectiveTokens);
    if (task === "scene" || task === "consistency") score += 1;
    return { item: l, score };
  });
  rankedLocs.sort((a, b) => b.score - a.score);
  const pickedLocs = rankedLocs
    .filter((r, i) => r.score > 0 || i < 4)
    .slice(0, task === "scene" ? 8 : 5);
  if (!pickedLocs.length && rankedLocs.length) {
    pickedLocs.push(...rankedLocs.slice(0, Math.min(4, rankedLocs.length)));
  }

  const linkLines: string[] = [];
  const links = project.locationLinks ?? [];
  if (links.length && pickedLocs.length) {
    const byId = new Map(locs.map((l) => [l.id, l.name]));
    const idSet = new Set(pickedLocs.map((r) => r.item.id));
    for (const link of links) {
      if (idSet.has(link.fromId) || idSet.has(link.toId)) {
        linkLines.push(
          `- ${byId.get(link.fromId) ?? link.fromId} --${link.relation}--> ${byId.get(link.toId) ?? link.toId}${link.note ? ` (${link.note})` : ""}`
        );
      }
    }
  }

  const varLines = (project.variables ?? []).map(
    (v) =>
      `- ${v.name} (${v.key}: ${v.type}) = ${JSON.stringify(v.value)}${
        v.bindCharacterId ? ` [char:${v.bindCharacterId}]` : ""
      }${v.note ? ` // ${v.note}` : ""}`
  );
  const spriteLines = (project.sprites ?? []).map((s) => {
    const ex = s.expressions.map((e) => e.tag).join(", ");
    return `- ${s.name} image=${s.imageTag}${s.characterId ? ` char=${s.characterId}` : ""} exprs=[${ex}]`;
  });

  // Other chapters: prefer extractive digests; raw excerpt only if high score + short
  const otherChapterBlocks: string[] = [...digestFmt.relatedBlocks];
  for (const ch of project.chapters) {
    if (focusChapter && ch.id === focusChapter.id) continue;
    const plain = blocksToPlain(ch.blocks, project.characters);
    const hay = `${ch.title}\n${ch.synopsis ?? ""}\n${plain}`;
    const score = scoreHaystack(hay, effectiveTokens);
    const already =
      score >= 4 &&
      otherChapterBlocks.some((b) => b.includes(`### ${ch.title}`));
    if (score >= 8 && plain.length && plain.length < 2500 && !already) {
      const budget = Math.min(900, 300 + score * 40);
      otherChapterBlocks.push(
        `### ${ch.title}（正文摘录 score=${score}）\n${chapterHeadTail(plain, budget)}`
      );
      included.push(`摘录章:${ch.title}`);
    }
  }

  // Focus chapter — prefer tail for continue/polish/branch/scene
  let focusBody = "";
  if (focusChapter) {
    const plain = blocksToPlain(focusChapter.blocks, project.characters);
    const focusBudget =
      task === "outline"
        ? 1800
        : task === "continue" || task === "branch" || task === "scene"
          ? 5000
          : 4200;
    const useTail =
      task === "continue" ||
      task === "polish" ||
      task === "branch" ||
      task === "scene";
    focusBody = [
      `## 当前章节：${focusChapter.title}`,
      focusChapter.synopsis ? `Synopsis: ${focusChapter.synopsis}` : "",
      useTail ? chapterTail(plain, focusBudget) : chapterHeadTail(plain, focusBudget),
    ]
      .filter(Boolean)
      .join("\n");
    included.push(`当前章:${focusChapter.title}`);
  }

  if (pickedChars.length) {
    included.push(`角色×${pickedChars.length}`);
  }
  if (pickedLocs.length) included.push(`地点×${pickedLocs.length}`);
  if (varLines.length) included.push(`变量×${varLines.length}`);
  if (opts.selection) included.push(`选区${opts.selection.length}字`);
  if (opts.chatMemory?.trim()) included.push("对话记忆");

  const focusDigest = digests.find((d) => d.chapterId === focusChapter?.id);

  const sections: string[] = [
    metaLines.join("\n"),
    bibleBlock ? `\n## Story Bible（内部参考，禁止整段搬进正文）\n${bibleBlock}` : "",
    opts.chatMemory?.trim()
      ? `\n## 对话滚动记忆（更早轮次压缩，非正式剧情）\n${clip(opts.chatMemory.trim(), 2800)}`
      : "",
    `\n## 章节目录（含本地摘要）\n${indexLines.join("\n")}`,
    pickedChars.length
      ? `\n## Characters（内部参考：只校准语气与行为，禁止写入对白当说明书）\n${pickedChars.map((r) => charCard(r.item)).join("\n")}`
      : "",
    pickedLocs.length
      ? `\n## Locations（内部参考：氛围与走位，勿念地名百科）\n${pickedLocs.map((r) => locCard(r.item)).join("\n")}${
          linkLines.length ? `\n通路:\n${linkLines.join("\n")}` : ""
        }`
      : "",
    varLines.length && (task === "consistency" || task === "branch" || task === "scene" || task === "continue" || effectiveTokens.length)
      ? `\n## Variables / 状态机\n${varLines.join("\n")}`
      : varLines.length && task === "chat"
        ? `\n## Variables / 状态机\n${clip(varLines.join("\n"), 600)}`
        : "",
    spriteLines.length
      ? `\n## Sprites\n${clip(spriteLines.join("\n"), 400)}`
      : "",
    otherChapterBlocks.length
      ? `\n## 其他章节（摘要优先）\n${otherChapterBlocks.join("\n\n")}`
      : "",
    focusBody
      ? `\n${focusBody}${
          focusDigest?.beatSummary
            ? `\n（章摘要备忘: ${focusDigest.beatSummary}）`
            : ""
        }`
      : "",
    opts.selection
      ? `\n## 用户选区（审稿/改写焦点）\n${clip(opts.selection, 2000)}`
      : "",
    `\n## 编排说明\n上下文按任务「${task}」检索拼装：章摘要本地抽取、大纲节拍检索、对话记忆压缩。人设与 bible 是作者备忘不是讲稿。续写请紧接「当前章节」正文末尾。`,
  ];

  let text = sections.filter(Boolean).join("\n");

  // Trim from the least critical middle (other chapters) if over budget
  if (text.length > maxChars) {
    const overflow = text.length - maxChars;
    // Drop other-chapter bodies first by regenerating without heavy excerpts
    if (overflow > 0 && otherChapterBlocks.length) {
      const lightOthers = project.chapters
        .filter((ch) => !focusChapter || ch.id !== focusChapter.id)
        .map((ch) =>
          ch.synopsis
            ? `### ${ch.title}\n摘要: ${clip(ch.synopsis, 100)}`
            : `### ${ch.title}`
        )
        .join("\n\n");
      text = sections
        .filter(Boolean)
        .join("\n")
        .replace(
          /## 其他章节[\s\S]*?(?=\n## 当前章节|\n## 用户选区|\n## 编排说明|$)/,
          `## 其他章节（仅摘要，因篇幅压缩）\n${lightOthers}\n\n`
        );
      included.push("已压缩其他章摘录");
    }
    if (text.length > maxChars) {
      // Keep head (meta) + tail (focus chapter / selection)
      const keepTail = Math.min(
        Math.floor(maxChars * 0.55),
        focusBody.length + (opts.selection?.length ?? 0) + 400
      );
      const keepHead = maxChars - keepTail - 30;
      text = `${text.slice(0, keepHead)}\n\n…(上下文中段压缩)…\n\n${text.slice(text.length - keepTail)}`;
      included.push("中段压缩");
    }
  }

  return {
    text,
    included,
    charsUsed: text.length,
    task,
  };
}
