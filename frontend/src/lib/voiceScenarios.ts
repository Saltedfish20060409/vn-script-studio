import type { VoiceScenario } from "../api/client";

export type ShapeMode = "preference" | "scene" | "interview" | "manual";

export function ensureCustomScenario(list: VoiceScenario[]): VoiceScenario[] {
  const has = list.some((s) => s.id === "custom");
  if (has) return list;
  return [...list, { id: "custom", label: "自定义…", prompt: "", longSuitable: true }];
}

export function promptSlug(prompt: string, maxLen = 16): string {
  return prompt.replace(/\s+/g, " ").trim().slice(0, maxLen);
}
