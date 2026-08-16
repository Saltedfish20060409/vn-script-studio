/**
 * Natural-language intent routing for the studio Agent.
 * Buttons are optional shortcuts; normal speech should hit the same pipelines.
 */

export type AgentIntentKind =
  | "chapter_revise"
  | "chapter_polish"
  | "chapter_lock_name"
  | "chapter_open_review"
  | "settings_ingest"
  | "facts_scan"
  | "critique_only"
  | "pipeline"
  | "style_lint"
  | "finalize"
  | "ledger_digest"
  | "brainstorm"
  | "list_mentors"
  | "chat";

export type AgentIntent = {
  kind: AgentIntentKind;
  /** Optional note / topic forwarded to the capability */
  note?: string;
  /** Locked character/name for chapter_lock_name */
  lockName?: string;
  /** Preferred revise mode when inferred from speech */
  mode?: "cut_lecture" | "human_warmth" | "light_touch";
};

function hasAttach(n: number): boolean {
  return n > 0;
}

/** True when user wants written revision, not just opinions. */
function wantsRewrite(text: string): boolean {
  return /(回炉|整章|重写|改写|改一版|改一章|改稿|据此.*改|按.*改|帮我改|进行修改|直接改|写入正文|落到工程)/.test(
    text
  );
}

/** True when user explicitly wants discussion only. */
function wantsCritiqueOnly(text: string): boolean {
  if (wantsRewrite(text)) return false;
  return /(只要意见|先别改|先不要改|不要写入|你觉得对吗|这个分析对吗|点评一下|审稿意见|修改意见(?!.*改))/u.test(
    text
  );
}

/**
 * Infer capability from user text + attachment count.
 * Prefer specific studio pipelines over generic chat when intent is clear.
 */
export function inferAgentIntent(text: string, attachmentCount = 0): AgentIntent {
  const trimmed = (text || "").trim();
  const t = trimmed || (hasAttach(attachmentCount) ? "请阅读附件并协助整理" : "");

  if (
    /^(跑|运行)?\s*(完整)?流水线/.test(t) ||
    t.startsWith("【流水线】") ||
    /请.*(规划|计划).*(写|生成|续写)/.test(t)
  ) {
    const note = t
      .replace(/^【流水线】/, "")
      .replace(/^(跑|运行)?\s*(完整)?流水线[：:\s]*/, "")
      .trim();
    return { kind: "pipeline", note: note || t };
  }

  if (/^(文风)?体检$|^风格检查/.test(t)) return { kind: "style_lint" };
  if (/^定稿(入库)?$/.test(t)) return { kind: "finalize" };
  if (/^(更新|写入|刷新)?账本$|^章节(摘要|锚点)入库$|^入库账本$/.test(t)) {
    return { kind: "ledger_digest" };
  }

  if (/^(头脑风暴|圆桌|多视角)[：:\s]/.test(t) || t === "头脑风暴") {
    return {
      kind: "brainstorm",
      note: t.replace(/^(头脑风暴|圆桌|多视角)[：:\s]*/, "").trim(),
    };
  }

  if (/^(列出|查看)?写作导师|^导师列表$|^当前导师$/.test(t)) {
    return { kind: "list_mentors" };
  }

  // Short editorial commands (after a revise preview, or as prefs)
  if (
    /^(再润|再润一版|再软一点|再轻一点)([。！!？?\s]|$)/.test(t) ||
    /^轻润一下/.test(t)
  ) {
    return { kind: "chapter_polish", note: t, mode: "light_touch" };
  }
  if (/这段用原文|还原这段|打开对照|对照面板|挑选段落/.test(t)) {
    return { kind: "chapter_open_review", note: t };
  }
  {
    const lock = t.match(
      /别动\s*([^\s，,。！!？?]{1,12})|不要改\s*([^\s，,。！!？?]{1,12})|保留\s*([^\s，,。！!？?]{1,12})\s*的戏/
    );
    if (lock) {
      const name = (lock[1] || lock[2] || lock[3] || "").trim();
      if (name && !/结构|原文|改稿|这一章|当前章/.test(name)) {
        return { kind: "chapter_lock_name", lockName: name, note: t };
      }
    }
  }

  // Mode hints inside natural revise asks
  let mode: AgentIntent["mode"];
  if (/只去说明书|只要去说明书|别大改/.test(t)) mode = "cut_lecture";
  else if (/轻润|不改结构|少改/.test(t)) mode = "light_touch";
  else if (/人味|更有温度|毛边/.test(t)) mode = "human_warmth";

  // Chapter revise — broad NL, including "据此修改第一章" style asks
  if (
    /回炉|整章\s*(改写|重写)|章节回炉/.test(t) ||
    /(重写|改写|修改|回炉).{0,12}(第.|当前)?章/.test(t) ||
    /(第.|当前|这一)章.{0,16}(重写|改写|修改|回炉|人味)/.test(t) ||
    /改(这一章|当前章|第.章)/.test(t) ||
    /帮我改.{0,10}章/.test(t) ||
    (hasAttach(attachmentCount) &&
      /(改写|回炉|重写|改一版|改稿|人味|审稿后)/.test(t)) ||
    (t.length > 500 && wantsRewrite(t))
  ) {
    return { kind: "chapter_revise", note: t, mode };
  }

  // Settings ingest — especially with attachments
  if (
    hasAttach(attachmentCount) &&
    /(设定|圣经|bible|世界观|大纲|角色卡|人设|背景|主题|备忘|写入设定|更新设定|整理进设定|填进设定)/.test(
      t
    )
  ) {
    return { kind: "settings_ingest", note: t };
  }
  if (
    !hasAttach(attachmentCount) &&
    /(根据附件|上传的).{0,20}(设定|世界观|大纲|角色)/.test(t)
  ) {
    // No attach this turn — fall through to chat with a clear error path later
    return { kind: "chat", note: t };
  }

  // Fact / relationship / timeline scan
  if (
    /(关系图|人物关系|角色关系|时间线|扫(一扫)?事实|scan_facts|整理关系|整理时间线)/.test(
      t
    )
  ) {
    return { kind: "facts_scan", note: t };
  }

  if (
    wantsCritiqueOnly(t) ||
    (t.length > 800 && !wantsRewrite(t) && /对吗|意见|分析/.test(t))
  ) {
    return { kind: "critique_only", note: t };
  }

  // Attachment with vague "整理/根据附件" — prefer settings if looks like lore, else chat
  if (
    hasAttach(attachmentCount) &&
    /(根据附件|整理进|写入|更新工程|帮我整理)/.test(t)
  ) {
    if (/(关系|时间线)/.test(t)) return { kind: "facts_scan", note: t };
    if (/(设定|角色|世界观|大纲)/.test(t)) return { kind: "settings_ingest", note: t };
  }

  return { kind: "chat" };
}
