import type { DeepSeekConfig } from "./ai.js";
import { projectToContext } from "./renpy.js";
import type { VnProject } from "./types.js";

export interface VoiceIssue {
  character: string;
  severity: "info" | "warn" | "high";
  quote: string;
  note: string;
  suggestion?: string;
}

export interface VoiceReport {
  summary: string;
  issues: VoiceIssue[];
  model: string;
}

export async function runVoiceCheck(
  config: DeepSeekConfig,
  project: VnProject,
  chapterId?: string
): Promise<VoiceReport> {
  if (!config.apiKey || config.apiKey.includes("your-key")) {
    throw new Error("请先配置 DEEPSEEK_API_KEY");
  }
  const baseUrl = (config.baseUrl ?? "https://api.deepseek.com").replace(
    /\/$/,
    ""
  );
  const model = config.model ?? "deepseek-chat";

  const focusChapter = chapterId
    ? project.chapters.find((c) => c.id === chapterId)
    : undefined;

  const res = await fetch(`${baseUrl}/v1/chat/completions`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      Authorization: `Bearer ${config.apiKey}`,
    },
    body: JSON.stringify({
      model,
      temperature: 0.3,
      response_format: { type: "json_object" },
      messages: [
        {
          role: "system",
          content: `你是视觉小说对白审稿编辑。根据角色 voice/bio，检查对白是否破人设。
只输出 JSON：
{
  "summary": "总体评价（中文）",
  "issues": [
    { "character": "角色名", "severity": "info|warn|high", "quote": "原句摘录", "note": "问题", "suggestion": "改写建议" }
  ]
}
若整体稳定，issues 可为空，summary 给鼓励与微调建议。`,
        },
        {
          role: "user",
          content: `${projectToContext(project, 10000)}\n\n重点检查章节: ${focusChapter?.title ?? "全部"}`,
        },
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
  let raw = data.choices?.[0]?.message?.content?.trim() ?? "{}";
  const fence = raw.match(/```(?:json)?\s*([\s\S]*?)```/);
  if (fence) raw = fence[1].trim();
  const parsed = JSON.parse(raw) as {
    summary?: string;
    issues?: VoiceIssue[];
  };
  return {
    summary: parsed.summary ?? "无摘要",
    issues: Array.isArray(parsed.issues) ? parsed.issues : [],
    model: data.model ?? model,
  };
}
