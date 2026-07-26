import type {
  AgentAction,
  AgentChatMessage,
  AgentRequest,
  AgentResponse,
  Character,
  Location,
  LocationRelation,
  ScriptBlock,
  VnProject,
} from "./types.js";
import type { DeepSeekConfig } from "./ai.js";
import {
  buildAgentContext,
  inferAgentTask,
  isAgentTask,
  taskHint,
} from "./agentContext.js";
import {
  buildWritingCraftPrompt,
  selectCraftMode,
} from "./writingCraft.js";
import {
  applyReviewedScript,
  chapterTailPlain,
  extractScriptFromActions,
  runNarrativeSelfReview,
  shouldSelfReview,
} from "./narrativeReview.js";
import {
  lintHasBlockers,
  lintNarrativeDraft,
} from "./narrativeLint.js";
import { newLocationLink, uid } from "./project.js";

const AGENT_SYSTEM = `你是「VN Script Studio」的驻场轻小说 / 视觉小说责编（Editor Agent）。

你不是通用聊天框：你服务于**这一部作品**的专业化写作任务（续写、改写、润色、分支、大纲、语气审校、一致性排查、写一场戏）。

身份：
- 轻小说责编 + VN 脚本顾问：把故事写好是第一位；增删角色/地点/章节是创作手段。
- 上下文由工作室检索拼装（当前章优先、相关设定/角色/地点/变量、他章摘要），不是全库倾倒——缺材料时主动问用户或请其切换章节。

关键（务必遵守）：
- 作品档案里的人设 / bible / 变量 = **内部参考**，用来指导「怎么演」，禁止整段搬进对白或旁白当说明书。
- 续写/写戏时：叙事逻辑与节奏 > 展示设定完整度。受众要沉浸，不要设定展柜。
- 若工艺 Skills 与「写全上下文」冲突，以工艺 Skills 为准。

创作原则：
1. 先对齐任务模式、章末节拍与人设语气，再给方案或可上演正文。
2. 正文优先 Ren'Py 可粘贴风格：旁白 "..."、对白 name "..."、必要时 scene/show/menu/jump/label。
3. 审稿要具体到句子：口气崩、信息倾倒、假选择、地点氛围不一致，并给改法。
4. 尊重 Variables（好感/flag）与 Sprites 表情槽；需要时可在对白旁注释 show 标签。
5. 纯讨论/大纲/点评：actions=[]，精华放 message。
6. 快捷任务若已要求写入，或用户说「写入/追加/应用/创建…」，再用 actions。
7. 禁止擅自大删既有剧情；replace_script 仅在用户明确要求整章重写时。
8. message 里可先用一两句说明本段「接了什么节拍、故意没写哪些设定」；正文仍走 actions。

输出（单一 JSON，无 markdown 围栏）：
{
  "message": "中文：讨论/审稿/大纲；正文要点可先展示",
  "actions": []
}

可用 op（字段名必须是 "op"，不要写成 action）：
add_character / update_character / delete_character /
add_location / update_location / delete_location /
add_location_link / delete_location_link /
add_chapter / delete_chapter / rename_chapter /
append_script { "op":"append_script", "chapterRef"?, "text" } /
replace_script { "op":"replace_script", "chapterRef"?, "text" } /
update_bible / update_meta

defineName：英文小写+数字下划线。relation：adjacent|contains|inside|above|below|leads_to|visible_from|other。`;

function slugDefine(name: string): string {
  const ascii = name
    .normalize("NFKD")
    .replace(/[^\w]+/g, "_")
    .replace(/^_+|_+$/g, "")
    .toLowerCase();
  if (ascii && /^[a-z]/.test(ascii)) return ascii.slice(0, 32);
  return `char_${Date.now().toString(36)}`;
}

function findCharacter(project: VnProject, ref: string): Character | undefined {
  const r = ref.trim().toLowerCase();
  return project.characters.find(
    (c) =>
      c.id.toLowerCase() === r ||
      c.defineName.toLowerCase() === r ||
      c.displayName.toLowerCase() === r
  );
}

function findLocation(project: VnProject, ref: string): Location | undefined {
  const r = ref.trim().toLowerCase();
  return (project.locations ?? []).find(
    (l) =>
      l.id.toLowerCase() === r ||
      l.name.toLowerCase() === r ||
      (l.imageTag && l.imageTag.toLowerCase() === r)
  );
}

function findChapter(project: VnProject, ref?: string) {
  if (!ref) return project.chapters[0];
  const r = ref.trim().toLowerCase();
  return (
    project.chapters.find(
      (c) => c.id.toLowerCase() === r || c.title.toLowerCase() === r
    ) ?? project.chapters[0]
  );
}

function textToBlocks(text: string): ScriptBlock[] {
  const lines = text.replace(/\r\n/g, "\n").split("\n");
  return lines
    .map((line): ScriptBlock | null => {
      const t = line.trimEnd();
      if (!t.trim()) return null;
      return { type: "raw", code: t };
    })
    .filter((b): b is ScriptBlock => b !== null);
}

function coerceScriptText(value: unknown): string | undefined {
  if (typeof value === "string") return value;
  if (typeof value === "number" || typeof value === "boolean") {
    return String(value);
  }
  if (Array.isArray(value)) {
    return value
      .map((line) => (typeof line === "string" ? line : JSON.stringify(line)))
      .join("\n");
  }
  if (value && typeof value === "object") {
    const o = value as Record<string, unknown>;
    for (const key of ["text", "content", "script", "body", "code"]) {
      const inner = coerceScriptText(o[key]);
      if (inner !== undefined) return inner;
    }
  }
  return undefined;
}

function normalizeAgentActions(raw: unknown): AgentAction[] {
  if (!Array.isArray(raw)) return [];
  const out: AgentAction[] = [];
  for (const item of raw) {
    if (!item || typeof item !== "object") continue;
    const obj = { ...(item as Record<string, unknown>) };
    // Models drift: action / type / name / operation instead of op
    if (typeof obj.op !== "string") {
      for (const key of ["action", "type", "name", "operation", "command"]) {
        if (typeof obj[key] === "string") {
          obj.op = obj[key];
          break;
        }
      }
    }
    for (const key of ["action", "type", "operation", "command"]) {
      if (key !== "op") delete obj[key];
    }
    if (typeof obj.op !== "string") continue;
    obj.op = String(obj.op).trim();

    if (obj.op === "append_script" || obj.op === "replace_script") {
      const text = coerceScriptText(
        obj.text ?? obj.content ?? obj.script ?? obj.body ?? obj.code
      );
      if (text !== undefined) obj.text = text;
      // chapter title sometimes sent as chapter / chapterId / chapter_name
      if (obj.chapterRef == null) {
        const ref =
          obj.chapter ?? obj.chapterId ?? obj.chapter_name ?? obj.chapterTitle;
        if (typeof ref === "string") obj.chapterRef = ref;
      }
    }

    out.push(obj as unknown as AgentAction);
  }
  return out;
}

function parseAgentJson(raw: string): { message: string; actions: AgentAction[] } {
  let text = raw.trim();
  const fence = text.match(/```(?:json)?\s*([\s\S]*?)```/);
  if (fence) text = fence[1].trim();
  const start = text.indexOf("{");
  const end = text.lastIndexOf("}");
  if (start >= 0 && end > start) text = text.slice(start, end + 1);
  const parsed = JSON.parse(text) as {
    message?: string;
    actions?: unknown;
  };
  return {
    message: parsed.message?.trim() || "已处理。",
    actions: normalizeAgentActions(parsed.actions),
  };
}

export async function runAgent(
  config: DeepSeekConfig,
  request: AgentRequest
): Promise<AgentResponse> {
  if (!config.apiKey || config.apiKey.includes("your-key")) {
    throw new Error("请先配置 DEEPSEEK_API_KEY");
  }
  const baseUrl = (config.baseUrl ?? "https://api.deepseek.com").replace(
    /\/$/,
    ""
  );
  const model = config.model ?? "deepseek-chat";

  const lastUser = [...request.messages]
    .reverse()
    .find((m) => m.role === "user")?.content;

  const task = isAgentTask(request.task)
    ? request.task
    : inferAgentTask(lastUser ?? "");

  const craft = selectCraftMode({
    task,
    userMessage: lastUser,
    project: request.project,
    chapterId: request.chapterId,
    preference: request.craftMode,
  });

  const ctx = buildAgentContext(request.project, {
    chapterId: request.chapterId,
    selection: request.selection,
    userMessage: lastUser,
    task,
    maxChars: 12000,
    chatMemory: request.chatMemory,
  });

  const history = (
    request.messages.length
      ? request.messages
      : []
  )
    .slice(-20)
    .map((m: AgentChatMessage) => ({
      role: m.role,
      content: m.content,
    }));

  const temperature =
    craft.mode === "off"
      ? 0.82
      : task === "polish" || task === "voice" || task === "consistency"
        ? 0.55
        : task === "outline"
          ? 0.7
          : craft.mode === "lite"
            ? 0.72
            : 0.78;

  const craftBlock = buildWritingCraftPrompt(task, craft.mode);

  const res = await fetch(`${baseUrl}/v1/chat/completions`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${config.apiKey}`,
    },
    body: JSON.stringify({
      model,
      temperature,
      response_format: { type: "json_object" },
      messages: [
        {
          role: "system",
          content: `${AGENT_SYSTEM}\n\n${taskHint(task)}\n\n${craftBlock}\n\n—— 作品上下文（检索拼装；人设/设定为内部参考）——\n${ctx.text}`,
        },
        ...history,
      ],
    }),
  });

  if (!res.ok) {
    const errText = await res.text();
    throw new Error(`DeepSeek API ${res.status}: ${errText.slice(0, 400)}`);
  }

  const data = (await res.json()) as {
    choices?: { message?: { content?: string } }[];
    model?: string;
  };
  const content = data.choices?.[0]?.message?.content?.trim() ?? "{}";
  let parsed = parseAgentJson(content);

  let reviewNote = "";
  const reviewPref = request.selfReview ?? "auto";
  if (shouldSelfReview(task, reviewPref)) {
    const scriptHit = extractScriptFromActions(parsed.actions);
    if (scriptHit.op && scriptHit.text) {
      const lintIssues = lintNarrativeDraft(scriptHit.text);
      const criticConfig = {
        apiKey:
          request.criticApiKey ||
          config.apiKey,
        baseUrl: request.criticApiBaseUrl || config.baseUrl,
        model: request.criticApiModel || config.model,
      };
      const review = await runNarrativeSelfReview(criticConfig, {
        draft: scriptHit.text,
        task,
        project: request.project,
        chapterTail: chapterTailPlain(request.project, request.chapterId),
        lintIssues,
      });
      reviewNote = review.note;
      if (!review.ok && review.revisedText) {
        parsed = {
          message: parsed.message,
          actions: applyReviewedScript(
            parsed.actions,
            scriptHit.index,
            review.revisedText
          ),
        };
        if (review.issues.length) {
          parsed.message = `${parsed.message}\n\n（自检修订：${review.issues.slice(0, 3).join("；")}）`;
        }
      } else if (lintHasBlockers(lintIssues) && !review.revisedText) {
        reviewNote =
          reviewNote ||
          `规则未过：${lintIssues
            .filter((i) => i.severity === "error")
            .map((i) => i.message)
            .slice(0, 2)
            .join("；")}`;
      }
    }
  }

  return {
    message: parsed.message,
    actions: parsed.actions,
    model: data.model ?? model,
    contextMeta: {
      task: ctx.task,
      charsUsed: ctx.charsUsed,
      craftMode: craft.mode,
      craftReason: craft.reason,
      included: ctx.included,
      selfReview: reviewNote || undefined,
    },
  };
}

export interface ApplyAgentResult {
  project: VnProject;
  applied: string[];
  skipped: string[];
}

/** Apply agent actions immutably to a project. */
export function applyAgentActions(
  project: VnProject,
  actions: AgentAction[],
  opts?: { defaultChapterId?: string }
): ApplyAgentResult {
  let next: VnProject = {
    ...project,
    characters: [...project.characters],
    chapters: project.chapters.map((c) => ({
      ...c,
      blocks: [...c.blocks],
    })),
    locations: [...(project.locations ?? [])],
    locationLinks: [...(project.locationLinks ?? [])],
    characterLinks: [...(project.characterLinks ?? [])],
    timeline: [...(project.timeline ?? [])],
    bible: { ...(project.bible ?? {}) },
  };
  const applied: string[] = [];
  const skipped: string[] = [];

  for (const action of actions) {
    try {
      switch (action.op) {
        case "add_character": {
          if (!action.displayName?.trim()) {
            skipped.push("add_character 缺少 displayName");
            break;
          }
          const defineName =
            action.defineName?.replace(/[^A-Za-z0-9_]/g, "") ||
            slugDefine(action.displayName);
          const id = defineName;
          if (next.characters.some((c) => c.id === id || c.defineName === defineName)) {
            skipped.push(`角色已存在: ${action.displayName}`);
            break;
          }
          next.characters.push({
            id,
            defineName,
            displayName: action.displayName,
            color: action.color ?? "#6b7280",
            voice: action.voice ?? "",
            bio: action.bio ?? "",
            relationships: action.relationships ?? "",
          });
          applied.push(`添加角色 ${action.displayName}`);
          break;
        }
        case "update_character": {
          const ch = findCharacter(next, action.ref);
          if (!ch) {
            skipped.push(`未找到角色: ${action.ref}`);
            break;
          }
          next.characters = next.characters.map((c) =>
            c.id === ch.id ? { ...c, ...action.patch } : c
          );
          applied.push(`更新角色 ${ch.displayName}`);
          break;
        }
        case "delete_character": {
          const ch = findCharacter(next, action.ref);
          if (!ch) {
            skipped.push(`未找到角色: ${action.ref}`);
            break;
          }
          next.characters = next.characters.filter((c) => c.id !== ch.id);
          next.characterLinks = (next.characterLinks ?? []).filter(
            (l) => l.fromId !== ch.id && l.toId !== ch.id
          );
          applied.push(`删除角色 ${ch.displayName}`);
          break;
        }
        case "add_location": {
          const id = uid("loc");
          const n = (next.locations?.length ?? 0) + 1;
          next.locations = [
            ...(next.locations ?? []),
            {
              id,
              name: action.name,
              imageTag: action.imageTag,
              description: action.description,
              tags: action.tags,
              mapX: action.mapX ?? 200 + (n % 6) * 220,
              mapY: action.mapY ?? 180 + Math.floor(n / 6) * 180,
            },
          ];
          applied.push(`添加地点 ${action.name}`);
          break;
        }
        case "update_location": {
          const loc = findLocation(next, action.ref);
          if (!loc) {
            skipped.push(`未找到地点: ${action.ref}`);
            break;
          }
          next.locations = (next.locations ?? []).map((l) =>
            l.id === loc.id ? { ...l, ...action.patch } : l
          );
          applied.push(`更新地点 ${loc.name}`);
          break;
        }
        case "delete_location": {
          const loc = findLocation(next, action.ref);
          if (!loc) {
            skipped.push(`未找到地点: ${action.ref}`);
            break;
          }
          next.locations = (next.locations ?? []).filter((l) => l.id !== loc.id);
          next.locationLinks = (next.locationLinks ?? []).filter(
            (l) => l.fromId !== loc.id && l.toId !== loc.id
          );
          applied.push(`删除地点 ${loc.name}`);
          break;
        }
        case "add_location_link": {
          const from = findLocation(next, action.fromRef);
          const to = findLocation(next, action.toRef);
          if (!from || !to) {
            skipped.push(`连线失败: ${action.fromRef} → ${action.toRef}`);
            break;
          }
          const relation = (action.relation ?? "leads_to") as LocationRelation;
          next.locationLinks = [
            ...(next.locationLinks ?? []),
            { ...newLocationLink(from.id, to.id, relation), note: action.note },
          ];
          applied.push(`地图通路 ${from.name}→${to.name}`);
          break;
        }
        case "delete_location_link": {
          const from = findLocation(next, action.fromRef);
          const to = findLocation(next, action.toRef);
          if (!from || !to) {
            skipped.push(`未找到连线`);
            break;
          }
          next.locationLinks = (next.locationLinks ?? []).filter(
            (l) => !(l.fromId === from.id && l.toId === to.id)
          );
          applied.push(`删除通路 ${from.name}→${to.name}`);
          break;
        }
        case "add_chapter": {
          const id = uid("ch");
          next.chapters = [
            ...next.chapters,
            {
              id,
              title: action.title,
              synopsis: action.synopsis,
              blocks: [{ type: "label", id: "start", name: "start" }],
            },
          ];
          applied.push(`添加章节 ${action.title}`);
          break;
        }
        case "delete_chapter": {
          if (next.chapters.length <= 1) {
            skipped.push("至少保留一章");
            break;
          }
          const ch = findChapter(next, action.ref);
          if (!ch) {
            skipped.push(`未找到章节: ${action.ref}`);
            break;
          }
          next.chapters = next.chapters.filter((c) => c.id !== ch.id);
          applied.push(`删除章节 ${ch.title}`);
          break;
        }
        case "rename_chapter": {
          const ch = findChapter(next, action.ref);
          if (!ch) {
            skipped.push(`未找到章节: ${action.ref}`);
            break;
          }
          next.chapters = next.chapters.map((c) =>
            c.id === ch.id ? { ...c, title: action.title } : c
          );
          applied.push(`重命名章节为 ${action.title}`);
          break;
        }
        case "append_script": {
          const ch = findChapter(
            next,
            action.chapterRef ?? opts?.defaultChapterId
          );
          if (!ch) {
            skipped.push("无章节可写入");
            break;
          }
          const text = coerceScriptText(
            (action as { text?: unknown }).text
          );
          if (text === undefined || !String(text).trim()) {
            skipped.push("append_script 缺少正文 text（模型未返回可写入内容）");
            break;
          }
          const blocks = textToBlocks(String(text));
          if (!blocks.length) {
            skipped.push("append_script 正文为空");
            break;
          }
          next.chapters = next.chapters.map((c) =>
            c.id === ch.id ? { ...c, blocks: [...c.blocks, ...blocks] } : c
          );
          applied.push(`向「${ch.title}」写入剧情`);
          break;
        }
        case "replace_script": {
          const ch = findChapter(
            next,
            action.chapterRef ?? opts?.defaultChapterId
          );
          if (!ch) {
            skipped.push("无章节可写入");
            break;
          }
          const text = coerceScriptText(
            (action as { text?: unknown }).text
          );
          if (text === undefined) {
            skipped.push("replace_script 缺少正文 text");
            break;
          }
          const blocks = textToBlocks(String(text));
          next.chapters = next.chapters.map((c) =>
            c.id === ch.id
              ? {
                  ...c,
                  blocks: blocks.length
                    ? blocks
                    : [{ type: "label", id: "start", name: "start" }],
                }
              : c
          );
          applied.push(`重写「${ch.title}」`);
          break;
        }
        case "update_bible": {
          next.bible = { ...next.bible, ...action.patch };
          if (action.patch.world !== undefined) next.lore = action.patch.world;
          applied.push("更新故事设定");
          break;
        }
        case "update_meta": {
          if (action.title !== undefined) next.title = action.title;
          if (action.logline !== undefined) next.logline = action.logline;
          if (action.genre !== undefined) next.genre = action.genre;
          applied.push("更新作品信息");
          break;
        }
        default:
          skipped.push(
            `未知动作: ${String((action as { op?: string }).op ?? "?")}`
          );
      }
    } catch (err) {
      const op = String((action as { op?: string })?.op ?? "?");
      const detail = err instanceof Error ? err.message : "未知错误";
      skipped.push(`${op} 执行失败: ${detail.slice(0, 120)}`);
    }
  }

  next.updatedAt = new Date().toISOString();
  return { project: next, applied, skipped };
}
