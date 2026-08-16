import type { VnProject } from "../types/vn";
import { API_BASE, apiFetch, getToken } from "./http";
// ---------------------------------------------------------------------------
// Writing pipeline (Plan → Write → Check → Revise + quality gate)
// ---------------------------------------------------------------------------

export interface PipelineGate {
  pass: boolean;
  errorCount?: number;
  warnCount?: number;
  message?: string;
  blockers?: Array<{ severity?: string; code?: string; message?: string }>;
}

export interface PipelineRunResult {
  stages: string[];
  plan?: { content?: string; beatSheet?: Record<string, unknown> | null };
  draft?: string;
  finalDraft?: string;
  check?: {
    pass?: boolean;
    errorCount?: number;
    warnCount?: number;
    notes?: string[];
    issues?: Array<{ severity: string; code: string; message: string }>;
    beatMode?: string;
    voiceChecked?: boolean;
  };
  revise?: { content?: string; skipped?: boolean; message?: string };
  reviseRounds?: number;
  runId?: string;
  gate?: PipelineGate;
  applied?: boolean;
  applyError?: string;
  project?: VnProject;
  enrichMeta?: {
    enrich?: boolean;
    factCount?: number;
    stateCount?: number;
    foreshadowCount?: number;
    error?: string | null;
  };
  trace?: Array<{
    stage?: string;
    ms?: number;
    ok?: boolean;
    errorCount?: number;
    warnCount?: number;
    beatMode?: string;
    blockTypes?: string[];
    [key: string]: unknown;
  }>;
}

export function pipelineMeta(): Promise<{
  layers: string[];
  styleSkill: Record<string, unknown>;
  styleConfirm: string;
  defaultStages: string[];
  defaults?: {
    maxReviseRounds?: number;
    voiceCheck?: boolean;
    semanticBeats?: boolean;
    enrichLedgerOnFinalize?: boolean;
  };
}> {
  return apiFetch("/pipeline/meta");
}

export function pipelineRun(
  id: string,
  body: {
    instruction?: string;
    draft?: string;
    selection?: string;
    chapter_id?: string;
    stages?: Array<"plan" | "write" | "check" | "revise">;
    apply_to_chapter?: boolean;
    apply_mode?: "replace" | "append";
    max_revise_rounds?: number;
    voice_check?: boolean;
    voice_hard?: boolean;
    semantic_beats?: boolean;
    async_mode?: boolean;
  }
): Promise<PipelineRunResult | { jobId: string; async: true; status: string }> {
  return apiFetch(`/projects/${id}/pipeline/run`, {
    method: "POST",
    timeoutMs: 180000,
    body: JSON.stringify(body),
  });
}

export type PipelineStreamEvent =
  | {
      type: "stage";
      stage: string;
      ms?: number;
      ok?: boolean;
      errorCount?: number;
      warnCount?: number;
    }
  | { type: "token"; delta: string }
  | { type: "final"; result?: JobStatus };

/**
 * Streaming pipeline run (async_mode + stream). Resolves with the final JobStatus;
 * `onEvent` receives each stage-complete event as it happens.
 */
export async function pipelineRunStream(
  id: string,
  body: Parameters<typeof pipelineRun>[1] & { stream?: boolean },
  onEvent: (evt: PipelineStreamEvent) => void,
  signal?: AbortSignal
): Promise<JobStatus> {
  const token = getToken();
  const res = await fetch(`${API_BASE}/projects/${id}/pipeline/run`, {
    method: "POST",
    headers: {
      "Content-Type": "application/json",
      ...(token ? { Authorization: `Bearer ${token}` } : {}),
    },
    body: JSON.stringify({ ...body, async_mode: true, stream: true }),
    signal,
  });
  if (!res.ok || !res.body) {
    const detail = await res.text().catch(() => `HTTP ${res.status}`);
    throw new Error(detail || `HTTP ${res.status}`);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalResult: JobStatus | null = null;
  for (;;) {
    if (signal?.aborted) {
      reader.cancel().catch(() => undefined);
      throw new Error("请求已取消");
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
      let evt: PipelineStreamEvent;
      try {
        evt = JSON.parse(payload) as PipelineStreamEvent;
      } catch {
        continue;
      }
      onEvent(evt);
      if (evt.type === "final" && evt.result) finalResult = evt.result;
    }
    if (done) break;
  }
  if (!finalResult) throw new Error("流水线流式响应缺少最终结果");
  return finalResult;
}

export type JobStatus = {
  id: string;
  kind: string;
  projectId: string;
  status: "queued" | "running" | "done" | "error" | string;
  stage?: string;
  progress?: number;
  message?: string;
  error?: string | null;
  result?: Record<string, unknown>;
  createdAt?: string;
  updatedAt?: string;
};

export function getProjectJob(projectId: string, jobId: string): Promise<JobStatus> {
  return apiFetch(`/projects/${projectId}/jobs/${jobId}`);
}

/** Poll until job done/error or timeout. */
export async function waitProjectJob(
  projectId: string,
  jobId: string,
  opts?: {
    intervalMs?: number;
    timeoutMs?: number;
    onTick?: (job: JobStatus) => void;
  }
): Promise<JobStatus> {
  const interval = opts?.intervalMs ?? 1200;
  const timeout = opts?.timeoutMs ?? 15 * 60 * 1000;
  const start = Date.now();
  for (;;) {
    const job = await getProjectJob(projectId, jobId);
    opts?.onTick?.(job);
    if (job.status === "done" || job.status === "error") return job;
    if (Date.now() - start > timeout) {
      throw new Error("任务等待超时，请稍后在运行记录中查看");
    }
    await new Promise((r) => setTimeout(r, interval));
  }
}

export function pipelineGate(
  id: string,
  body: {
    draft?: string;
    chapter_id?: string;
    require_zero_warn?: boolean;
    finalize?: boolean;
    update_ledger?: boolean;
    apply_draft?: boolean;
    enrich_ledger?: boolean;
    voice_check?: boolean;
    voice_hard?: boolean;
    semantic_beats?: boolean;
  }
): Promise<{
  check?: PipelineRunResult["check"];
  gate: PipelineGate;
  qualityGate?: Record<string, unknown>;
  project?: VnProject | null;
  ledgerUpdated?: boolean;
  applied?: boolean;
  enrichMeta?: PipelineRunResult["enrichMeta"];
}> {
  return apiFetch(`/projects/${id}/pipeline/gate`, {
    method: "POST",
    timeoutMs: 180000,
    body: JSON.stringify(body),
  });
}

export function pipelineRuns(
  id: string,
  limit = 12
): Promise<{ runs: Array<Record<string, unknown>> }> {
  return apiFetch(`/projects/${id}/pipeline/runs?limit=${limit}`);
}

export function pipelineLedgerDigest(
  id: string,
  chapterId: string,
  opts?: { enrich?: boolean }
): Promise<{
  ledger: unknown;
  agentBlock: string;
  project: VnProject;
  enrichMeta?: {
    enrich?: boolean;
    factCount?: number;
    stateCount?: number;
    foreshadowCount?: number;
    error?: string | null;
  };
}> {
  return apiFetch(`/projects/${id}/pipeline/ledger/digest`, {
    method: "POST",
    timeoutMs: 180000,
    body: JSON.stringify({
      chapter_id: chapterId,
      enrich: opts?.enrich !== false,
    }),
  });
}
