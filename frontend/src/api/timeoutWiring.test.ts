/**
 * 超时 wiring 守卫（AST）。
 *
 * ## 规则 A（LLM 档必须显式 timeoutKind: "llm"）
 * 扫描 `frontend/src/api/*.ts`（排除 *.test.ts）：凡 `timeoutMs` 解析为
 * `TIMEOUTS.(quick|chat|write|long|batch|probe)` 的对象字面量，必须同层有
 * `timeoutKind: "llm"`。
 *
 * **覆盖**：同文件一层 `const t = TIMEOUTS.chat` → `{ timeoutMs: t }`。
 * **不覆盖（靠 code review）**：多层转发、函数返回值、跨文件 import 别名。
 *
 * ## 规则 B（禁止把 timeoutMs 塞进请求 body）
 * `timeoutMs` 不得出现在：
 * - `JSON.stringify(...)` 的实参对象内；
 * - 名为 `body` 的属性的对象字面量内。
 *
 * **当前无白名单**；未来若有合法「body 内带 timeoutMs」再评估加白。
 *
 * **已知不覆盖**：`const b = { timeoutMs: ... }; JSON.stringify(b)` 这种间接
 * body——AST 在 stringify 实参处只看到 Identifier，抓不到。勿用此写法绕过。
 *
 * ## T4 / T8
 * - T4：`fetchWithTimeout` 内 `timeoutMessage` 的 kind 必须来自
 *   `resolveTimeoutKind`（Identifier / CallExpression），禁止字面量 `"api"` 兜底。
 * - T8：`auth.ts` 每处 `apiFetch` 的 options 必须同层有 `TIMEOUTS.auth` + `"auth"`。
 */
import { readdirSync, readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";
import * as ts from "typescript";

import { LLM_TIMEOUT_KEYS } from "./timeouts";

const API_DIR = fileURLToPath(new URL(".", import.meta.url));
const LLM_KEYS = new Set<string>(LLM_TIMEOUT_KEYS);

function apiSourceFiles(): string[] {
  return readdirSync(API_DIR)
    .filter((n) => n.endsWith(".ts") && !n.endsWith(".test.ts"))
    .sort();
}

function parse(fileName: string, src: string): ts.SourceFile {
  return ts.createSourceFile(fileName, src, ts.ScriptTarget.Latest, true, ts.ScriptKind.TS);
}

function propName(node: ts.ObjectLiteralElementLike): string | undefined {
  if (!ts.isPropertyAssignment(node)) return undefined;
  const n = node.name;
  if (ts.isIdentifier(n) || ts.isStringLiteral(n)) return n.text;
  return undefined;
}

/** 同文件一层：Identifier → VariableDeclaration 初始化式。 */
function oneHopConstInits(sf: ts.SourceFile): Map<string, ts.Expression> {
  const map = new Map<string, ts.Expression>();
  const visit = (node: ts.Node) => {
    if (ts.isVariableDeclaration(node) && ts.isIdentifier(node.name) && node.initializer) {
      map.set(node.name.text, node.initializer);
    }
    ts.forEachChild(node, visit);
  };
  visit(sf);
  return map;
}

function resolveTimeoutsKey(
  expr: ts.Expression,
  consts: Map<string, ts.Expression>
): string | undefined {
  if (
    ts.isPropertyAccessExpression(expr) &&
    ts.isIdentifier(expr.expression) &&
    expr.expression.text === "TIMEOUTS" &&
    ts.isIdentifier(expr.name)
  ) {
    return expr.name.text;
  }
  if (ts.isIdentifier(expr)) {
    const init = consts.get(expr.text);
    if (init) return resolveTimeoutsKey(init, consts);
  }
  return undefined;
}

function siblingTimeoutKind(obj: ts.ObjectLiteralExpression): string | undefined {
  for (const el of obj.properties) {
    if (propName(el) !== "timeoutKind") continue;
    if (!ts.isPropertyAssignment(el)) continue;
    const init = el.initializer;
    if (ts.isStringLiteral(init)) return init.text;
  }
  return undefined;
}

function isJsonStringifyCall(node: ts.Node): node is ts.CallExpression {
  return (
    ts.isCallExpression(node) &&
    ts.isPropertyAccessExpression(node.expression) &&
    ts.isIdentifier(node.expression.expression) &&
    node.expression.expression.text === "JSON" &&
    node.expression.name.text === "stringify"
  );
}

/** timeoutMs 是否落在非法 body 位置（规则 B）。 */
function isInsideForbiddenBody(timeoutMsProp: ts.PropertyAssignment): boolean {
  let cur: ts.Node | undefined = timeoutMsProp.parent;
  while (cur) {
    if (ts.isObjectLiteralExpression(cur)) {
      const objParent: ts.Node = cur.parent;
      if (isJsonStringifyCall(objParent) && objParent.arguments[0] === cur) {
        return true;
      }
      if (
        ts.isPropertyAssignment(objParent) &&
        propName(objParent) === "body" &&
        objParent.initializer === cur
      ) {
        return true;
      }
    }
    cur = cur.parent;
  }
  return false;
}

function findFunction(sf: ts.SourceFile, name: string): ts.FunctionDeclaration | undefined {
  let found: ts.FunctionDeclaration | undefined;
  const visit = (node: ts.Node) => {
    if (ts.isFunctionDeclaration(node) && node.name?.text === name) {
      found = node;
      return;
    }
    ts.forEachChild(node, visit);
  };
  visit(sf);
  return found;
}

describe("超时 wiring（AST）", () => {
  it("扫描目录覆盖 api/*.ts（排除测试），避免新文件漏扫", () => {
    const files = apiSourceFiles();
    expect(files).toContain("projects.ts");
    expect(files).toContain("auth.ts");
    expect(files).toContain("http.ts");
    expect(files).toContain("misc.ts");
    expect(files).toContain("voice.ts");
    expect(files).toContain("pipeline.ts");
    expect(files.every((f) => !f.endsWith(".test.ts"))).toBe(true);
  });

  it("规则 A：LLM 档 timeoutMs 同层必须 timeoutKind: \"llm\"（含一层 const）", () => {
    const offenders: string[] = [];
    for (const file of apiSourceFiles()) {
      const src = readFileSync(`${API_DIR}${file}`, "utf8");
      const sf = parse(file, src);
      const consts = oneHopConstInits(sf);
      const visit = (node: ts.Node) => {
        if (ts.isPropertyAssignment(node) && propName(node) === "timeoutMs") {
          const key = resolveTimeoutsKey(node.initializer, consts);
          if (key && LLM_KEYS.has(key)) {
            const obj = node.parent;
            if (!ts.isObjectLiteralExpression(obj)) {
              offenders.push(`${file}: timeoutMs 不在对象字面量内`);
            } else if (siblingTimeoutKind(obj) !== "llm") {
              const { line } = sf.getLineAndCharacterOfPosition(node.getStart(sf));
              offenders.push(`${file}:${line + 1} TIMEOUTS.${key} 缺少 timeoutKind: "llm"`);
            }
          }
        }
        ts.forEachChild(node, visit);
      };
      visit(sf);
    }
    expect(offenders).toEqual([]);
  });

  it("规则 B：timeoutMs 不得写进 JSON.stringify / body 对象（当前无白名单）", () => {
    const offenders: string[] = [];
    for (const file of apiSourceFiles()) {
      const src = readFileSync(`${API_DIR}${file}`, "utf8");
      const sf = parse(file, src);
      const visit = (node: ts.Node) => {
        if (ts.isPropertyAssignment(node) && propName(node) === "timeoutMs") {
          if (isInsideForbiddenBody(node)) {
            const { line } = sf.getLineAndCharacterOfPosition(node.getStart(sf));
            offenders.push(`${file}:${line + 1} timeoutMs 落在 body / JSON.stringify 内`);
          }
        }
        ts.forEachChild(node, visit);
      };
      visit(sf);
    }
    expect(offenders).toEqual([]);
  });

  it("T4：fetchWithTimeout 的 timeoutMessage kind 来自 resolveTimeoutKind", () => {
    const src = readFileSync(`${API_DIR}http.ts`, "utf8");
    const sf = parse("http.ts", src);
    const fn = findFunction(sf, "fetchWithTimeout");
    expect(fn, "找不到 fetchWithTimeout").toBeTruthy();

    let timeoutMessageCall: ts.CallExpression | undefined;
    const visit = (node: ts.Node) => {
      if (
        ts.isCallExpression(node) &&
        ts.isIdentifier(node.expression) &&
        node.expression.text === "timeoutMessage"
      ) {
        timeoutMessageCall = node;
      }
      ts.forEachChild(node, visit);
    };
    visit(fn!);

    expect(timeoutMessageCall, "fetchWithTimeout 内未调用 timeoutMessage").toBeTruthy();
    const args = timeoutMessageCall!.arguments;
    expect(args.length, "timeoutMessage 必须传入 kind 第二参").toBeGreaterThanOrEqual(2);
    const kindArg = args[1];
    expect(ts.isStringLiteral(kindArg) && kindArg.text === "api").toBe(false);

    if (ts.isCallExpression(kindArg)) {
      expect(ts.isIdentifier(kindArg.expression)).toBe(true);
      expect((kindArg.expression as ts.Identifier).text).toBe("resolveTimeoutKind");
      return;
    }

    expect(ts.isIdentifier(kindArg)).toBe(true);
    const kindName = (kindArg as ts.Identifier).text;
    let boundToResolve = false;
    const findBind = (node: ts.Node) => {
      if (
        ts.isVariableDeclaration(node) &&
        ts.isIdentifier(node.name) &&
        node.name.text === kindName &&
        node.initializer &&
        ts.isCallExpression(node.initializer) &&
        ts.isIdentifier(node.initializer.expression) &&
        node.initializer.expression.text === "resolveTimeoutKind"
      ) {
        boundToResolve = true;
      }
      ts.forEachChild(node, findBind);
    };
    findBind(fn!);
    expect(boundToResolve, `kind 标识符 ${kindName} 应绑定 resolveTimeoutKind(...)`).toBe(true);
  });

  it("T8：auth.ts 每处 apiFetch 必须 TIMEOUTS.auth + timeoutKind \"auth\"", () => {
    const src = readFileSync(`${API_DIR}auth.ts`, "utf8");
    const sf = parse("auth.ts", src);
    const consts = oneHopConstInits(sf);
    const offenders: string[] = [];

    const visit = (node: ts.Node) => {
      if (
        ts.isCallExpression(node) &&
        ts.isIdentifier(node.expression) &&
        node.expression.text === "apiFetch"
      ) {
        const opts = node.arguments[1];
        if (!opts || !ts.isObjectLiteralExpression(opts)) {
          const { line } = sf.getLineAndCharacterOfPosition(node.getStart(sf));
          offenders.push(`auth.ts:${line + 1} apiFetch 缺少 options 对象字面量`);
          return;
        }
        let msOk = false;
        let kindOk = false;
        for (const el of opts.properties) {
          const name = propName(el);
          if (!ts.isPropertyAssignment(el)) continue;
          if (name === "timeoutMs") {
            msOk = resolveTimeoutsKey(el.initializer, consts) === "auth";
          }
          if (name === "timeoutKind" && ts.isStringLiteral(el.initializer)) {
            kindOk = el.initializer.text === "auth";
          }
        }
        if (!msOk || !kindOk) {
          const { line } = sf.getLineAndCharacterOfPosition(node.getStart(sf));
          offenders.push(
            `auth.ts:${line + 1} 缺少 timeoutMs: TIMEOUTS.auth 和/或 timeoutKind: "auth"`
          );
        }
      }
      ts.forEachChild(node, visit);
    };
    visit(sf);
    expect(offenders).toEqual([]);
  });
});
