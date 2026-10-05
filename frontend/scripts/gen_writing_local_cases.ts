/**
 * 生成跨端夹具 `shared/test-fixtures/writing_local_cases.json`。
 *
 * 为什么用生成而不是手写：期望值必须是 **Web 端实现的真实输出**，手算的期望迟早会和实现悄悄分叉。
 * 输入（cases）在本文件里人工维护，输出（expect）由 `lib/editorAssist.ts` / `lib/wordCount.ts` /
 * `lib/typoRules.ts` 现算。
 *
 * 三端各自验证：
 * - 前端：`src/lib/writingLocalCases.test.ts` 重算并与夹具比对（改了规则忘记重新生成就红）；
 * - Android：`feature/editor` 的 `WritingLocalCasesTest` 用 Kotlin 移植版对同一份夹具断言。
 *
 * 用法（在 frontend 目录）：`npx tsx scripts/gen_writing_local_cases.ts`
 */
import { writeFileSync } from "node:fs";
import { resolve } from "node:path";
import { fileURLToPath } from "node:url";

import {
  PAIR_MAP,
  RULE_BASIS,
  SCENE_SEPARATOR,
  applyPairOnKey,
  expandReplacement,
  findMatches,
  goalProgress,
  lintProse,
  nextMatch,
  parseScenes,
  replaceAllMatches,
  replaceRange,
  type FindOptions,
  type MatchRange,
} from "../src/lib/editorAssist";
import { TYPO_RULES } from "../src/lib/typoRules";
import { countWords, formatWords } from "../src/lib/wordCount";

export const WORD_COUNT_TEXTS = [
  "",
  "你好世界",
  "Hello world 123",
  "混合abc中文123",
  "ＡＢＣ全角字母",
  "ひらがなカタカナ",
  "a_b-c d.e",
  "😀表情符号",
  "  \n\t ",
  "第1章 开端",
];

export const FORMAT_WORDS = [0, 999, 9999, 10000, 10050, 11500, 12345, 12500, 99999, 100000, 123456];

export const LINT_TEXTS = [
  "",
  "今天天气很好。他说：「我们走吧。」",
  "他说：「今天不写了。\n所以呢。",
  "你好,世界",
  "你好，世界!",
  "他说--不对",
  "分隔线\n---\n后文",
  "他—走了",
  "她说：2019—2020 年间——结束",
  "她说...",
  "English sentence... stays quiet",
  "好的。。。",
  "他 说了一句。",
  "他 说了一句。   ",
  "2019-2020 年间",
  "二〇一九年的秋天",
  "大约10几个人",
  "那是3、4年前的事",
  "第3、4章很精彩",
  "带来了……等等东西",
  "我在读《钟声与《第七个抽屉》》。",
  "他说：“她叫我“小澪”。”",
  "他迫不急待地推开门，一如继往地按耐不住。",
  "他说：「你好。\n\n她答：「再见。」\n",
  "（括号没关",
  "第一段「配对」。\n\n第二段「没配对。\n\n第三段』多了。",
  "混合“双引号”和「直角引号」都合法。",
];

export const FIND_CASES: { text: string; query: string; options: FindOptions }[] = [
  { text: "abcABCabc", query: "abc", options: {} },
  { text: "abcABCabc", query: "abc", options: { caseSensitive: true } },
  { text: "aaaa", query: "aa", options: {} },
  { text: "他说他走", query: "他", options: {} },
  { text: "abc", query: "", options: {} },
  { text: "a1b22c333", query: "\\d+", options: { regex: true } },
  { text: "a1b22c333", query: "(", options: { regex: true } },
  { text: "abc", query: "x*", options: { regex: true } },
  { text: "ABC abc", query: "b", options: { regex: true, caseSensitive: true } },
];

export const REPLACE_ALL_CASES: {
  text: string;
  query: string;
  replacement: string;
  options: FindOptions;
}[] = [
  { text: "猫追老鼠，猫赢了。", query: "猫", replacement: "狗", options: {} },
  { text: "abcABC", query: "abc", replacement: "x", options: {} },
  { text: "abcABC", query: "abc", replacement: "x", options: { caseSensitive: true } },
  { text: "价格$1", query: "$1", replacement: "$$", options: {} },
  { text: "john smith", query: "(\\w+) (\\w+)", replacement: "$2, $1", options: { regex: true } },
  { text: "abc", query: "b", replacement: "[$&]", options: { regex: true } },
  { text: "a-b", query: "-", replacement: "$$", options: { regex: true } },
  { text: "abc", query: "z", replacement: "y", options: {} },
  { text: "abc", query: "(", replacement: "y", options: { regex: true } },
  { text: "x1y", query: "(\\d)", replacement: "$2|$0|$1$1", options: { regex: true } },
];

export const EXPAND_CASES: {
  text: string;
  range: MatchRange;
  query: string;
  replacement: string;
  options: FindOptions;
}[] = [
  { text: "john smith", range: { from: 0, to: 10 }, query: "(\\w+) (\\w+)", replacement: "$2 $1", options: { regex: true } },
  { text: "john smith", range: { from: 0, to: 4 }, query: "john", replacement: "$1", options: {} },
  { text: "ab", range: { from: 0, to: 1 }, query: "a", replacement: "<$&>", options: { regex: true } },
];

export const NEXT_CASES: { ranges: MatchRange[]; caret: number; direction: 1 | -1 }[] = [
  { ranges: [], caret: 0, direction: 1 },
  { ranges: [{ from: 2, to: 3 }, { from: 8, to: 9 }], caret: 0, direction: 1 },
  { ranges: [{ from: 2, to: 3 }, { from: 8, to: 9 }], caret: 2, direction: 1 },
  { ranges: [{ from: 2, to: 3 }, { from: 8, to: 9 }], caret: 9, direction: 1 },
  { ranges: [{ from: 2, to: 3 }, { from: 8, to: 9 }], caret: 9, direction: -1 },
  { ranges: [{ from: 2, to: 3 }, { from: 8, to: 9 }], caret: 2, direction: -1 },
  { ranges: [{ from: 2, to: 3 }, { from: 8, to: 9 }], caret: 1, direction: -1 },
];

export const REPLACE_RANGE_CASES: { text: string; from: number; to: number; replacement: string }[] = [
  { text: "0123456789", from: 2, to: 4, replacement: "ab" },
  { text: "0123456789", from: 4, to: 2, replacement: "ab" },
  { text: "0123", from: -5, to: 99, replacement: "X" },
  { text: "0123", from: 2, to: 2, replacement: "ins" },
];

export const PAIR_CASES: { text: string; start: number; end: number; key: string }[] = [
  { text: "他说", start: 2, end: 2, key: "「" },
  { text: "他说", start: 0, end: 2, key: "“" },
  { text: "他说」", start: 2, end: 2, key: "」" },
  { text: "他说", start: 2, end: 2, key: "」" },
  { text: "abc", start: 1, end: 1, key: "(" },
  { text: "abc", start: 1, end: 1, key: "\"" },
  { text: "abc", start: 1, end: 1, key: "a" },
  { text: "abc", start: 1, end: 1, key: "「」" },
  { text: "", start: 0, end: 0, key: "《" },
];

export const SCENE_TEXTS = [
  "",
  "只有一段话，没有分场。",
  "第一场内容\n\n◇◇◇\n\n第二场内容\n***\n第三场",
  "【雨夜】\n他走进雨里。\n\n【清晨】\n天亮了。",
  "场景：告别\n她转身。\n场景：重逢\n他回头。",
  "第3场\n正文开始\n第 4 场：雨夜\n又一场\n第5场 告别\n结束",
  "第一场的内容。\n继续写。",
  "第 3 场 他走了。\n后文",
  "## 小标题\n文字\n### 另一个\n更多文字",
  "---\n开头就是分隔\n===\n",
  "A\n\n\n\nB\n◆◆◆\nC",
];

export const GOAL_CASES: { words: number; target: number }[] = [
  { words: 0, target: 0 },
  { words: 50, target: 100 },
  { words: 150, target: 100 },
  { words: 10, target: -5 },
  { words: 7, target: 3.9 },
  { words: 100, target: 100 },
];

function build() {
  return {
    _comment:
      "由 frontend/scripts/gen_writing_local_cases.ts 生成，请勿手改。Web 端与 Android 端都对这份夹具断言。",
    sceneSeparator: SCENE_SEPARATOR,
    ruleBasis: RULE_BASIS,
    pairMap: PAIR_MAP,
    typoRules: TYPO_RULES,
    wordCount: WORD_COUNT_TEXTS.map((text) => ({ text, count: countWords(text) })),
    formatWords: FORMAT_WORDS.map((words) => ({ words, text: formatWords(words) })),
    lintProse: LINT_TEXTS.map((text) => ({
      text,
      issues: lintProse(text).map((i) => ({
        code: i.code,
        level: i.level,
        message: i.message,
        offset: i.offset,
        length: i.length,
        line: i.line,
        snippet: i.snippet,
        basis: i.basis,
      })),
    })),
    findMatches: FIND_CASES.map((c) => ({ ...c, ranges: findMatches(c.text, c.query, c.options) })),
    replaceAll: REPLACE_ALL_CASES.map((c) => ({
      ...c,
      result: replaceAllMatches(c.text, c.query, c.replacement, c.options),
    })),
    expandReplacement: EXPAND_CASES.map((c) => ({
      ...c,
      result: expandReplacement(c.text, c.range, c.query, c.replacement, c.options),
    })),
    nextMatch: NEXT_CASES.map((c) => ({ ...c, result: nextMatch(c.ranges, c.caret, c.direction) })),
    replaceRange: REPLACE_RANGE_CASES.map((c) => ({
      ...c,
      result: replaceRange(c.text, c.from, c.to, c.replacement),
    })),
    applyPairOnKey: PAIR_CASES.map((c) => ({ ...c, result: applyPairOnKey(c.text, c.start, c.end, c.key) })),
    parseScenes: SCENE_TEXTS.map((text) => ({ text, scenes: parseScenes(text) })),
    goalProgress: GOAL_CASES.map((c) => ({ ...c, result: goalProgress(c.words, c.target) })),
  };
}

export const buildFixture = build;

// 直接运行时写文件；被 vitest 导入时只导出 buildFixture
if (process.argv[1] && /gen_writing_local_cases/.test(process.argv[1])) {
  const here = fileURLToPath(new URL(".", import.meta.url));
  const out = resolve(here, "../../shared/test-fixtures/writing_local_cases.json");
  writeFileSync(out, `${JSON.stringify(build(), null, 2)}\n`, "utf8");
  console.log(`wrote ${out}`);
}
