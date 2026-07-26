import type { AiAction, AiRequest, AiResponse, VnProject } from "./types.js";
import { projectToContext } from "./renpy.js";

export interface DeepSeekConfig {
  apiKey: string;
  baseUrl?: string;
  model?: string;
}

const ACTION_PROMPTS: Record<AiAction, string> = {
  continue:
    "根据上下文续写视觉小说脚本。输出纯 Ren'Py 风格片段：旁白用双引号行，对白用 角色名 \"台词\"，需要时用 menu/jump/label。不要解释。",
  rewrite:
    "改写用户选中的片段，保持剧情意图与人物语气，输出改进后的 Ren'Py 风格脚本，不要解释。",
  choices:
    "为当前情节设计 2～4 个有意义的分支选项（menu），每个选项给出简短后果或 jump 目标名，输出 Ren'Py menu 代码。",
  polish:
    "润色对白与旁白：更自然、更有画面感，保持人物声音一致。输出润色后的 Ren'Py 片段。",
  outline:
    "根据已有设定，给出接下来 3～5 个场景的大纲（场景标题 + 一句话冲突 + 可选分支），用中文条目列表。",
  character_voice:
    "检查并改写，使对白更符合角色人设与语气。输出改写后的 Ren'Py 对白片段。",
};

function buildSystemPrompt(project: VnProject): string {
  return [
    "你是资深视觉小说编剧助手，输出默认贴近 Ren'Py script。",
    "约定：",
    "- 角色 define 名用英文小写标识符；对白行写成：name \"台词\"",
    "- 旁白：\"旁白文字\"",
    "- 场景：scene bg_xxx / show char_xxx / hide char_xxx",
    "- 分支：menu: 与 jump label_name",
    "- 除非用户要求，不要输出大段讲解，直接给可粘贴的脚本。",
    "",
    "作品上下文：",
    projectToContext(project),
  ].join("\n");
}

export async function runAi(
  config: DeepSeekConfig,
  request: AiRequest
): Promise<AiResponse> {
  if (!config.apiKey || config.apiKey.includes("your-key")) {
    throw new Error("请先配置 DEEPSEEK_API_KEY");
  }

  const baseUrl = (config.baseUrl ?? "https://api.deepseek.com").replace(
    /\/$/,
    ""
  );
  const model = config.model ?? "deepseek-chat";

  const userParts = [
    ACTION_PROMPTS[request.action],
    request.instruction ? `额外要求：${request.instruction}` : "",
    request.selection ? `选中/焦点内容：\n${request.selection}` : "",
  ].filter(Boolean);

  const res = await fetch(`${baseUrl}/v1/chat/completions`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${config.apiKey}`,
    },
    body: JSON.stringify({
      model,
      messages: [
        { role: "system", content: buildSystemPrompt(request.project) },
        { role: "user", content: userParts.join("\n\n") },
      ],
      temperature: request.action === "outline" ? 0.8 : 0.7,
      stream: false,
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

  const content = data.choices?.[0]?.message?.content?.trim() ?? "";
  return { content, model: data.model ?? model };
}
