/**
 * 条件表达式：解析 / 求值 / 导出（分支与旗标的地基）。
 *
 * **语法的唯一权威在后端**（`backend/app/core/conditions.py`），这里是一份刻意保持
 * 最小化的镜像实现：前端试玩器要能求值，编辑器要能即时校验。两边共用同一张用例表
 * （见 conditions.test.ts 与 backend/tests/test_conditions.py），任何一侧改动都要同步。
 *
 *     cond  := term (('and' | '&&' | '并且') term)*
 *     term  := ident (op value)?
 *     op    := == | != | >= | <= | > | <
 *     value := 数字 | "字符串" | true | false
 */

type Comparison = {
  key: string;
  op?: "==" | "!=" | ">=" | "<=" | ">" | "<";
  value?: number | boolean | string;
};

export type Condition = Comparison[];

const IDENT_RE = /^[A-Za-z_][A-Za-z0-9_]*$/;
const OPS = ["==", "!=", ">=", "<=", ">", "<"] as const;
const NUMBER_RE = /^-?\d+(?:\.\d+)?$/;

class ConditionError extends Error {}

function parseValue(raw: string): number | boolean | string {
  const t = raw.trim();
  if (!t) throw new ConditionError("缺少比较值");
  const low = t.toLowerCase();
  if (low === "true") return true;
  if (low === "false") return false;
  if (NUMBER_RE.test(t)) return t.includes(".") ? parseFloat(t) : parseInt(t, 10);
  const quoted = t.match(/^"((?:\\.|[^"\\])*)"$/);
  if (quoted) return quoted[1].replace(/\\"/g, '"').replace(/\\\\/g, "\\");
  if (IDENT_RE.test(t)) return t;
  throw new ConditionError(`无法识别的比较值：${t.slice(0, 40)}`);
}

function parseTerm(raw: string): Comparison {
  const t = raw.trim();
  if (!t) throw new ConditionError("条件里有空的比较项");
  for (const op of OPS) {
    const idx = t.indexOf(op);
    if (idx > 0) {
      const key = t.slice(0, idx).trim();
      if (!IDENT_RE.test(key)) throw new ConditionError(`变量名不合法：${key.slice(0, 40)}`);
      return { key, op, value: parseValue(t.slice(idx + op.length)) };
    }
  }
  if (!IDENT_RE.test(t)) {
    throw new ConditionError(`条件写法不支持：${t.slice(0, 40)}（示例：affection >= 3）`);
  }
  return { key: t };
}

/** 空字符串 → 空条件（恒真）。语法错误抛 ConditionError。 */
export function parseCondition(text?: string | null): Condition {
  const raw = (text || "").trim();
  if (!raw) return [];
  return raw
    .split(/\s*(?:&&|\band\b|并且)\s*/i)
    .filter((p) => p.trim())
    .map(parseTerm);
}

function coerce(left: unknown, right: unknown): { lhs: unknown; rhs: unknown; ok: boolean } {
  if (typeof left === "boolean" || typeof right === "boolean") {
    return { lhs: left, rhs: right, ok: true };
  }
  if (typeof left === "number" && typeof right === "string") {
    const n = Number(right);
    return Number.isNaN(n)
      ? { lhs: left, rhs: right, ok: false }
      : { lhs: left, rhs: n, ok: true };
  }
  if (typeof left === "string" && typeof right === "number") {
    const n = Number(left);
    return Number.isNaN(n)
      ? { lhs: left, rhs: right, ok: false }
      : { lhs: n, rhs: right, ok: true };
  }
  return { lhs: left, rhs: right, ok: true };
}

/** 未定义变量按 0/false 处理（试玩器里"没定义=假"，并在变量检查里给出提示）。 */
export function evaluateCondition(
  cond: Condition,
  variables: Record<string, unknown>
): boolean {
  for (const c of cond) {
    let left = variables[c.key];
    if (left === undefined || left === null) {
      left = c.op === undefined || c.op === "==" || c.op === "!=" ? false : 0;
    }
    if (c.op === undefined) {
      if (!left) return false;
      continue;
    }
    const { lhs, rhs, ok } = coerce(left, c.value);
    if (c.op === "==" || c.op === "!=") {
      const equal = ok ? lhs === rhs : false;
      if ((c.op === "==") !== equal) return false;
      continue;
    }
    if (!ok) return false;
    if (typeof lhs !== "number" || typeof rhs !== "number") return false;
    if (c.op === ">=") {
      if (!(lhs >= rhs)) return false;
    } else if (c.op === "<=") {
      if (!(lhs <= rhs)) return false;
    } else if (c.op === ">") {
      if (!(lhs > rhs)) return false;
    } else if (!(lhs < rhs)) {
      return false;
    }
  }
  return true;
}

/** 校验用：返回错误信息，合法则返回 null。 */
export function conditionError(text?: string | null): string | null {
  try {
    parseCondition(text);
    return null;
  } catch (e) {
    return e instanceof Error ? e.message : "条件格式不正确";
  }
}
