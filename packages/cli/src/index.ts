#!/usr/bin/env node
import { readFileSync, writeFileSync, existsSync, mkdirSync } from "node:fs";
import { dirname, resolve } from "node:path";
import {
  createDemoProject,
  exportToRenpy,
  runAi,
  type AiAction,
  type VnProject,
} from "@vnss/core";

/** Prefer the directory where the user invoked npm (INIT_CWD), not the workspace package cwd. */
function baseCwd(): string {
  return process.env.INIT_CWD || process.cwd();
}

function abs(path: string): string {
  return resolve(baseCwd(), path);
}

function printHelp() {
  console.log(`VN Script Studio CLI

用法:
  npm run cli -- help
  npm run cli -- demo [out.json]
  npm run cli -- export <project.json> [out.rpy]
  npm run cli -- ai <project.json> <action> [--selection "..."] [--instruction "..."]

action: continue | rewrite | choices | polish | outline | character_voice

环境变量:
  DEEPSEEK_API_KEY   必填（ai 子命令）
  DEEPSEEK_BASE_URL  默认 https://api.deepseek.com
  DEEPSEEK_MODEL     默认 deepseek-chat
`);
}

function loadProject(path: string): VnProject {
  const file = abs(path);
  if (!existsSync(file)) throw new Error(`找不到文件: ${file}`);
  return JSON.parse(readFileSync(file, "utf8")) as VnProject;
}

function parseFlag(args: string[], name: string): string | undefined {
  const i = args.indexOf(name);
  if (i >= 0 && args[i + 1]) return args[i + 1];
  return undefined;
}

async function main() {
  const [, , cmd = "help", ...rest] = process.argv;

  if (cmd === "help" || cmd === "-h" || cmd === "--help") {
    printHelp();
    return;
  }

  if (cmd === "demo") {
    const out = abs(rest[0] ?? "demo-project.json");
    mkdirSync(dirname(out), { recursive: true });
    const project = createDemoProject();
    writeFileSync(out, JSON.stringify(project, null, 2), "utf8");
    console.log(`已写入示例工程: ${out}`);
    return;
  }

  if (cmd === "export") {
    const input = rest[0];
    if (!input) throw new Error("请提供 project.json 路径");
    const project = loadProject(input);
    const out = abs(rest[1] ?? `${project.title || "script"}.rpy`);
    mkdirSync(dirname(out), { recursive: true });
    writeFileSync(out, exportToRenpy(project), "utf8");
    console.log(`已导出 Ren'Py: ${out}`);
    return;
  }

  if (cmd === "ai") {
    const input = rest[0];
    const action = rest[1] as AiAction | undefined;
    if (!input || !action) {
      throw new Error("用法: ai <project.json> <action>");
    }
    const project = loadProject(input);
    const result = await runAi(
      {
        apiKey: process.env.DEEPSEEK_API_KEY ?? "",
        baseUrl: process.env.DEEPSEEK_BASE_URL,
        model: process.env.DEEPSEEK_MODEL,
      },
      {
        action,
        project,
        selection: parseFlag(rest, "--selection"),
        instruction: parseFlag(rest, "--instruction"),
      }
    );
    console.log(result.content);
    console.error(`\n# model: ${result.model}`);
    return;
  }

  throw new Error(`未知命令: ${cmd}`);
}

main().catch((err) => {
  console.error(err instanceof Error ? err.message : err);
  process.exit(1);
});
