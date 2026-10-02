/**
 * ADR 0001 P4/P5：意图 → Writing Turn capability / write_op。
 *
 * P5：polish / expand / condense / style_transfer 进 turn；
 * chapter_revise 仍旁路多窗口作业；chapter_polish 默认走 turn polish。
 */

import type { AgentIntent } from "./agentIntent";

export type TurnCapability = "write" | "critique" | "ingest" | "chat";
export type TurnWriteOp =
  | "continue"
  | "rewrite"
  | "polish"
  | "expand"
  | "condense"
  | "style_transfer";

export type TurnRoute = {
  capability: TurnCapability;
  writeOp?: TurnWriteOp;
  /** 仍走旧路径（chapter-revise 作业等），不经 turn */
  bypassTurn?: boolean;
};

/**
 * 从用户话术推断 P5 write_op（显式优先于 continue/rewrite 缺省）。
 * 无命中返回 null，由调用方按选区落 continue/rewrite。
 */
export function inferWriteOpFromText(text: string): TurnWriteOp | null {
  const t = (text || "").trim();
  if (!t) return null;
  if (
    /(风格迁移|换成.{0,12}风格|改成.{0,12}风格|文风改成|迁移成.{0,8}风格|按.{0,12}风格改)/.test(
      t
    )
  ) {
    return "style_transfer";
  }
  if (/(缩写|压缩|精简|删繁就简|缩短|写短一点|压短)/.test(t)) {
    return "condense";
  }
  if (/(扩写|写细|加长|展开写|写得更细|加细节|铺开写)/.test(t)) {
    return "expand";
  }
  if (
    /(润色|再润|轻润|润一版|润一下|润润)/.test(t) &&
    !/(扩写|缩写|风格迁移)/.test(t)
  ) {
    return "polish";
  }
  return null;
}

/**
 * 把 inferAgentIntent 的结果映射到 turn 路由。
 * @param selection 当前编辑器选区；有选区且 write 缺省时默认 rewrite
 * @param instruction 可选：用于识别 polish/expand/condense/style_transfer
 */
export function mapIntentToTurnRoute(
  intent: Pick<AgentIntent, "kind">,
  opts: { selection?: string | null; instruction?: string | null } = {}
): TurnRoute {
  const hasSelection = Boolean((opts.selection || "").trim());
  const fromText = inferWriteOpFromText(opts.instruction || "");

  switch (intent.kind) {
    case "write_to_script":
      return {
        capability: "write",
        writeOp:
          fromText || (hasSelection ? "rewrite" : "continue"),
      };
    case "targeted_revise":
      return {
        capability: "write",
        writeOp: fromText === "polish" ? "polish" : "rewrite",
      };
    case "critique_only":
      return { capability: "critique" };
    case "settings_ingest":
      return { capability: "ingest" };
    case "chat":
      return { capability: "chat" };
    case "chapter_polish":
      return { capability: "write", writeOp: "polish" };
    case "chapter_revise":
      // 多窗口作业旁路保留
      return { capability: "write", writeOp: "rewrite", bypassTurn: true };
    default:
      // 其它特殊意图（pipeline / finalize / …）由 AgentChat 自有分支处理
      return { capability: "chat" };
  }
}

/** 轻确认写入作用域（与 AgentTurnIn.scope 对齐）。 */
export type WriteDraftScope =
  | "chapter_append"
  | "selection_replace"
  | "chapter_replace";

/**
 * 默认作用域推断（与 P3 handleConfirmWriteDraft 一致），供气泡控件初值。
 */
export function inferDefaultWriteScope(opts: {
  originalText: string;
  revisedText: string;
  selection?: string | null;
}): WriteDraftScope {
  const original = (opts.originalText || "").trim();
  const piece = (opts.revisedText || "").trim();
  if (!original) return "chapter_replace";
  const sel = (opts.selection || "").trim();
  if (sel && original.includes(sel)) return "selection_replace";
  const headN = Math.min(80, original.length, piece.length);
  const looksFullRewrite =
    headN > 0 &&
    piece.length >= original.length * 0.8 &&
    piece.slice(0, headN) === original.slice(0, headN);
  return looksFullRewrite ? "chapter_replace" : "chapter_append";
}

/** 按作用域把草稿合成最终正文。 */
export function applyWriteDraftScope(opts: {
  scope: WriteDraftScope;
  originalText: string;
  revisedText: string;
  selection?: string | null;
}): string {
  const original = (opts.originalText || "").trim();
  const piece = (opts.revisedText || "").trim();
  if (!original) return piece;
  if (opts.scope === "chapter_replace") return piece;
  if (opts.scope === "chapter_append") return `${original}\n\n${piece}`;
  const sel = (opts.selection || "").trim();
  if (sel && original.includes(sel)) return original.replace(sel, piece);
  // 选区不可用时降级为追加，避免 silently wipe
  return `${original}\n\n${piece}`;
}

export function selectionReplaceEnabled(
  originalText: string,
  selection?: string | null
): boolean {
  const original = (originalText || "").trim();
  const sel = (selection || "").trim();
  return Boolean(sel && original.includes(sel));
}
