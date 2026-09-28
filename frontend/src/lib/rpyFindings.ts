import type { RpyFinding } from "../api/projects";

/**
 * .rpy 体检结论 → 人话（纯函数，面板只负责渲染）。
 *
 * 为什么单独一层：后端给的 `code`/`severity` 是给程序看的，界面要说清"这条会不会
 * 让玩家卡住、要不要现在处理"。分级的口径只有一处（这里），面板和状态栏不会各说各话。
 *
 * 分级口径：
 * - `error`：会在 Ren'Py 里报错或让玩家卡死（悬空跳转、未转义方括号、重名 label）
 *   —— 建议先修再下载，但**不拦下载**：作者可能就是要先拿到文件去引擎里试。
 * - `warn`：不一定坏（本章片段没有 label start、说话人 define 在别的文件里、
 *   中文 label 名被安全化），但要让人看见。
 * - `info`：只是提示（疑似 `%s` 替换形态）。
 */
export type RpyFindingLine = {
  level: "error" | "warn" | "info";
  text: string;
};

export type RpyFindingSummary = {
  /** 没有 error 级结论 */
  ok: boolean;
  errors: number;
  warnings: number;
  infos: number;
  /** 一句话结论：状态栏 / toast 用 */
  headline: string;
  /** 逐条：导出面板列表用（error 在前） */
  lines: RpyFindingLine[];
};

const ICON: Record<RpyFindingLine["level"], string> = {
  error: "⛔ ",
  warn: "⚠️ ",
  info: "· ",
};

const RANK: Record<RpyFindingLine["level"], number> = { error: 0, warn: 1, info: 2 };

/** 面板列表用：加前缀图标 + 先严重后轻微。 */
export function rpyFindingLines(
  findings: RpyFinding[] | null | undefined
): RpyFindingLine[] {
  return (findings ?? [])
    .map((f) => ({ level: f.severity, text: f.message }))
    .sort((a, b) => RANK[a.level] - RANK[b.level])
    .map((l) => ({ level: l.level, text: `${ICON[l.level]}${l.text}` }));
}

export function summarizeRpyFindings(
  findings: RpyFinding[] | null | undefined
): RpyFindingSummary {
  const list = findings ?? [];
  const errors = list.filter((f) => f.severity === "error").length;
  const warnings = list.filter((f) => f.severity === "warn").length;
  const infos = list.filter((f) => f.severity === "info").length;
  let headline: string;
  if (errors > 0) {
    headline = `导出体检：有 ${errors} 项会让 Ren'Py 报错或让玩家卡住${warnings > 0 ? `，另有 ${warnings} 项提示` : ""}`;
  } else if (warnings > 0) {
    headline = `导出体检：没有会崩的问题，有 ${warnings} 项提示`;
  } else if (infos > 0) {
    headline = `导出体检：没有会让 Ren'Py 报错的问题（${infos} 项提示）`;
  } else {
    headline = "导出体检：没有发现问题";
  }
  return {
    ok: errors === 0,
    errors,
    warnings,
    infos,
    headline,
    lines: rpyFindingLines(list),
  };
}
