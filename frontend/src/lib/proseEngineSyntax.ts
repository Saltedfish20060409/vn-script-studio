/**
 * 正文档引擎语法检测（与 backend/app/core/prose_engine_syntax.py、
 * shared/test-fixtures/engine_syntax_cases.json 对齐）。
 */

export const PROSE_ENGINE_REJECT_MSG =
  "这段含引擎语法（如 label / $ / with fade），正文档只接受自然语言。若要生成 Ren'Py 脚本，请切到 RPY 面或使用「根据剧本生成」。";

export const PASTE_ENGINE_HINT = "这段内容含引擎语法，是否要粘贴到 RPY 面？";

const L1 = /^\s*label\s+[A-Za-z_][A-Za-z0-9_]*\s*:/;
const L2 = /^\s*menu(\s+[A-Za-z_][A-Za-z0-9_]*)?\s*:/;
const L3 = /^\s*define\s+[A-Za-z_][A-Za-z0-9_]*\s*=/;
const L4 = /^\s*jump\s+[A-Za-z_][A-Za-z0-9_]*\s*(#.*)?$/;
const L5 =
  /^\s*(scene|show|hide)\s+[A-Za-z_][A-Za-z0-9_.]*(?:\s+at\s+\S+)?(?:\s+with\s+\S+)?\s*$/;
const L6 = /^\s*with\s+(fade|dissolve|None|vpunch|hpunch)\b/;
const L7 = /^\s*\$\s*(?:[A-Za-z_]\w*|renpy\.)/;
const L8 = /^\s*if\s+(?:not\s+)?[A-Za-z_]\w*\s*:/;
const L9 = /^\s*\[label\s+[^\]]+\]/;
const L10 = /^\s*\[(场景|出现|消失)(\s*[:：]\s*[^\]]*|\s+[^\]]+)\]/;
const L11 = /renpy\.input\s*\(/;

const LINE_RULES: Array<[string, RegExp]> = [
  ["L1", L1],
  ["L2", L2],
  ["L3", L3],
  ["L4", L4],
  ["L5", L5],
  ["L6", L6],
  ["L7", L7],
  ["L8", L8],
  ["L9", L9],
  ["L10", L10],
];

/** 单行命中 → 规则 id，否则 null。 */
export function lineHasEngineSyntax(line: string): string | null {
  const raw = line.replace(/\r\n/g, "\n").replace(/\r/g, "\n");
  const stripped = raw.includes("#") ? raw.split("#", 1)[0] : raw;
  for (const [rid, pat] of LINE_RULES) {
    if (pat.test(stripped)) return rid;
  }
  if (L11.test(raw)) return "L11";
  return null;
}

/** 全文任一行命中 → 规则 id。 */
export function textHasEngineSyntax(text: string): string | null {
  if (!text) return null;
  for (const line of text.replace(/\r\n/g, "\n").replace(/\r/g, "\n").split("\n")) {
    const hit = lineHasEngineSyntax(line);
    if (hit) return hit;
  }
  return null;
}
