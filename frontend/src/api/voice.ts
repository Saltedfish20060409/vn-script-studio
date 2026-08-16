import type { VnProject } from "../types/vn";
import { apiFetch } from "./http";
// ---------------------------------------------------------------------------
// Character workshop (角色工坊)
// ---------------------------------------------------------------------------

export interface VoiceScenario {
  id: string;
  label: string;
  prompt: string;
  longSuitable?: boolean;
}

export interface VoiceAxisTag {
  id: string;
  label: string;
  hint: string;
}

export interface VoiceVariant {
  axisId: string;
  axisLabel: string;
  hypothesis: string;
  lines: Array<{ speaker: string; text: string }>;
  /** True when the model failed to produce this variant — never acceptable. */
  placeholder?: boolean;
}

export interface VoiceCorpusStats {
  sampleCount: number;
  scenarioCoverage: number;
  volumeChars?: number;
  shortCount?: number;
  sceneCount?: number;
  interviewCount?: number;
  readyForMind: boolean;
  hasMindPack?: boolean;
  confirmedAxes?: string[];
}

export function getVoiceAxisTags(): Promise<{ tags: VoiceAxisTag[] }> {
  return apiFetch("/voice/axis-tags");
}

export function getCharacterVoiceState(
  projectId: string,
  characterId: string
): Promise<
  VoiceCorpusStats & {
    characterId: string;
    displayName: string;
    voice?: string;
    bio?: string;
    voiceCorpus: import("../types/vn").VoiceCorpusSample[];
    voiceMind?: string;
    voiceRejectNotes: string[];
    scenarios: VoiceScenario[];
    axisTags?: VoiceAxisTag[];
  }
> {
  return apiFetch(`/projects/${projectId}/characters/${characterId}/voice`);
}

export function generateCharacterVoice(
  projectId: string,
  characterId: string,
  body: {
    scenario_id?: string;
    scenario_prompt?: string;
    scenario_label?: string;
    extra_constraints?: string;
    kind?: "preference" | "scene" | "interview";
    turns?: number;
    question?: string;
    axis_tags?: string[];
  }
): Promise<{
  kind?: string;
  scenarioId: string;
  scenarioLabel: string;
  scenarioPrompt?: string;
  question?: string;
  axes?: VoiceAxisTag[];
  variants?: VoiceVariant[];
  lines?: Array<{ speaker: string; text: string }>;
  model?: string;
  confirmedAxes?: string[];
  pinnedTags?: string[];
}> {
  return apiFetch(`/projects/${projectId}/characters/${characterId}/voice/generate`, {
    method: "POST",
    timeoutMs: 180000,
    body: JSON.stringify(body),
  });
}

export function acceptCharacterVoiceSample(
  projectId: string,
  characterId: string,
  body: {
    scenario_id?: string;
    scenario_label?: string;
    scenario_prompt?: string;
    axis?: string;
    hypothesis?: string;
    lines: Array<{ speaker: string; text: string }>;
    user_note?: string;
    preference_note?: string;
    rejected_summary?: string;
    source?: string;
  }
): Promise<
  VoiceCorpusStats & {
    sample: import("../types/vn").VoiceCorpusSample;
    voicePreferNotes?: string[];
    project: VnProject;
  }
> {
  return apiFetch(`/projects/${projectId}/characters/${characterId}/voice/accept`, {
    method: "POST",
    timeoutMs: 180000,
    body: JSON.stringify(body),
  });
}

export function rejectCharacterVoiceRound(
  projectId: string,
  characterId: string,
  body: { note?: string; hypotheses?: string[] }
): Promise<{ voiceRejectNotes: string[]; project: VnProject }> {
  return apiFetch(`/projects/${projectId}/characters/${characterId}/voice/reject`, {
    method: "POST",
    timeoutMs: 180000,
    body: JSON.stringify(body),
  });
}

export function deleteCharacterVoiceSample(
  projectId: string,
  characterId: string,
  sampleId: string
): Promise<{ sampleCount: number; project: VnProject }> {
  return apiFetch(
    `/projects/${projectId}/characters/${characterId}/voice/samples/${sampleId}`,
    { method: "DELETE" }
  );
}

export function synthesizeCharacterVoiceMind(
  projectId: string,
  characterId: string,
  body: { force?: boolean; apply_voice_summary?: boolean } = {}
): Promise<{
  markdown: string;
  sampleCount: number;
  scenarioCoverage: number;
  ready: boolean;
  project: VnProject;
}> {
  return apiFetch(`/projects/${projectId}/characters/${characterId}/voice/synthesize`, {
    method: "POST",
    timeoutMs: 180000,
    body: JSON.stringify(body),
  });
}

export function extractCharacterVoice(
  projectId: string,
  characterId: string
): Promise<{
  candidates: Array<{
    chapterId: string;
    chapterTitle?: string;
    blockIndex: number;
    scenario: string;
    scenarioLabel: string;
    lines: Array<{ speaker: string; text: string }>;
    preview: string;
  }>;
  count: number;
}> {
  return apiFetch(`/projects/${projectId}/characters/${characterId}/voice/extract`, {
    method: "POST",
    timeoutMs: 180000,
    body: "{}",
  });
}

export function acceptExtractedCharacterVoice(
  projectId: string,
  characterId: string,
  body: { indices?: number[]; samples?: unknown[] }
): Promise<{
  added: unknown[];
  sampleCount: number;
  scenarioCoverage: number;
  readyForMind: boolean;
  project: VnProject;
}> {
  return apiFetch(
    `/projects/${projectId}/characters/${characterId}/voice/extract/accept`,
    { method: "POST",
    timeoutMs: 180000, body: JSON.stringify(body) }
  );
}

export function exportCharacterVoicePack(
  projectId: string,
  characterId: string
): Promise<{
  filename: string;
  packId: string;
  markdown: string;
  sampleCount: number;
  scenarioCoverage: number;
}> {
  return apiFetch(`/projects/${projectId}/characters/${characterId}/voice/export`);
}

export function importCharacterVoiceMind(
  projectId: string,
  characterId: string,
  body: { markdown: string; replace_corpus?: boolean }
): Promise<{ voiceMind?: string; project: VnProject }> {
  return apiFetch(
    `/projects/${projectId}/characters/${characterId}/voice/import-mind`,
    { method: "POST",
    timeoutMs: 180000, body: JSON.stringify(body) }
  );
}

export function workshopChat(
  projectId: string,
  characterId: string,
  body: {
    mode: "user" | "duo";
    message: string;
    partner_id?: string;
    history?: Array<{ role: string; content: string }>;
  }
): Promise<{
  mode: string;
  reply?: string;
  speakerId?: string;
  speakerName?: string;
  lines?: Array<{ speakerId: string; speakerName: string; text: string }>;
  model?: string;
}> {
  return apiFetch(`/projects/${projectId}/characters/${characterId}/workshop/chat`, {
    method: "POST",
    timeoutMs: 180000,
    body: JSON.stringify(body),
  });
}
