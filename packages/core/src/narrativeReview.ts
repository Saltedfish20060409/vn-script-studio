import type {
  AgentAction,
  AgentTaskKind,
  Character,
  VnProject,
} from "./types.js";
import type { DeepSeekConfig } from "./ai.js";
import {
  lintHasBlockers,
  lintNarrativeDraft,
  type NarrativeLintIssue,
} from "./narrativeLint.js";

export type SelfReviewPreference = "auto" | "on" | "off";

export interface NarrativeReviewResult {
  ok: boolean;
  issues: string[];
  revisedText?: string;
  /** short note for UI */
  note: string;
  /** rule-engine hits */
  lintIssues?: NarrativeLintIssue[];
}

const REVIEW_TASKS: AgentTaskKind[] = [
  "continue",
  "scene",
  "rewrite",
  "polish",
];

/** Adversarial critic: assume draft is flawed; different role from writer */
const CRITIC_SYSTEM = `你是「挑错责编」，不是作者本人。默认假设草稿有社交/叙事问题，你的KPI是找出问题；只有确实干净才 ok=true。

禁止：为作者辩护、把「推进剧情需要」当成连问盘人的借口、只夸氛围不查对白。

硬性否决项（命中任一项 → ok 必须 false，并给 revised_text）：
- 同一角色本拍主动追问≥2次
- 问→答→再问的乒乓推进
- 陌生人/克制人设过熟倾诉或无偿讲解完整路线
- 设定/履历宣讲

审查清单：
1. 社交温度与常理
2. 盘问串 / 问答乒乓
3. 信息动机（失言/恐惧/炫耀 vs 被审讯）
4. 惜话与沉默是否被写满
5. 是否违背 voice
6. 能否用环境/动作替代多余对白

若下方提供「规则引擎已检出」，那些项视为已坐实，必须改写，不得 ok=true 无视。

输出唯一 JSON：
{
  "ok": false,
  "issues": ["..."],
  "revised_text": "改写后的完整片段（与草稿同风格）",
  "note": "一句话"
}

ok=true 时 issues 应为空且可省略 revised_text。改写保留钩子与推进意图，对白更少更尖。`;

export function shouldSelfReview(
  task: AgentTaskKind,
  preference: SelfReviewPreference = "auto"
): boolean {
  if (preference === "off") return false;
  if (preference === "on") return REVIEW_TASKS.includes(task);
  // auto: writing tasks that produce script
  return REVIEW_TASKS.includes(task);
}

export function extractScriptFromActions(actions: AgentAction[]): {
  op: "append_script" | "replace_script" | null;
  text: string;
  index: number;
} {
  for (let i = 0; i < actions.length; i++) {
    const a = actions[i] as AgentAction & { text?: string };
    if (
      (a.op === "append_script" || a.op === "replace_script") &&
      typeof a.text === "string" &&
      a.text.trim()
    ) {
      return { op: a.op, text: a.text, index: i };
    }
  }
  return { op: null, text: "", index: -1 };
}

function parseReviewJson(raw: string): NarrativeReviewResult {
  let text = raw.trim();
  const fence = text.match(/```(?:json)?\s*([\s\S]*?)```/);
  if (fence) text = fence[1].trim();
  const start = text.indexOf("{");
  const end = text.lastIndexOf("}");
  if (start >= 0 && end > start) text = text.slice(start, end + 1);
  try {
    const parsed = JSON.parse(text) as {
      ok?: boolean;
      issues?: unknown;
      revised_text?: unknown;
      revisedText?: unknown;
      note?: unknown;
    };
    const issues = Array.isArray(parsed.issues)
      ? parsed.issues.map((x) => String(x)).filter(Boolean)
      : [];
    const revisedRaw =
      typeof parsed.revised_text === "string"
        ? parsed.revised_text
        : typeof parsed.revisedText === "string"
          ? parsed.revisedText
          : "";
    const revised = revisedRaw.trim();
    const note =
      typeof parsed.note === "string" && parsed.note.trim()
        ? parsed.note.trim()
        : "";

    const fail =
      parsed.ok === false || (issues.length > 0 && revised.length > 0);
    if (fail && revised) {
      return {
        ok: false,
        issues,
        revisedText: revised,
        note: note || `自检未通过（${issues.slice(0, 2).join("；") || "需改写"}）`,
      };
    }
    return {
      ok: true,
      issues,
      note: note || (issues.length ? `自检通过（备注：${issues[0]}）` : "自检通过"),
    };
  } catch {
    return { ok: true, issues: [], note: "自检解析失败，沿用原稿" };
  }
}

function characterVoiceBrief(project: VnProject): string {
  return project.characters
    .slice(0, 8)
    .map(
      (c: Character) =>
        `- ${c.displayName}: voice=${c.voice || "（无）"} | bio要点=${(c.bio || "").slice(0, 60)}`
    )
    .join("\n");
}

/** Second-pass critic: prefers a *different* model/config when provided. */
export async function runNarrativeSelfReview(
  config: DeepSeekConfig,
  opts: {
    draft: string;
    task: AgentTaskKind;
    project: VnProject;
    chapterTail?: string;
    /** Precomputed rule-engine issues */
    lintIssues?: NarrativeLintIssue[];
  }
): Promise<NarrativeReviewResult> {
  const lintIssues = opts.lintIssues ?? lintNarrativeDraft(opts.draft);
  const lintMsgs = lintIssues.map((i) => `[${i.severity}] ${i.message}`);

  if (!config.apiKey || config.apiKey.includes("your-key")) {
    // No LLM critic — still block on rule engine
    if (lintHasBlockers(lintIssues)) {
      return {
        ok: false,
        issues: lintMsgs,
        lintIssues,
        note: "规则引擎未通过（无责编模型可改写，请人工改或配置 Key）",
      };
    }
    return {
      ok: true,
      issues: lintMsgs,
      lintIssues,
      note: "规则引擎通过；无 Key 跳过模型责编",
    };
  }

  const baseUrl = (config.baseUrl ?? "https://api.deepseek.com").replace(
    /\/$/,
    ""
  );
  const model = config.model ?? "deepseek-chat";

  const user = [
    `任务类型: ${opts.task}`,
    opts.chapterTail ? `章末前文钩子:\n${opts.chapterTail}` : "",
    `角色声线（须尊重）:\n${characterVoiceBrief(opts.project) || "（无）"}`,
    lintMsgs.length
      ? `规则引擎已检出（必须处理，不得无视）:\n${lintMsgs.map((m) => `- ${m}`).join("\n")}`
      : "规则引擎未检出硬伤；仍请对抗式审查社交常理。",
    `草稿:\n${opts.draft}`,
    "请输出 JSON。若规则引擎有 error 级问题，ok 必须为 false 并给出 revised_text。",
  ]
    .filter(Boolean)
    .join("\n\n");

  const res = await fetch(`${baseUrl}/v1/chat/completions`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${config.apiKey}`,
    },
    body: JSON.stringify({
      model,
      temperature: 0.25,
      response_format: { type: "json_object" },
      messages: [
        { role: "system", content: CRITIC_SYSTEM },
        { role: "user", content: user },
      ],
    }),
  });

  if (!res.ok) {
    if (lintHasBlockers(lintIssues)) {
      return {
        ok: false,
        issues: lintMsgs,
        lintIssues,
        note: `责编模型失败(${res.status})；规则引擎未通过`,
      };
    }
    return {
      ok: true,
      issues: [],
      lintIssues,
      note: `责编请求失败(${res.status})，规则无硬伤，沿用原稿`,
    };
  }

  const data = (await res.json()) as {
    choices?: { message?: { content?: string } }[];
  };
  const content = data.choices?.[0]?.message?.content?.trim() ?? "{}";
  const reviewed = parseReviewJson(content);
  reviewed.lintIssues = lintIssues;

  // If lint blockers exist but critic wrongly approved without revise, force fail note
  if (lintHasBlockers(lintIssues) && reviewed.ok && !reviewed.revisedText) {
    return {
      ok: false,
      issues: [...lintMsgs, ...reviewed.issues],
      lintIssues,
      revisedText: undefined,
      note: "规则引擎未通过且责编未给出改写，沿用原稿但标记风险",
    };
  }

  // Merge lint messages into issues for transparency
  if (lintMsgs.length) {
    reviewed.issues = [...new Set([...lintMsgs, ...reviewed.issues])];
  }
  if (!reviewed.ok && reviewed.revisedText) {
    reviewed.note =
      reviewed.note ||
      (lintHasBlockers(lintIssues)
        ? "规则+责编：已改写"
        : "责编自检：已改写");
  }
  return reviewed;
}

export function applyReviewedScript(
  actions: AgentAction[],
  index: number,
  revisedText: string
): AgentAction[] {
  return actions.map((a, i) => {
    if (i !== index) return a;
    if (a.op === "append_script" || a.op === "replace_script") {
      return { ...a, text: revisedText };
    }
    return a;
  });
}

/** Rough chapter tail for critic context */
export function chapterTailPlain(
  project: VnProject,
  chapterId?: string,
  maxChars = 600
): string {
  const ch =
    project.chapters.find((c) => c.id === chapterId) ?? project.chapters[0];
  if (!ch) return "";
  const lines: string[] = [];
  for (const b of ch.blocks) {
    if (b.type === "dialogue") {
      const name =
        project.characters.find((c) => c.id === b.characterId)?.displayName ??
        b.characterId;
      lines.push(`${name}: ${b.text}`);
    } else if (b.type === "narration") {
      lines.push(`旁白: ${b.text}`);
    } else if (b.type === "raw") {
      lines.push(b.code);
    }
  }
  const plain = lines.join("\n");
  if (plain.length <= maxChars) return plain;
  return plain.slice(plain.length - maxChars);
}
