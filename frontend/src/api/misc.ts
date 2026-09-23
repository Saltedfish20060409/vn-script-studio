import type { ServerSettingsOut } from "../lib/settings";
import type { VnProject } from "../types/vn";
import { apiFetch } from "./http";
import { TIMEOUTS } from "./timeouts";
// ---------------------------------------------------------------------------
// Chapter long memory (NovelMaster-style, PG sliced)
// ---------------------------------------------------------------------------

export interface MemoryArchiveSummary {
  id: string;
  label: string;
  span: number;
  rangeFrom: number;
  rangeTo: number;
  wordCount: number;
  isLatest: boolean;
  updatedAt?: string | null;
}

export function archiveChapterMemory(
  id: string,
  opts?: { span?: number; includeIncomplete?: boolean }
): Promise<{
  archives: MemoryArchiveSummary[];
  count: number;
  span: number;
  latestLabel: string | null;
}> {
  return apiFetch(`/projects/${id}/memory/archive`, {
    method: "POST",
    body: JSON.stringify({
      span: opts?.span ?? 10,
      include_incomplete: opts?.includeIncomplete ?? false,
    }),
  });
}

export function listChapterMemory(
  id: string
): Promise<{ archives: MemoryArchiveSummary[] }> {
  return apiFetch(`/projects/${id}/memory/archives`);
}

export interface LatestMemory {
  archiveId: string;
  label: string;
  rangeFrom: number;
  rangeTo: number;
  spine: string[];
  continuityText: string;
  agentBlock: string;
}

/** 最新一段「章节记忆」——写作页用它显示"已自动记住前 N 章要点"。 */
export function getLatestMemory(
  id: string
): Promise<{ latest: LatestMemory | null }> {
  return apiFetch(`/projects/${id}/memory/latest`);
}

export interface MemoryArchiveDetail {
  id: string;
  label: string;
  span?: number;
  rangeFrom: number;
  rangeTo: number;
  wordCount: number;
  isLatest?: boolean;
  continuityText?: string;
  spine?: unknown[];
  summaries?: unknown[];
  slices?: Array<{
    id?: string;
    kind: string;
    sliceIndex: number;
    charCount: number;
    content: string;
  }>;
}

export function getChapterMemoryArchive(
  id: string,
  archiveId: string
): Promise<MemoryArchiveDetail> {
  return apiFetch(`/projects/${id}/memory/archives/${archiveId}`);
}

export interface HarnessLintResult {
  issues: Array<{
    severity: string;
    code: string;
    message: string;
    source?: string;
  }>;
  errorCount: number;
  warnCount: number;
  infoCount: number;
  pass: boolean;
}

export function harnessLint(id: string, draft: string): Promise<HarnessLintResult> {
  return apiFetch(`/projects/${id}/harness/lint`, {
    method: "POST",
    body: JSON.stringify({ draft }),
  });
}

// ---------------------------------------------------------------------------
// Writing mentors
// ---------------------------------------------------------------------------

export interface MentorPackMeta {
  id: string;
  name: string;
  version?: string;
  tags?: string[];
  stages?: string[];
  budget_chars?: number;
  source?: string;
}

export function getProjectMentors(id: string): Promise<{
  activeIds: string[];
  customPacks: Array<{ id?: string; name?: string; updatedAt?: string }>;
  active: MentorPackMeta[];
  builtin: MentorPackMeta[];
  defaultActiveIds: string[];
}> {
  return apiFetch(`/projects/${id}/mentors`);
}

// ---------------------------------------------------------------------------
// Author lenses (作家思维)
// ---------------------------------------------------------------------------

export interface LensPackMeta {
  id: string;
  name: string;
  version?: string;
  tags?: string[];
  source?: string;
  family?: "ln_vn" | "literary" | string;
}

export function listLenses(): Promise<{
  packs: LensPackMeta[];
  families?: Record<string, string>;
  note?: string;
  maxActive?: number;
}> {
  return apiFetch("/lenses");
}

export function getProjectLenses(id: string): Promise<{
  activeIds: string[];
  customPacks: Array<{ id?: string; name?: string; updatedAt?: string }>;
  active: LensPackMeta[];
  builtin: LensPackMeta[];
}> {
  return apiFetch(`/projects/${id}/lenses`);
}

export function putProjectLenses(
  id: string,
  body: { activeIds: string[] }
): Promise<{
  activeIds: string[];
  active: LensPackMeta[];
  project: VnProject;
}> {
  return apiFetch(`/projects/${id}/lenses`, {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

interface BrainstormPerspective {
  id: string;
  name: string;
  content: string;
  ok: boolean;
  error?: string | null;
  model?: string | null;
}

export interface BrainstormResult {
  mode: string;
  question: string;
  lensIds: string[];
  perspectives: BrainstormPerspective[];
  synthesis: string;
  markdown: string;
  authorCount: number;
  okCount: number;
  model?: string;
}

export function runBrainstorm(
  id: string,
  body: {
    question: string;
    lens_ids?: string[];
    chapter_id?: string;
    selection?: string;
    draft?: string;
  }
): Promise<BrainstormResult> {
  return apiFetch(`/projects/${id}/brainstorm`, {
    method: "POST",
    timeoutMs: TIMEOUTS.long,
    body: JSON.stringify(body),
  });
}

/**
 * 异步（作业化）头脑风暴：只负责**发起**，结果用 `waitProjectJob` 取 `job.result`。
 *
 * 为什么：一次头脑风暴是两轮串行的模型调用（作家并发一轮 + 责编综合一轮），思考档下
 * 最坏 8 分钟量级。放在请求里会逼前端把等待预算拉到 10 分钟级才不误判超时；作业化后
 * 发起只需覆盖"登记作业"的时间，进度与结果走既有作业通道（与自动写作 / 章节回炉同一套）。
 * 结果形状与同步的 `runBrainstorm` 一致（含 `markdown`），调用方两种都能直接用。
 */
export function startBrainstormJob(
  id: string,
  body: {
    question: string;
    lens_ids?: string[];
    chapter_id?: string;
    selection?: string;
    draft?: string;
  }
): Promise<{ jobId: string; async: true; status: string }> {
  return apiFetch(`/projects/${id}/brainstorm`, {
    method: "POST",
    // 只是登记作业：用最短的一档即可，真正的耗时走作业通道。
    timeoutMs: TIMEOUTS.upload,
    body: JSON.stringify({ ...body, async_mode: true }),
  });
}

// ---------------------------------------------------------------------------
// Shares
// ---------------------------------------------------------------------------

export function createShare(id: string): Promise<{ token: string; url: string }> {
  return apiFetch(`/projects/${id}/shares`, { method: "POST" });
}

export interface ShareOut {
  token: string;
  title: string;
  project: VnProject;
  created_at: string;
  /** Public landing-page preview: chapter text taste + character list */
  preview?: {
    chapterPreviews?: Array<{
      chapterId: string;
      title: string;
      text: string;
    }>;
    characters?: Array<{ name: string; bio: string }>;
    stats?: { chapters: number; words: number };
  };
}

export function getShare(token: string): Promise<ShareOut> {
  return apiFetch(`/shares/${token}`, { skipAuthRedirect: true });
}

export function revokeShare(id: string, token: string): Promise<{ ok: boolean }> {
  return apiFetch(`/projects/${id}/shares/${token}`, { method: "DELETE" });
}

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------

export function getSettings(): Promise<ServerSettingsOut> {
  return apiFetch<ServerSettingsOut>("/settings");
}

export function putSettings(body: Record<string, unknown>): Promise<ServerSettingsOut> {
  return apiFetch<ServerSettingsOut>("/settings", {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

// ---------------------------------------------------------------------------
// LLM model catalogue + connectivity test
// ---------------------------------------------------------------------------

export interface ModelPreset {
  id: string;
  label: string;
  vendor: string;
  base_url: string;
  model: string;
  json_mode: boolean;
  context_k: number;
  note: string;
}

export interface ActiveLlmInfo {
  base_url: string;
  model: string;
  source: "user" | "server" | "client";
}

export function getModelCatalogue(): Promise<{
  presets: ModelPreset[];
  active: ActiveLlmInfo | null;
}> {
  return apiFetch<{ presets: ModelPreset[]; active: ActiveLlmInfo | null }>(
    "/settings/models"
  );
}

export function testLlm(body: {
  api_key?: string;
  base_url?: string;
  model?: string;
}): Promise<{ ok: boolean; latency_ms: number; model: string; error?: string }> {
  return apiFetch<{ ok: boolean; latency_ms: number; model: string; error?: string }>(
    "/settings/test-llm",
    {
      method: "POST",
      body: JSON.stringify(body),
    timeoutMs: TIMEOUTS.probe,
    }
  );
}

// ---------------------------------------------------------------------------
// LLM usage
// ---------------------------------------------------------------------------

export interface UsageTotals {
  promptTokens: number;
  completionTokens: number;
  totalTokens: number;
  calls: number;
}

export function getUsage(): Promise<{ today: UsageTotals; total: UsageTotals }> {
  return apiFetch<{ today: UsageTotals; total: UsageTotals }>("/usage");
}
