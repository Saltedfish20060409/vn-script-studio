/**
 * One-off A/B eval: continue-writing with vs without craft skills.
 * Usage: npx tsx scripts/eval-agent-continue.ts
 * Loads key from packages/web/.env.local — never prints the key.
 */
import { readFileSync, writeFileSync } from "node:fs";
import { resolve, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import {
  applyAgentActions,
  buildAgentContext,
  buildWritingCraftPrompt,
  createDemoProject,
  projectToContext,
  runAgent,
  taskHint,
  writingSkillTitles,
} from "../src/index.js";
import type { AgentRequest, DeepSeekConfig } from "../src/index.js";

const __dirname = dirname(fileURLToPath(import.meta.url));
const root = resolve(__dirname, "../../..");
const envPath = resolve(root, "packages/web/.env.local");

function loadEnv(path: string): Record<string, string> {
  const out: Record<string, string> = {};
  try {
    const text = readFileSync(path, "utf8");
    for (const line of text.split(/\r?\n/)) {
      const m = line.match(/^\s*([A-Z0-9_]+)\s*=\s*(.*)$/);
      if (!m) continue;
      out[m[1]] = m[2].replace(/^["']|["']$/g, "").trim();
    }
  } catch {
    /* missing */
  }
  return out;
}

const CONTINUE_PROMPT = `【任务：续写】请只续写一小段可上演节拍，紧接当前章末尾的情绪与未完成的事。
硬性要求：
1) 人物设定/bio/世界观是内部参考，禁止写进对白或旁白当说明书；
2) 不要开场介绍人物是谁、有什么能力；
3) 用行动、态度、潜台词推进关系或冲突；
4) 段末留钩子，不要作者总结。
写完用 append_script 写入当前章。`;

const AGENT_SYSTEM_MINIMAL = `你是视觉小说编剧。输出单一 JSON：{"message":"...","actions":[{"op":"append_script","text":"..."}]}。
正文用 Ren'Py 风格。根据项目上下文续写。`;

async function callRaw(
  config: DeepSeekConfig,
  system: string,
  user: string
): Promise<{ message: string; actions: unknown[]; raw: string }> {
  const baseUrl = (config.baseUrl ?? "https://api.deepseek.com").replace(
    /\/$/,
    ""
  );
  const model = config.model ?? "deepseek-chat";
  const res = await fetch(`${baseUrl}/v1/chat/completions`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${config.apiKey}`,
    },
    body: JSON.stringify({
      model,
      temperature: 0.78,
      response_format: { type: "json_object" },
      messages: [
        { role: "system", content: system },
        { role: "user", content: user },
      ],
    }),
  });
  if (!res.ok) {
    throw new Error(`API ${res.status}: ${(await res.text()).slice(0, 300)}`);
  }
  const data = (await res.json()) as {
    choices?: { message?: { content?: string } }[];
  };
  const raw = data.choices?.[0]?.message?.content?.trim() ?? "{}";
  let parsed: { message?: string; actions?: unknown[] } = {};
  try {
    parsed = JSON.parse(raw.replace(/^```json\s*|\s*```$/g, ""));
  } catch {
    const s = raw.indexOf("{");
    const e = raw.lastIndexOf("}");
    if (s >= 0 && e > s) parsed = JSON.parse(raw.slice(s, e + 1));
  }
  return {
    message: parsed.message ?? "",
    actions: parsed.actions ?? [],
    raw,
  };
}

function extractScript(actions: unknown[]): string {
  const parts: string[] = [];
  for (const a of actions) {
    if (
      a &&
      typeof a === "object" &&
      "op" in a &&
      (a as { op: string }).op === "append_script" &&
      "text" in a
    ) {
      parts.push(String((a as { text: string }).text));
    }
  }
  return parts.join("\n\n");
}

/** Heuristic rubric 0–2 each; higher = better craft */
function scoreScript(text: string, chapterTail: string): Record<string, number> {
  const t = text.trim();
  if (!t || t.length < 20) {
    return {
      anti_exposition: 0,
      continuity: 0,
      voice_contrast: 0,
      pacing_hook: 0,
      sensory: 0,
      conflict_subtext: 0,
      anti_cliche: 0,
      delivered_script: 0,
    };
  }
  const lower = t.toLowerCase();
  let antiExpo = 2;
  const dumpPatterns = [
    /图书管理员/,
    /24\s*岁/,
    /失踪三周/,
    /身份不明/,
    /我是林夏/,
    /我叫周屿/,
    /拥有.*能力/,
    /世界观/,
    /好感度/,
    /作为一名/,
  ];
  for (const p of dumpPatterns) {
    if (p.test(t)) antiExpo = Math.max(0, antiExpo - 1);
  }
  if (/姐姐失踪/.test(t) && /介绍|其实|告诉你/.test(t)) {
    antiExpo = Math.max(0, antiExpo - 1);
  }

  let continuity = 1;
  if (/伞|雨|延误|那个人|失踪/.test(t)) continuity = 2;
  if (/图书馆|设定|角色卡/.test(t) && !/伞|雨/.test(chapterTail.slice(-80))) {
    continuity = Math.max(0, continuity - 1);
  }

  let voice = 1;
  const hasLin = /linxia|林夏/i.test(t);
  const hasZhou = /zhouyu|周屿/i.test(t);
  if (hasLin && hasZhou) voice = 2;
  if (/微微一笑|不禁|涌上心头|命运的齿轮/.test(t)) voice = Math.max(0, voice - 1);

  let pacing = 1;
  const lines = t.split(/\n/).filter((l) => l.trim()).length;
  if (lines >= 4 && lines <= 28) pacing = 2;
  if (lines > 40) pacing = 0;
  if (/总之|由此可见|他们开始了/.test(t)) pacing = Math.max(0, pacing - 1);

  let sensory = /雨|伞|湿|亮|屏|广播|冷|声/.test(t) ? 2 : 1;
  let conflict = /试探|戒|笑|回避|问|不答|沉默|为什么|谁/.test(t) ? 2 : 1;
  let cliche =
    (/仿佛|不禁|微微|深深地|复杂的眼神/.test(t) ? 0 : 1) +
    (!/空气突然/.test(t) ? 1 : 0);

  return {
    anti_exposition: antiExpo,
    continuity,
    voice_contrast: voice,
    pacing_hook: pacing,
    sensory: sensory,
    conflict_subtext: conflict,
    anti_cliche: cliche,
    delivered_script: 2,
  };
}

function total(scores: Record<string, number>): number {
  return Object.values(scores).reduce((a, b) => a + b, 0);
}

async function main() {
  const env = {
    ...loadEnv(envPath),
    ...process.env,
  };
  const apiKey = env.DEEPSEEK_API_KEY || "";
  if (!apiKey || apiKey.includes("your-key")) {
    console.error("No DEEPSEEK_API_KEY in packages/web/.env.local");
    process.exit(1);
  }
  const config: DeepSeekConfig = {
    apiKey,
    baseUrl: env.DEEPSEEK_BASE_URL,
    model: env.DEEPSEEK_MODEL || "deepseek-chat",
  };

  const project = createDemoProject();
  const chapterId = project.chapters[0].id;
  const chapterTail =
    "周屿: 那个人……也喜欢在这种天气失踪吗？";

  console.log("Model:", config.model);
  console.log("A) With craft skills (runAgent)...");
  const req: AgentRequest = {
    project,
    chapterId,
    task: "continue",
    messages: [{ role: "user", content: CONTINUE_PROMPT }],
  };
  const withSkills = await runAgent(config, req);
  const withText = extractScript(withSkills.actions as unknown[]);
  console.log(
    "A actions sample:",
    JSON.stringify(withSkills.actions).slice(0, 500)
  );
  const withApplied = applyAgentActions(project, withSkills.actions, {
    defaultChapterId: chapterId,
  });

  console.log("B) Baseline dump context, no skills...");
  const baselineSystem = `${AGENT_SYSTEM_MINIMAL}\n\n作品上下文:\n${projectToContext(project, 14000)}\n\n${taskHint("continue")}`;
  const baseline = await callRaw(config, baselineSystem, CONTINUE_PROMPT);
  console.log("B actions sample:", JSON.stringify(baseline.actions).slice(0, 500));
  const baseText = extractScript(baseline.actions);

  // C) Same retrieval context as studio, but WITHOUT craft skills block
  console.log("C) Retrieval context, no craft skills...");
  const ctx = buildAgentContext(project, {
    chapterId,
    task: "continue",
    userMessage: CONTINUE_PROMPT,
  });
  const noCraftSystem = `你是「VN Script Studio」责编。输出单一 JSON：{"message":"...","actions":[...]}。
可用 append_script。设定在上下文中，请续写。

${taskHint("continue")}

—— 作品上下文 ——
${ctx.text}`;
  const noCraft = await callRaw(config, noCraftSystem, CONTINUE_PROMPT);
  const noCraftText = extractScript(noCraft.actions);
  console.log("C actions sample:", JSON.stringify(noCraft.actions).slice(0, 500));

  const scoreA = scoreScript(
    withText || withSkills.message,
    chapterTail
  );
  const scoreB = scoreScript(baseText || baseline.message, chapterTail);
  const scoreC = scoreScript(noCraftText || noCraft.message, chapterTail);

  const report = {
    at: new Date().toISOString(),
    model: config.model,
    chapterTail,
    skillsInjected: writingSkillTitles("continue"),
    skillCount: writingSkillTitles("continue").length,
    contextMeta: withSkills.contextMeta,
    withSkills: {
      message: withSkills.message,
      script: withText,
      actionsJson: withSkills.actions,
      actionOps: withSkills.actions.map((a) =>
        a && typeof a === "object" && "op" in a ? (a as { op: string }).op : null
      ),
      applied: withApplied.applied,
      scores: scoreA,
      total: total(scoreA),
      max: 14,
    },
    baselineFullDump: {
      message: baseline.message,
      script: baseText,
      actionOps: (baseline.actions as { op?: string }[]).map((a) => a.op),
      scores: scoreB,
      total: total(scoreB),
      max: 14,
    },
    retrievalNoCraft: {
      message: noCraft.message,
      script: noCraftText,
      actionOps: (noCraft.actions as { op?: string }[]).map((a) => a.op),
      scores: scoreC,
      total: total(scoreC),
      max: 14,
    },
    deltas: {
      skills_vs_dump: total(scoreA) - total(scoreB),
      skills_vs_retrieval: total(scoreA) - total(scoreC),
    },
  };

  const outPath = resolve(root, "packages/core/scripts/eval-continue-result.json");
  writeFileSync(outPath, JSON.stringify(report, null, 2), "utf8");
  console.log("Wrote", outPath);
  console.log(
    "A(skills)",
    report.withSkills.total,
    "/16  B(dump)",
    report.baselineFullDump.total,
    "/16  C(retrieval)",
    report.retrievalNoCraft.total,
    "/16"
  );
  console.log("deltas", JSON.stringify(report.deltas));

  const craft = buildWritingCraftPrompt("continue");
  console.log("Craft prompt chars:", craft.length, "Context chars:", ctx.charsUsed);
}

main().catch((e) => {
  console.error(e instanceof Error ? e.message : e);
  process.exit(1);
});
