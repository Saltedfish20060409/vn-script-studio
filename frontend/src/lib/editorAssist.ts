/**
 * 编辑器手感层（纯函数，无 DOM、无 React）。
 *
 * 为什么单独一层：这一层全是"给定文本 → 得到什么"的确定性规则，可以直接跑单测；
 * 组件只负责把结果画出来、把光标放回去。规则本身刻意保守——宁可漏报也不误报，
 * 因为作者最烦的是"工具在没写错的地方报错"。所有条目都给出原文片段与位置，
 * 点一下就能跳到那一处，作者自己判断要不要改。
 *
 * 与后端 `app/core/novel_consistency.py` 的口径保持一致（同一套标点/连字符/省略号
 * 判据），区别只在范围：编辑器按段判，后端按章判（对白跨行是合法写法，按行会误报）。
 */

/**
 * 字数口径不在这里重复实现：`lib/wordCount.ts` 已经和后端 `writing_stats.py`
 * 对齐（汉字逐字 + 拉丁词），再抄一份迟早会两边不一致——界面上就会出现
 * "卷头 1200 字、进度条 1188 字"这种事。
 */
import { countWords } from "./wordCount";
import { findTypos, typoMessage } from "./typoRules";

export type IssueLevel = "error" | "warn" | "info";

export interface TextIssue {
  /** 机器可读的规则名（测试与去重用） */
  code: string;
  level: IssueLevel;
  /** 给人看的一句话：说清"哪里不对"和"通常怎么改" */
  message: string;
  /** 命中片段在全文中的起始偏移 */
  offset: number;
  /** 命中片段长度（用来选中/高亮） */
  length: number;
  /** 1 起算的行号（用来显示"第 N 行"） */
  line: number;
  /** 原文片段（截断到 24 字，供列表里直接看） */
  snippet: string;
}

const CJK = "\\u3400-\\u4dbf\\u4e00-\\u9fff\\uf900-\\ufaff\\u3040-\\u30ff\\uac00-\\ud7af";
const CJK_RE = new RegExp(`[${CJK}]`);

/** 命中片段超过这个长度就截断（列表里只用来认位置，不需要全文） */
const SNIPPET_MAX = 24;

function lineOf(text: string, offset: number): number {
  let line = 1;
  for (let i = 0; i < offset && i < text.length; i += 1) {
    if (text[i] === "\n") line += 1;
  }
  return line;
}

function snippetOf(text: string, offset: number, length: number): string {
  const raw = text.slice(offset, offset + Math.max(length, 1)).replace(/\n/g, "⏎");
  return raw.length > SNIPPET_MAX ? `${raw.slice(0, SNIPPET_MAX)}…` : raw;
}

function hasCjkNear(text: string, offset: number, length: number, radius = 2): boolean {
  const from = Math.max(0, offset - radius);
  const to = Math.min(text.length, offset + length + radius);
  return CJK_RE.test(text.slice(from, to));
}

/** 把文本切成"段"：连续非空行算一段，空行分段。返回每段的起止偏移。 */
function paragraphs(text: string): { from: number; to: number }[] {
  const out: { from: number; to: number }[] = [];
  let from = -1;
  let offset = 0;
  for (const line of text.split("\n")) {
    const empty = line.trim() === "";
    if (!empty && from < 0) from = offset;
    if (empty && from >= 0) {
      out.push({ from, to: offset });
      from = -1;
    }
    offset += line.length + 1;
  }
  if (from >= 0) out.push({ from, to: text.length });
  return out;
}

/**
 * 逐段检查引号配对。
 *
 * 为什么按段而不是按行：中文对白确实可以跨行（「他说：\n……这样」），按行会误报；
 * 按章又太钝（一整章几千字，一处不配对要自己找）。段是最接近"作者心里一段话"的单位。
 * 只比数量、不比顺序——顺序检查（闭引号出现在开引号之前）误报率高，交给后端章级扫描。
 */
function checkQuotes(text: string): TextIssue[] {
  const pairs: [string, string][] = [
    ["「", "」"],
    ["『", "』"],
    ["“", "”"],
    ["‘", "’"],
    ["（", "）"],
  ];
  const issues: TextIssue[] = [];
  for (const para of paragraphs(text)) {
    const body = text.slice(para.from, para.to);
    for (const [open, close] of pairs) {
      const opens = body.split(open).length - 1;
      const closes = body.split(close).length - 1;
      if (opens === closes) continue;
      const first = body.indexOf(opens > closes ? open : close);
      const offset = para.from + (first < 0 ? 0 : first);
      issues.push({
        code: "quote_unbalanced",
        level: "error",
        message: `引号不配对：这一段有 ${opens} 个「${open}」、${closes} 个「${close}」，请检查漏写或多写`,
        offset,
        length: 1,
        line: lineOf(text, offset),
        snippet: snippetOf(text, offset, 1),
      });
    }
  }
  return issues;
}

/** 一条规则 + 一个正则：命中处做一次判断，通过就报。 */
function scan(
  text: string,
  re: RegExp,
  level: IssueLevel,
  code: string,
  message: (hit: RegExpExecArray) => string,
  accept: (hit: RegExpExecArray) => boolean = () => true
): TextIssue[] {
  const issues: TextIssue[] = [];
  const rx = new RegExp(re.source, re.flags.includes("g") ? re.flags : `${re.flags}g`);
  let hit: RegExpExecArray | null = rx.exec(text);
  while (hit) {
    if (accept(hit) && hit[0].length > 0) {
      issues.push({
        code,
        level,
        message: message(hit),
        offset: hit.index,
        length: hit[0].length,
        line: lineOf(text, hit.index),
        snippet: snippetOf(text, hit.index, hit[0].length),
      });
    }
    if (hit[0].length === 0) rx.lastIndex += 1;
    hit = rx.exec(text);
  }
  return issues;
}

/**
 * 确定性笔误/标点体检。规则刻意只覆盖"几乎肯定是手误"的情形：
 * 半角标点贴在汉字上、`--` 当破折号、`...` 当省略号、单个 `—`、`。。。`、
 * 汉字之间多出空格、行尾多余空格。混合引号体系（「」与“”并存）只报 info——
 * 引用层次里两种并用是合法的。
 */
export function lintProse(text: string): TextIssue[] {
  if (!text) return [];
  const issues: TextIssue[] = [
    ...checkQuotes(text),
    // 半角标点紧贴汉字：中文正文里出现 , ; : ! ? ( ) 基本是输入法没切或从英文稿粘来的
    ...scan(
      text,
      new RegExp(`[${CJK}][,;:!?()]|[,;:!?()][${CJK}]`, "g"),
      "warn",
      "punct_halfwidth_near_cjk",
      (h) => `中文里混用了半角标点「${h[0]}」，中文标点通常写作 ，；：！？（）`
    ),
    // -- 当破折号（--- 常见于 Markdown 分隔线，不报）
    ...scan(text, /(?<!-)--(?!-)/g, "warn", "dash_ascii_double", () =>
      "用两个半角连字符 `--` 代替破折号了，中文破折号是 `——`"
    ),
    // 落单的 em dash：成双的 —— 是正常破折号，2019—2020 这类不贴汉字也不算
    ...scan(
      text,
      /—+/g,
      "warn",
      "dash_single_em",
      () => "这个破折号只有一个 `—`，中文破折号通常成双写 `——`",
      (h) => h[0].length === 1 && hasCjkNear(text, h.index, 1)
    ),
    // 半角省略号（要求邻近有汉字，英文句中的 ... 不报）
    ...scan(
      text,
      /\.{3,}/g,
      "warn",
      "ellipsis_ascii_dots",
      () => "用半角句点写省略号了，中文省略号是 `……`（两个）",
      (h) => hasCjkNear(text, h.index, h[0].length)
    ),
    // 。。。 当省略号
    ...scan(text, /。{3,}/g, "warn", "ellipsis_fullwidth_period", () =>
      "用句号 `。。。` 代替省略号了，中文省略号是 `……`"
    ),
    // 汉字之间的空格：从 PDF/EPUB 转来的稿子最容易带这个
    ...scan(
      text,
      new RegExp(`[${CJK}][ \\t]+[${CJK}]`, "g"),
      "info",
      "space_between_cjk",
      () => "汉字之间多了空格（导入的稿子常见），确认是无意的就删掉"
    ),
    // 行尾空格
    ...scan(text, /[ \t]+(?=\n|$)/g, "info", "trailing_space", () =>
      "行尾有多余空格"
    ),
    // 常见别字（成语/固定搭配词表，零误报口径；见 lib/typoRules.ts）
    ...lintTypos(text),
  ];
  return issues.sort((a, b) => a.offset - b.offset || a.code.localeCompare(b.code));
}

/**
 * 别字体检（词表命中，零误报口径）。
 *
 * 为什么并进 `lintProse` 而不是另开一组界面：作者看到的应该是"这一章有几处要留意"，
 * 而不是先学会区分"标点问题"和"别字问题"。级别给 warn——成语里的同音别字
 * 几乎不可能是本意，但仍由作者确认（可能有角色故意写错，比如小孩说话）。
 */
export function lintTypos(text: string): TextIssue[] {
  return findTypos(text).map((hit) => ({
    code: "typo_confusion",
    level: "warn" as const,
    message: typoMessage(hit),
    offset: hit.offset,
    length: hit.length,
    line: lineOf(text, hit.offset),
    snippet: snippetOf(text, hit.offset, hit.length),
  }));
}

/** 按级别汇总（界面上的角标用） */
export function countIssues(issues: TextIssue[]): Record<IssueLevel, number> {
  const out: Record<IssueLevel, number> = { error: 0, warn: 0, info: 0 };
  for (const issue of issues) out[issue.level] += 1;
  return out;
}

export interface MatchRange {
  from: number;
  to: number;
}

export interface FindOptions {
  caseSensitive?: boolean;
  regex?: boolean;
}

/**
 * 查找全部命中。正则模式下用户输入的是正则；非法正则不抛异常，返回 null，
 * 由界面显示"正则写错了"——作者在输入框里边打边看，抛异常会让整块界面炸掉。
 */
export function findMatches(
  text: string,
  query: string,
  options: FindOptions = {}
): MatchRange[] | null {
  if (!query) return [];
  const out: MatchRange[] = [];
  if (options.regex) {
    let rx: RegExp;
    try {
      rx = new RegExp(query, options.caseSensitive ? "g" : "gi");
    } catch {
      return null;
    }
    let hit = rx.exec(text);
    while (hit) {
      out.push({ from: hit.index, to: hit.index + hit[0].length });
      if (hit[0].length === 0) rx.lastIndex += 1;
      hit = rx.exec(text);
    }
    return out;
  }
  const haystack = options.caseSensitive ? text : text.toLowerCase();
  const needle = options.caseSensitive ? query : query.toLowerCase();
  let at = haystack.indexOf(needle);
  while (at >= 0) {
    out.push({ from: at, to: at + needle.length });
    at = haystack.indexOf(needle, at + Math.max(needle.length, 1));
  }
  return out;
}

/** 在指定区间做替换（区间越界会被夹到文本范围内，调用方不用先校验） */
export function replaceRange(text: string, from: number, to: number, replacement: string): string {
  const a = Math.max(0, Math.min(from, to, text.length));
  const b = Math.max(0, Math.min(Math.max(from, to), text.length));
  return text.slice(0, a) + replacement + text.slice(b);
}

/**
 * 全部替换：返回新文本与替换次数（次数 0 时新文本与原文本相同）。
 *
 * 正则模式下用原生 `replace`，所以 `$1`/`$&` 这类捕获组引用是按标准语义展开的；
 * 非正则模式一律按字面替换（作者写 `$1` 就是想写 `$1`）。
 */
export function replaceAllMatches(
  text: string,
  query: string,
  replacement: string,
  options: FindOptions = {}
): { text: string; count: number } {
  const ranges = findMatches(text, query, options);
  if (!ranges || ranges.length === 0) return { text, count: 0 };
  if (options.regex) {
    let rx: RegExp;
    try {
      rx = new RegExp(query, options.caseSensitive ? "g" : "gi");
    } catch {
      return { text, count: 0 };
    }
    return { text: text.replace(rx, replacement), count: ranges.length };
  }
  let out = text;
  // 从后往前替换，前面的偏移才不会失效
  for (let i = ranges.length - 1; i >= 0; i -= 1) {
    out = replaceRange(out, ranges[i].from, ranges[i].to, replacement);
  }
  return { text: out, count: ranges.length };
}

/**
 * 「替换这一处」用的展开：把当前命中片段单独拿出来跑一次替换，
 * 这样正则模式下的 `$1` 与"全部替换"行为一致（只在命中区间内展开，不越界）。
 */
export function expandReplacement(
  text: string,
  range: MatchRange,
  query: string,
  replacement: string,
  options: FindOptions = {}
): string {
  if (!options.regex) return replacement;
  try {
    const rx = new RegExp(query, options.caseSensitive ? "" : "i");
    return text.slice(range.from, range.to).replace(rx, replacement);
  } catch {
    return replacement;
  }
}

/** 找下一个命中：从 caret 往后找，到末尾回绕（找不到时返回 null） */
export function nextMatch(
  ranges: MatchRange[],
  caret: number,
  direction: 1 | -1 = 1
): MatchRange | null {
  if (ranges.length === 0) return null;
  if (direction === 1) {
    return ranges.find((r) => r.from > caret) ?? ranges[0];
  }
  for (let i = ranges.length - 1; i >= 0; i -= 1) {
    if (ranges[i].to < caret) return ranges[i];
  }
  return ranges[ranges.length - 1];
}

/**
 * 自动配对的括号/引号：输入左边那个，右边那个自己出来
 */
export const PAIR_MAP: Record<string, string> = {
  "「": "」",
  "『": "』",
  "“": "”",
  "‘": "’",
  "（": "）",
  "【": "】",
  "《": "》",
  "〔": "〕",
  "(": ")",
  "[": "]",
  "{": "}",
  '"': '"',
  "'": "'",
};

const CLOSERS = new Set(Object.values(PAIR_MAP));

export interface PairEdit {
  text: string;
  /** 处理完之后光标（或选区终点）应该在哪 */
  caret: number;
  /** 有选区被包住时，这里给出新的选区，方便继续输入 */
  selection?: MatchRange;
}

/**
 * 按键级的配对处理：在 `onKeyDown` 里拿到"即将插入的字符"再决定要不要拦下来自己写。
 *
 * 三种情况：
 * 1. 敲左半边且有选区 → 把选区包起来（`「选中文字」`）；
 * 2. 敲左半边且无选区 → 插入一对，光标留在中间；
 * 3. 敲右半边且右边正好就是那个右半边 → 只把光标移过去，不再插一个（"跳过"）。
 * 其余情况返回 null，让 textarea 走它自己的输入路径——我们只接管这三件事。
 */
export function applyPairOnKey(
  text: string,
  start: number,
  end: number,
  key: string
): PairEdit | null {
  if (key.length !== 1) return null;
  const close = PAIR_MAP[key];
  if (close) {
    if (end > start) {
      const wrapped = text.slice(0, start) + key + text.slice(start, end) + close + text.slice(end);
      return {
        text: wrapped,
        caret: end + 2,
        selection: { from: start + 1, to: end + 1 },
      };
    }
    return { text: text.slice(0, start) + key + close + text.slice(start), caret: start + 1 };
  }
  if (CLOSERS.has(key) && end === start && text[start] === key) {
    return { text, caret: start + 1 };
  }
  return null;
}

/** 场景分隔符：一键插入（后端/导出把它当分场标记） */
export const SCENE_SEPARATOR = "◇◇◇";

/**
 * 场景分隔行：`◇◇◇`/`※※※`/`***`/`---` 这类独立一行；也认显式场景标题
 * （`【场景】`、`场景：xxx`、`第 3 场`），因为作者两种写法都会用。
 */
const SEPARATOR_RE = /^(?:[◇◆※*\-—_=·]{3,})$/;
/**
 * 显式场景标题。这里刻意不用"一条宽松正则"，而是三条严格形式——
 * 因为 `第X场` 太容易撞上正文：`第一场的内容。` 会被 `^第.+场(.*)$` 当成标题，
 * 于是整章的第一个场景被切掉。规则收紧到"场次后面必须是分隔符或什么都没有"。
 */
function headingOf(trimmed: string): string | null {
  let hit = /^【(.+)】$/.exec(trimmed);
  if (hit) return hit[1].trim();
  hit = /^场景[：:]\s*(.+)$/.exec(trimmed);
  if (hit) return hit[1].trim();
  hit = /^#{2,}\s*(.+)$/.exec(trimmed);
  if (hit) return hit[1].trim();
  // `第3场` / `第 3 场`（整行只有场次）
  const ordinal = /^第\s*([零一二三四五六七八九十百千0-9]+)\s*场\s*$/.exec(trimmed);
  if (ordinal) return trimmed;
  // `第3场：雨夜` / `第 3 场·告别` / `第 3 场 — 告别`
  const labeled = /^第\s*[零一二三四五六七八九十百千0-9]+\s*场\s*[：:·—-]\s*(.+)$/.exec(trimmed);
  if (labeled) return labeled[1].trim();
  // `第 3 场 告别`：空格分隔的写法也认，但要求后半句短、且不像一句话
  const spaced = /^第\s*[零一二三四五六七八九十百千0-9]+\s*场\s+(\S.*)$/.exec(trimmed);
  if (spaced && spaced[1].length <= 20 && !/[。！？…；]$/.test(spaced[1])) {
    return spaced[1].trim();
  }
  return null;
}

export interface SceneBlock {
  /** 0 起算的场景序号 */
  index: number;
  /** 用于列表显示的标题（显式标题，或首行前若干字） */
  title: string;
  /** 场景正文起始偏移（分隔行之后 / 标题行之后） */
  from: number;
  /** 场景结束偏移（含正文，不含下一个分隔行） */
  to: number;
  /** 该场景字数（口径同 countWords） */
  words: number;
  /** 是否是显式写了标题的场景 */
  explicit: boolean;
}

/**
 * 解析场景大纲。没有分隔符时整章就是"一个场景"，不返回空数组——
 * 界面据此显示「本章还没有分场」，而不是显示一个空列表。
 */
export function parseScenes(text: string): SceneBlock[] {
  const lines = text.split("\n");
  const blocks: { title: string; explicit: boolean; from: number; to: number }[] = [];
  let current: { title: string; explicit: boolean; from: number; to: number } | null = null;
  let offset = 0;
  for (const raw of lines) {
    const lineStart = offset;
    const lineEnd = offset + raw.length;
    const trimmed = raw.trim();
    offset = lineEnd + 1;
    if (trimmed === "") {
      if (current) current.to = lineEnd;
      continue;
    }
    if (SEPARATOR_RE.test(trimmed)) {
      if (current) {
        current.to = lineStart;
        blocks.push(current);
        current = null;
      }
      continue;
    }
    const heading = headingOf(trimmed);
    if (heading !== null) {
      if (current) {
        current.to = lineStart;
        blocks.push(current);
      }
      current = {
        title: heading || `第 ${blocks.length + 1} 场`,
        explicit: true,
        from: offset,
        to: offset,
      };
      continue;
    }
    if (!current) {
      current = { title: trimmed.slice(0, 18), explicit: false, from: lineStart, to: lineEnd };
    } else {
      current.to = lineEnd;
    }
  }
  if (current) blocks.push(current);
  return blocks.map((block, index) => ({
    index,
    title: block.title === "" ? `第 ${index + 1} 场` : block.title,
    explicit: block.explicit,
    from: block.from,
    to: Math.max(block.to, block.from),
    words: countWords(text.slice(block.from, Math.max(block.to, block.from))),
  }));
}

export interface GoalProgress {
  words: number;
  target: number;
  /** 0..1（target 为 0 时按 1 处理，界面不会显示空进度条） */
  ratio: number;
  remaining: number;
  done: boolean;
}

/** 目标进度（目标 <= 0 视为"没设目标"，ratio 记 1、不显示差多少） */
export function goalProgress(words: number, target: number): GoalProgress {
  const t = Number.isFinite(target) && target > 0 ? Math.floor(target) : 0;
  if (t === 0) return { words, target: 0, ratio: 1, remaining: 0, done: true };
  return {
    words,
    target: t,
    ratio: Math.max(0, Math.min(1, words / t)),
    remaining: Math.max(0, t - words),
    done: words >= t,
  };
}
