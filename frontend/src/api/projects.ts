import type {
  AgentAction,
  AgentChatMessage,
  AgentContextMeta,
  AgentTaskKind,
  Location,
  LocationLink,
  VnProject,
  VoiceReport,
} from "../types/vn";
import {
  API_BASE,
  ApiError,
  apiFetch,
  authedRawFetch,
  buildApiHeaders,
  readErrorPayload,
} from "./http";
export interface ProjectSummary {
  id: string;
  title: string;
  logline?: string | null;
  genre?: string | null;
  updated_at: string;
  created_at: string;
  /** 章数（列表接口直接从 jsonb 数出来）：桌面图标角标 / 一眼进度 */
  chapters_count?: number;
}

export type WritingActivityDay = {
  date: string;
  added: number;
  removed: number;
  net: number;
  edits: number;
};

type ChapterStats = {
  index: number;
  id: string;
  title: string;
  words: number;
  lines: number;
  dialogueWords: number;
  dialogueRatio: number;
  speakers: string[];
  /** 所属卷 id（"" = 未分卷） */
  volumeId?: string;
};

/** 每卷进度（有卷时后端才返回内容） */
export type VolumeStats = {
  id: string;
  title: string;
  index: number;
  note: string;
  chapters: number;
  words: number;
  avgChapterWords: number;
  chapterIds: string[];
};

export type ProjectStats = {
  projectId: string;
  totals: {
    chapters: number;
    words: number;
    lines: number;
    avgChapterWords: number;
  };
  chapters: ChapterStats[];
  /** 每卷进度（含末尾的「未分卷」档；没有卷时为空数组） */
  volumes?: VolumeStats[];
  activity: WritingActivityDay[];
};

export function getProjectStats(id: string): Promise<ProjectStats> {
  return apiFetch<ProjectStats>(`/projects/${id}/stats`);
}

export function listProjects(): Promise<ProjectSummary[]> {
  return apiFetch<ProjectSummary[]>("/projects");
}

export function getProject(id: string): Promise<VnProject> {
  return apiFetch<VnProject>(`/projects/${id}`);
}

export function createProject(
  body: { title?: string; from_demo?: boolean; template_id?: string } = {}
): Promise<VnProject> {
  return apiFetch<VnProject>("/projects", {
    method: "POST",
    timeoutMs: 180000,
    body: JSON.stringify(body),
  });
}

export type ProjectTemplate = {
  id: string;
  title: string;
  genre: string;
  logline: string;
  characters: string[];
};

export function listProjectTemplates(): Promise<{ templates: ProjectTemplate[] }> {
  return apiFetch("/projects/templates");
}

export function putProject(
  id: string,
  data: VnProject,
  updatedAt?: string,
  opts?: {
    force?: boolean;
    /** Chapters this save actually modified — server merges only these. */
    chapterIds?: string[];
    /** Non-chapter top-level fields this save modified. */
    sections?: string[];
  }
): Promise<VnProject> {
  return apiFetch<VnProject>(`/projects/${id}`, {
    method: "PUT",
    body: JSON.stringify({
      data,
      updated_at: updatedAt,
      force: Boolean(opts?.force),
      chapter_ids: opts?.chapterIds?.length ? opts.chapterIds : undefined,
      sections: opts?.sections?.length ? opts.sections : undefined,
    }),
  });
}

export function patchProject(
  id: string,
  patch: { title?: string; logline?: string; genre?: string }
): Promise<VnProject> {
  return apiFetch<VnProject>(`/projects/${id}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export function deleteProject(id: string): Promise<{ ok: boolean }> {
  return apiFetch<{ ok: boolean }>(`/projects/${id}`, { method: "DELETE" });
}

export function duplicateProject(id: string): Promise<VnProject> {
  return apiFetch<VnProject>(`/projects/${id}/duplicate`, { method: "POST" });
}

/** 前情提要（卷首回顾）：生成一段"之前发生了什么"的可读回述。 */
export type RecapOut = {
  text: string;
  model: string;
  chaptersUsed: number;
  archivesUsed: number;
  included: string[];
  label: string;
  mode: "before" | "volume";
  volumeId: string | null;
};

export function getRecap(
  id: string,
  body: { volumeId?: string; mode?: "before" | "volume"; upToChapterId?: string }
): Promise<RecapOut> {
  return apiFetch<RecapOut>(`/projects/${id}/recap`, {
    method: "POST",
    timeoutMs: 240000,
    body: JSON.stringify({
      volume_id: body.volumeId,
      mode: body.mode ?? "before",
      up_to_chapter_id: body.upToChapterId,
    }),
  });
}

/** 写作页「标记批改」：让 AI 只改标出来的这一处（intent=advice 时只给建议，不动正文）。 */
export type MarkReviseOut = {
  replacement: string;
  /** 多候选：1–3 版改写（第一版即 replacement） */
  candidates?: string[];
  advice: string;
  changed: boolean;
  model: string;
  styleUsed: boolean;
  intent: "rewrite" | "advice";
  chapterId: string;
};

export function reviseMark(
  id: string,
  body: {
    chapterId: string;
    quote: string;
    prefix?: string;
    suffix?: string;
    instruction?: string;
    intent?: "rewrite" | "advice";
    /** 一次要几版改写（1–3） */
    candidates?: number;
  }
): Promise<MarkReviseOut> {
  return apiFetch<MarkReviseOut>(`/projects/${id}/marks/revise`, {
    method: "POST",
    timeoutMs: 180000,
    body: JSON.stringify({
      chapter_id: body.chapterId,
      quote: body.quote,
      prefix: body.prefix ?? "",
      suffix: body.suffix ?? "",
      instruction: body.instruction ?? "",
      intent: body.intent ?? "rewrite",
      candidates: body.candidates ?? 1,
    }),
  });
}

/** 标记面板的一句提示：项目有没有可用文风记忆（决定"按你的文风改"是否生效）。 */
export function marksHint(id: string): Promise<{ hasStyleMemory: boolean }> {
  return apiFetch<{ hasStyleMemory: boolean }>(`/projects/${id}/marks/hint`);
}

export function importProjectFile(file: File, title?: string): Promise<VnProject> {
  const form = new FormData();
  form.append("file", file);
  if (title) form.append("title", title);
  return apiFetch<VnProject>("/projects/import", {
    method: "POST",
    timeoutMs: 180000,
    body: form,
  });
}

export async function exportRpy(id: string): Promise<string> {
  const res = await authedRawFetch(`/projects/${id}/export/rpy`);
  return res.text();
}

export async function exportJson(id: string): Promise<Blob> {
  const res = await authedRawFetch(`/projects/${id}/export/json`);
  return res.blob();
}

/** Submission export: whole project as readable Markdown. */
export async function exportMarkdown(id: string): Promise<Blob> {
  const res = await authedRawFetch(`/projects/${id}/export/markdown`);
  return res.blob();
}

/** Submission export: whole project as a styled Word document. */
export async function exportDocx(id: string): Promise<Blob> {
  const res = await authedRawFetch(`/projects/${id}/export/docx`);
  return res.blob();
}

export type GenerateRpyOut = {
  rpy: string;
  blocks: import("../types/vn").ScriptBlock[];
  usedLlm: boolean;
  proseHash: string;
};

export async function generateRpyFromProse(
  id: string,
  chapterId: string,
  prose: string,
  useLlm = true
): Promise<GenerateRpyOut> {
  return apiFetch<GenerateRpyOut>(`/projects/${id}/generate-rpy`, {
    method: "POST",
    body: JSON.stringify({
      chapter_id: chapterId,
      prose,
      use_llm: useLlm,
    }),
  });
}

export interface LocalizationEntry {
  key: string;
  chapterId: string;
  kind: string;
  source: string;
  sourceHash: string;
  targets: Record<string, string>;
  status: Record<string, string>;
  note?: string;
}

export interface LocalizationOut {
  locales: Array<{ code: string; name?: string; status?: string }>;
  glossary: Array<{ term: string; targets: Record<string, string>; note?: string }>;
  entries: LocalizationEntry[];
  stats: {
    locales: Array<{
      code: string;
      name: string;
      status: string;
      translated: number;
      total: number;
      ratio: number;
    }>;
    entries: number;
    glossary: number;
    updatedAt?: string | null;
  };
}

export async function fetchLocalization(id: string): Promise<LocalizationOut> {
  return apiFetch<LocalizationOut>(`/projects/${id}/localization`);
}

export async function saveLocalization(
  id: string,
  payload: {
    locales: Array<{ code: string; name?: string; status?: string }>;
    entries: LocalizationEntry[];
    glossary: Array<{ term: string; targets: Record<string, string>; note?: string }>;
  }
): Promise<{ ok: boolean; stats: LocalizationOut["stats"] }> {
  return apiFetch(`/projects/${id}/localization`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export async function prefillLocalization(
  id: string,
  locale: string
): Promise<{ ok: boolean; filled: number; stats: LocalizationOut["stats"] }> {
  return apiFetch(`/projects/${id}/localization/prefill?locale=${encodeURIComponent(locale)}`, {
    method: "POST",
  });
}

/** AI 代翻（草稿，状态标记为 ai，需人工校对后再导出）。 */
export async function aiTranslateLocalization(
  id: string,
  opts: { locale: string; localeName?: string; overwrite?: boolean; limit?: number }
): Promise<{
  ok: boolean;
  applied: number;
  skipped: number;
  remaining: number;
  /** 这一次实际交给模型的句数 */
  batch: number;
  model?: string;
  /** 这一次真实消耗的 token（服务端从模型响应里取） */
  tokens: { prompt: number; completion: number; total: number };
  /** 今日已消耗 / 每日上限（0 表示不限）——让用户看到共享额度还剩多少 */
  usedToday: number;
  dailyCap: number;
  message: string;
  stats: LocalizationOut["stats"];
}> {
  return apiFetch(`/projects/${id}/localization/translate`, {
    method: "POST",
    body: JSON.stringify({
      locale: opts.locale,
      locale_name: opts.localeName ?? "",
      overwrite: Boolean(opts.overwrite),
      limit: opts.limit ?? 25,
    }),
    // 这是一次真实的模型调用，默认 30s 太短：超时会让用户以为失败，
    // 而服务端其实已经写完并提交了译文（进度显示与实际不符）。
    timeoutMs: 180000,
  });
}

/** 下载 tl/<lang>/strings.rpy 打包 zip。 */
export async function downloadLocalizationZip(id: string): Promise<Blob> {
  const res = await authedRawFetch(`/projects/${id}/export/localization.rpy`);
  if (!res.ok) throw new ApiError(res.status, "还没有任何译文，先在本地化页填几条");
  return res.blob();
}

export interface AssetAuditOut {
  images: {
    total: number;
    items: Array<{ image: string; uses: number; chapters: string[] }>;
    suspicious: Array<{ image: string; uses: number; chapters: string[] }>;
  };
  audio: Record<
    string,
    { total: number; items: Array<{ file: string; uses: number }> }
  >;
  declaredTags: string[];
  unusedTags: string[];
  notes: string[];
}

export async function fetchAssetAudit(id: string): Promise<AssetAuditOut> {
  return apiFetch<AssetAuditOut>(`/projects/${id}/assets/audit`);
}

export interface ScriptReportOut {
  labels: { total: number; reachable: number; unreachable: string[] };
  endings: Array<{ chapterId: string; label: string; via: string; reachable: boolean }>;
  endingsReachable: number;
  branchPoints: Array<{
    chapterId: string;
    menuId: string;
    choices: number;
    conditional: number;
  }>;
  conditions: Array<{
    chapterId: string;
    where: string;
    text: string;
    detail: string;
    error?: string | null;
  }>;
  invalidConditions: Array<{ chapterId: string; text: string; error?: string | null }>;
  danglingJumps: Array<{ chapterId: string; target: string }>;
  variables: {
    declared: string[];
    used: string[];
    unused: string[];
    undeclared: string[];
  };
  duration: {
    chars: number;
    readSeconds: number;
    waitSeconds: number;
    totalSeconds: number;
    minutes: number;
    assumption: string;
  };
  repetition: {
    totalChars: number;
    duplicateChars: number;
    ratio: number;
    uniqueDuplicated: number;
    top: Array<{ text: string; count: number; chars: number }>;
  };
  counts: Record<string, number>;
}

/** 剧本工程体检（纯本地计算，不调模型）。 */
export async function fetchScriptReport(id: string): Promise<ScriptReportOut> {
  return apiFetch<ScriptReportOut>(`/projects/${id}/analysis/script-report`, {
    skipAuthRedirect: true,
  });
}

/** Full Ren'Py project skeleton (script/options/gui/README) as a zip blob. */
export async function exportRenpyBundle(id: string): Promise<Blob> {
  const res = await authedRawFetch(`/projects/${id}/export/bundle`);
  return res.blob();
}

export type MapExtractProposal = {
  locations: Location[];
  locationLinks: LocationLink[];
  newPlaceIds: string[];
  newLinkIds: string[];
};

export type MapExtractPreviewResult = {
  project: VnProject;
  proposal: MapExtractProposal;
  addedCount: number;
  linkCount: number;
  llmAddedCount?: number;
  llmLinkCount?: number;
  mode?: string;
  llmUsed?: boolean;
  warnings?: string[];
};

export function mapExtract(
  id: string,
  opts?: { mode?: "smart" | "rules" }
): Promise<MapExtractPreviewResult> {
  return apiFetch(`/projects/${id}/map/extract`, {
    method: "POST",
    timeoutMs: 180000,
    body: JSON.stringify({ mode: opts?.mode ?? "smart" }),
  });
}

export function mapExtractAccept(
  id: string,
  body: {
    placeIds: string[];
    linkIds: string[];
    proposal: MapExtractProposal;
  }
): Promise<{
  project: VnProject;
  addedCount: number;
  linkCount: number;
}> {
  return apiFetch(`/projects/${id}/map/extract/accept`, {
    method: "POST",
    timeoutMs: 180000,
    body: JSON.stringify(body),
  });
}

export interface SnapshotSummary {
  id: string;
  label: string;
  createdAt: string;
}

export function listSnapshots(id: string): Promise<SnapshotSummary[]> {
  return apiFetch(`/projects/${id}/snapshots`);
}

export function createSnapshot(id: string, label: string): Promise<SnapshotSummary> {
  return apiFetch(`/projects/${id}/snapshots`, {
    method: "POST",
    timeoutMs: 180000,
    body: JSON.stringify({ label }),
  });
}

export function restoreSnapshot(id: string, snapshotId: string): Promise<VnProject> {
  return apiFetch(`/projects/${id}/snapshots/${snapshotId}/restore`, {
    method: "POST",
    timeoutMs: 180000,
  });
}

export function deleteSnapshot(
  id: string,
  snapshotId: string
): Promise<{ ok: boolean }> {
  return apiFetch(`/projects/${id}/snapshots/${snapshotId}`, {
    method: "DELETE",
  });
}

interface SnapshotChapterDiff {
  chapterId: string;
  title: string;
  status: "added" | "removed" | "changed" | "same";
  wordsFrom: number;
  wordsTo: number;
  linesFrom: number;
  linesTo: number;
}

interface SnapshotCharacterDiff {
  id: string;
  name: string;
  status: "added" | "removed" | "same";
}

export interface SnapshotDiffResult {
  summary: string;
  chapters: SnapshotChapterDiff[];
  characters: SnapshotCharacterDiff[];
  locations: { added: number; removed: number; changed: number };
  timeline: { added: number; removed: number; changed: number };
  changedChapters: number;
  fromHash: string;
  toHash: string;
}

export function compareSnapshot(
  id: string,
  fromSnapId: string,
  toSnapId?: string
): Promise<SnapshotDiffResult> {
  return apiFetch(`/projects/${id}/snapshots/compare`, {
    method: "POST",
    timeoutMs: 120000,
    body: JSON.stringify(
      toSnapId ? { from_snap_id: fromSnapId, to_snap_id: toSnapId } : { from_snap_id: fromSnapId }
    ),
  });
}

export interface AgentRunInBody {
  messages: AgentChatMessage[];
  chapter_id?: string;
  selection?: string;
  task?: AgentTaskKind;
  chat_memory?: string;
  conversation_id?: string;
  apply_actions?: boolean;
  lens_ids?: string[];
  lens_intent?: string;
  attachments?: AgentAttachment[];
  /** 断点续跑：从该会话 run_state 检查点继续上次中断/失败的多步运行 */
  resume?: boolean;
  /** 作者按需摘掉的资料块 key（见 lib/agentSections.AGENT_SECTIONS） */
  exclude_sections?: string[];
}

export type AgentAttachment = {
  id?: string | null;
  filename: string;
  text: string;
  chars?: number;
  warning?: string | null;
};

export function uploadAgentAttachment(
  projectId: string,
  file: File,
  persist = true
): Promise<AgentAttachment> {
  const form = new FormData();
  form.append("file", file);
  form.append("persist", persist ? "true" : "false");
  return apiFetch(`/projects/${projectId}/agent/attachments`, {
    method: "POST",
    timeoutMs: 180000,
    body: form,
  });
}

export function ingestAttachmentSettings(
  projectId: string,
  body: {
    attachments: AgentAttachment[];
    note?: string;
    conversation_id?: string;
  }
): Promise<{
  message: string;
  actions: AgentAction[];
  applied: string[];
  skipped: string[];
  project: VnProject;
  wrote: boolean;
}> {
  return apiFetch(`/projects/${projectId}/agent/ingest-settings`, {
    method: "POST",
    timeoutMs: 180000,
    body: JSON.stringify({
      attachments: body.attachments.map((a) => ({
        filename: a.filename,
        text: a.text,
        id: a.id,
      })),
      note: body.note,
      conversation_id: body.conversation_id,
    }),
  });
}

export function chapterRevise(
  projectId: string,
  body: {
    chapter_id?: string;
    note?: string;
    conversation_id?: string;
    attachments?: AgentAttachment[];
    mode?: "cut_lecture" | "human_warmth" | "light_touch";
    preferences?: {
      lockedNames?: string[];
      preferKeepOriginal?: boolean;
      notes?: string[];
      mode?: string;
    };
    async_mode?: boolean;
  }
): Promise<
  | {
      message: string;
      diagnosis: Record<string, unknown>;
      diagnosisMd: string;
      revisedText: string;
      sourceText?: string;
      chapterId: string | null;
      chapterTitle: string;
      sourceChars: number;
      warnings: string[];
      model?: string;
      criticNote?: string;
      lintIssues?: unknown[];
      llmCalls?: unknown[];
      elapsedMs?: number;
      wrote?: boolean;
      debugTrace?: unknown[];
    }
  | { jobId: string; async: true; status: string }
> {
  return apiFetch(`/projects/${projectId}/agent/chapter-revise`, {
    method: "POST",
    timeoutMs: 180000,
    body: JSON.stringify({
      ...body,
      attachments: body.attachments?.map((a) => ({
        filename: a.filename,
        text: a.text,
        id: a.id,
      })),
    }),
  });
}

export function chapterReviseApply(
  projectId: string,
  body: {
    chapter_id?: string;
    text: string;
    conversation_id?: string;
  }
): Promise<{
  message: string;
  applied: string[];
  skipped: string[];
  project: VnProject;
  wrote: boolean;
}> {
  return apiFetch(`/projects/${projectId}/agent/chapter-revise/apply`, {
    method: "POST",
    timeoutMs: 180000,
    body: JSON.stringify(body),
  });
}

export interface AgentRunOut {
  message: string;
  actions: AgentAction[];
  model: string;
  context_meta?: AgentContextMeta | null;
  project?: VnProject | null;
  applied: boolean;
  warnings: string[];
  conversation_id?: string | null;
  inbox_added?: number;
  trace?: import("../types/vn").AgentTraceEvent[];
}

// ---------------------------------------------------------------------------
// Agent streaming (SSE)
// ---------------------------------------------------------------------------

export type AgentStreamEvent =
  | { type: "task"; task?: string; craftMode?: string }
  | { type: "thought"; text?: string }
  | { type: "tool_call"; id?: string; name?: string; arguments?: unknown }
  | { type: "tool_result"; id?: string; name?: string; ok?: boolean; preview?: string }
  | { type: "actions"; actions?: AgentAction[]; skipped?: string[] }
  | { type: "review"; note?: string }
  | { type: "memory"; note?: string }
  | { type: "error"; message?: string }
  | { type: "done"; result?: AgentRunOut }
  | { type: "final"; result?: AgentRunOut };

/**
 * Streaming agent run. Resolves with the same AgentRunOut as runAgent();
 * `onEvent` receives each SSE event as it arrives (task / thought / tool / …).
 * Pass `signal` to cancel the stream (e.g. on component unmount); the fetch
 * and the read loop both observe it.
 */
export async function runAgentStream(
  id: string,
  body: AgentRunInBody,
  onEvent: (evt: AgentStreamEvent) => void,
  signal?: AbortSignal
): Promise<AgentRunOut> {
  const res = await fetch(`${API_BASE}/projects/${id}/agent/stream`, {
    method: "POST",
    headers: buildApiHeaders(undefined, true),
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok || !res.body) {
    const payload = await readErrorPayload(res).catch(() => ({
      message: `HTTP ${res.status}`,
      detail: undefined as unknown,
    }));
    throw new ApiError(res.status, payload.message, payload.detail);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalResult: AgentRunOut | null = null;
  for (;;) {
    if (signal?.aborted) {
      reader.cancel().catch(() => undefined);
      throw new ApiError(499, "请求已取消");
    }
    const { done, value } = await reader.read();
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
    let idx: number;
    while ((idx = buffer.indexOf("\n\n")) >= 0) {
      const chunk = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      const line = chunk.split("\n").find((l) => l.startsWith("data:"));
      if (!line) continue;
      const payload = line.slice(5).trim();
      if (!payload) continue;
      let evt: AgentStreamEvent;
      try {
        evt = JSON.parse(payload) as AgentStreamEvent;
      } catch {
        continue;
      }
      onEvent(evt);
      if (evt.type === "final" && evt.result) finalResult = evt.result;
      if (evt.type === "error") {
        throw new ApiError(500, evt.message || "Agent 流式请求失败");
      }
    }
    if (done) break;
  }
  if (!finalResult) throw new ApiError(500, "Agent 流式响应缺少最终结果");
  return finalResult;
}

export interface AgentConversationSummary {
  id: string;
  title: string;
  message_count: number;
  created_at: string;
  updated_at: string;
}

export interface AgentConversationOut {
  id: string;
  title: string;
  messages: AgentChatMessage[];
  chat_memory: string;
  undo_stack: unknown[];
  /** 运行检查点摘要：status interrupted/error 时前端显示"继续上次运行" */
  run_state?: {
    status?: string;
    step?: number;
    steps?: number;
    updatedAt?: string;
  } | null;
  created_at: string;
  updated_at: string;
}

export function listAgentConversations(
  projectId: string
): Promise<AgentConversationSummary[]> {
  return apiFetch(`/projects/${projectId}/agent/conversations`);
}

export function createAgentConversation(
  projectId: string,
  title?: string
): Promise<AgentConversationOut> {
  return apiFetch(`/projects/${projectId}/agent/conversations`, {
    method: "POST",
    timeoutMs: 180000,
    body: JSON.stringify({
      title: title?.trim() || undefined,
    }),
  });
}

export function getAgentConversation(
  projectId: string,
  conversationId: string
): Promise<AgentConversationOut> {
  return apiFetch(`/projects/${projectId}/agent/conversations/${conversationId}`);
}

export function putAgentConversation(
  projectId: string,
  conversationId: string,
  body: {
    title?: string;
    messages?: AgentChatMessage[];
    chat_memory?: string;
    undo_stack?: unknown[];
  }
): Promise<AgentConversationOut> {
  return apiFetch(`/projects/${projectId}/agent/conversations/${conversationId}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

export function renameAgentConversation(
  projectId: string,
  conversationId: string,
  title: string
): Promise<AgentConversationOut> {
  return apiFetch(`/projects/${projectId}/agent/conversations/${conversationId}`, {
    method: "PATCH",
    body: JSON.stringify({ title }),
  });
}

export function deleteAgentConversation(
  projectId: string,
  conversationId: string
): Promise<{ ok: boolean }> {
  return apiFetch(`/projects/${projectId}/agent/conversations/${conversationId}`, {
    method: "DELETE",
  });
}

export function voiceCheck(
  id: string,
  body: { chapter_id?: string; draft?: string }
): Promise<VoiceReport> {
  return apiFetch(`/projects/${id}/voice-check`, {
    method: "POST",
    timeoutMs: 180000,
    body: JSON.stringify(body),
  });
}

interface ConsistencyIssue {
  category: "character" | "timeline" | "location" | "bible" | "plot" | "style";
  severity: "high" | "medium" | "low";
  chapterIds: string[];
  quote: string;
  description: string;
  suggestion: string;
}

export interface ConsistencyAuditResult {
  issues: ConsistencyIssue[];
  summary: string;
  scanned_chapters: number;
  model: string;
  error?: string;
}

export function consistencyAudit(
  id: string,
  body?: { focus?: string; chapter_id?: string }
): Promise<ConsistencyAuditResult> {
  return apiFetch(`/projects/${id}/consistency/audit`, {
    method: "POST",
    timeoutMs: 240000,
    body: JSON.stringify(body ?? {}),
  });
}

export interface StyleMemoryOut {
  project: import("../types/vn").VnProject;
  guide: string;
  samples: string[];
  model?: string;
}

export function learnStyleMemory(id: string): Promise<StyleMemoryOut> {
  return apiFetch(`/projects/${id}/style-memory/learn`, {
    method: "POST",
    timeoutMs: 240000,
  });
}

export function clearStyleMemory(
  id: string
): Promise<{ project: import("../types/vn").VnProject }> {
  return apiFetch(`/projects/${id}/style-memory`, {
    method: "DELETE",
  });
}

export type FactsChanged = {
  chapters: string[];
  bible: boolean;
  characters: string[];
  isFirstScan: boolean;
};

export function factsReconcile(id: string): Promise<{
  project: import("../types/vn").VnProject;
  changed: FactsChanged;
  staleCount: number;
  wrote?: boolean;
}> {
  return apiFetch(`/projects/${id}/analysis/facts/reconcile`, {
    method: "POST",
    timeoutMs: 180000,
    body: JSON.stringify({}),
  });
}

export function factsScan(
  id: string,
  body?: {
    chapter_id?: string;
    paste_text?: string;
    full?: boolean;
    persist_paste?: boolean;
  }
): Promise<{
  project: import("../types/vn").VnProject;
  changed: FactsChanged;
  summary: {
    added: number;
    characterLinks: number;
    timelineEvents: number;
  };
  inbox: import("../types/vn").FactInboxItem[];
}> {
  return apiFetch(`/projects/${id}/analysis/facts/scan`, {
    method: "POST",
    timeoutMs: 180000,
    body: JSON.stringify(body ?? {}),
  });
}

export function factsInbox(
  id: string
): Promise<{ items: import("../types/vn").FactInboxItem[] }> {
  return apiFetch(`/projects/${id}/analysis/facts/inbox`);
}

export function factsAccept(
  id: string,
  ids: string[]
): Promise<{
  acceptedIds: string[];
  skippedIds?: string[];
  project: import("../types/vn").VnProject;
}> {
  return apiFetch(`/projects/${id}/analysis/facts/accept`, {
    method: "POST",
    timeoutMs: 180000,
    body: JSON.stringify({ ids }),
  });
}

export function factsReject(
  id: string,
  ids: string[]
): Promise<{ rejectedIds: string[] }> {
  return apiFetch(`/projects/${id}/analysis/facts/reject`, {
    method: "POST",
    timeoutMs: 180000,
    body: JSON.stringify({ ids }),
  });
}

export function factsAckStale(
  id: string,
  body: { linkIds?: string[]; timelineIds?: string[]; all?: boolean }
): Promise<{ project: import("../types/vn").VnProject }> {
  return apiFetch(`/projects/${id}/analysis/facts/ack-stale`, {
    method: "POST",
    timeoutMs: 180000,
    body: JSON.stringify(body),
  });
}
