import type {
  AgentAction,
  AgentChatMessage,
  AgentContextMeta,
  AgentTaskKind,
  VnProject,
  VoiceReport,
} from "../types/vn";
import type { ServerSettingsOut } from "../lib/settings";

export const TOKEN_KEY = "vnss-token";
const API_BASE = "/api/v1";

export function getToken(): string | null {
  try {
    return localStorage.getItem(TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setToken(token: string) {
  try {
    localStorage.setItem(TOKEN_KEY, token);
  } catch {
    /* ignore quota */
  }
}

export function clearToken() {
  try {
    localStorage.removeItem(TOKEN_KEY);
  } catch {
    /* ignore */
  }
}

export class ApiError extends Error {
  status: number;
  constructor(status: number, message: string) {
    super(message);
    this.name = "ApiError";
    this.status = status;
  }
}

interface ApiFetchOptions extends RequestInit {
  /** Skip the auto clear-token + redirect-to-login behavior on 401 (used by public endpoints). */
  skipAuthRedirect?: boolean;
}

async function readErrorDetail(res: Response): Promise<string> {
  try {
    const data = await res.clone().json();
    if (data && typeof data === "object") {
      if (typeof data.detail === "string") return data.detail;
      if (typeof data.message === "string") return data.message;
    }
  } catch {
    /* not JSON */
  }
  try {
    const text = await res.text();
    if (text) return text;
  } catch {
    /* ignore */
  }
  return res.statusText || `请求失败 (${res.status})`;
}

function redirectToLogin() {
  if (typeof window === "undefined") return;
  if (window.location.pathname === "/login") return;
  window.location.href = "/login";
}

/** Core fetch helper: prefixes /api/v1, attaches bearer token, handles JSON. */
export async function apiFetch<T = unknown>(
  path: string,
  options: ApiFetchOptions = {}
): Promise<T> {
  const token = getToken();
  const headers = new Headers(options.headers);
  const isFormData =
    typeof FormData !== "undefined" && options.body instanceof FormData;
  if (!isFormData && options.body != null && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  if (token) headers.set("Authorization", `Bearer ${token}`);

  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });

  if (res.status === 401) {
    clearToken();
    if (!options.skipAuthRedirect) redirectToLogin();
    throw new ApiError(401, "未登录或登录已过期");
  }

  if (!res.ok) {
    throw new ApiError(res.status, await readErrorDetail(res));
  }

  if (res.status === 204) return undefined as T;

  const contentType = res.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return (await res.json()) as T;
  }
  return (await res.text()) as unknown as T;
}

/** Raw fetch for binary/text downloads (keeps headers/blob semantics intact). */
async function authedRawFetch(
  path: string,
  options: RequestInit = {}
): Promise<Response> {
  const token = getToken();
  const headers = new Headers(options.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  const res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (res.status === 401) {
    clearToken();
    redirectToLogin();
    throw new ApiError(401, "未登录或登录已过期");
  }
  if (!res.ok) {
    throw new ApiError(res.status, await readErrorDetail(res));
  }
  return res;
}

// ---------------------------------------------------------------------------
// Auth
// ---------------------------------------------------------------------------

export interface TokenOut {
  access_token: string;
  token_type: string;
}

export interface UserOut {
  id: string;
  username: string;
  created_at: string;
}

export async function register(
  username: string,
  password: string
): Promise<TokenOut> {
  const data = await apiFetch<TokenOut>("/auth/register", {
    method: "POST",
    body: JSON.stringify({ username, password }),
    skipAuthRedirect: true,
  });
  setToken(data.access_token);
  return data;
}

export async function login(
  username: string,
  password: string
): Promise<TokenOut> {
  const data = await apiFetch<TokenOut>("/auth/login", {
    method: "POST",
    body: JSON.stringify({ username, password }),
    skipAuthRedirect: true,
  });
  setToken(data.access_token);
  return data;
}

export function me(): Promise<UserOut> {
  return apiFetch<UserOut>("/auth/me");
}

// ---------------------------------------------------------------------------
// Projects
// ---------------------------------------------------------------------------

export interface ProjectSummary {
  id: string;
  title: string;
  logline?: string | null;
  genre?: string | null;
  updated_at: string;
  created_at: string;
}

export function listProjects(): Promise<ProjectSummary[]> {
  return apiFetch<ProjectSummary[]>("/projects");
}

export function getProject(id: string): Promise<VnProject> {
  return apiFetch<VnProject>(`/projects/${id}`);
}

export function createProject(
  body: { title?: string; from_demo?: boolean } = {}
): Promise<VnProject> {
  return apiFetch<VnProject>("/projects", {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function putProject(
  id: string,
  data: VnProject,
  updatedAt?: string
): Promise<VnProject> {
  return apiFetch<VnProject>(`/projects/${id}`, {
    method: "PUT",
    body: JSON.stringify({ data, updated_at: updatedAt }),
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

export function importProjectFile(
  file: File,
  title?: string
): Promise<VnProject> {
  const form = new FormData();
  form.append("file", file);
  if (title) form.append("title", title);
  return apiFetch<VnProject>("/projects/import", {
    method: "POST",
    body: form,
  });
}

export function importProjectJson(
  obj: unknown,
  title?: string
): Promise<VnProject> {
  const form = new FormData();
  form.append("json_body", JSON.stringify(obj));
  if (title) form.append("title", title);
  return apiFetch<VnProject>("/projects/import", {
    method: "POST",
    body: form,
  });
}

export function importProjectText(
  text: string,
  title?: string
): Promise<VnProject> {
  const form = new FormData();
  form.append("text", text);
  if (title) form.append("title", title);
  return apiFetch<VnProject>("/projects/import", {
    method: "POST",
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

export function mapExtract(
  id: string
): Promise<{ project: VnProject; addedCount: number; linkCount: number }> {
  return apiFetch(`/projects/${id}/map/extract`, { method: "POST" });
}

export interface BranchNodeDto {
  id: string;
  kind: "label" | "menu" | "choice" | "jump" | "end";
  title: string;
  children: BranchNodeDto[];
}

export function branchTree(id: string): Promise<{ nodes: BranchNodeDto[] }> {
  return apiFetch(`/projects/${id}/analysis/branch-tree`, { method: "POST" });
}

export function lint(
  id: string,
  draft: string
): Promise<{ issues: Record<string, unknown>[] }> {
  return apiFetch(`/projects/${id}/analysis/lint`, {
    method: "POST",
    body: JSON.stringify({ draft }),
  });
}

// ---------------------------------------------------------------------------
// Snapshots
// ---------------------------------------------------------------------------

export interface SnapshotSummary {
  id: string;
  label: string;
  createdAt: string;
}

export function listSnapshots(id: string): Promise<SnapshotSummary[]> {
  return apiFetch(`/projects/${id}/snapshots`);
}

export function createSnapshot(
  id: string,
  label: string
): Promise<SnapshotSummary> {
  return apiFetch(`/projects/${id}/snapshots`, {
    method: "POST",
    body: JSON.stringify({ label }),
  });
}

export function restoreSnapshot(
  id: string,
  snapshotId: string
): Promise<VnProject> {
  return apiFetch(`/projects/${id}/snapshots/${snapshotId}/restore`, {
    method: "POST",
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

// ---------------------------------------------------------------------------
// Agent
// ---------------------------------------------------------------------------

export interface AgentRunInBody {
  messages: AgentChatMessage[];
  chapter_id?: string;
  selection?: string;
  task?: AgentTaskKind;
  chat_memory?: string;
  conversation_id?: string;
  apply_actions?: boolean;
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
}

export function runAgent(
  id: string,
  body: AgentRunInBody
): Promise<AgentRunOut> {
  return apiFetch(`/projects/${id}/agent`, {
    method: "POST",
    body: JSON.stringify(body),
  });
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
    body: JSON.stringify({
      title: title?.trim() || undefined,
    }),
  });
}

export function getAgentConversation(
  projectId: string,
  conversationId: string
): Promise<AgentConversationOut> {
  return apiFetch(
    `/projects/${projectId}/agent/conversations/${conversationId}`
  );
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
  return apiFetch(
    `/projects/${projectId}/agent/conversations/${conversationId}`,
    {
      method: "PUT",
      body: JSON.stringify(body),
    }
  );
}

export function renameAgentConversation(
  projectId: string,
  conversationId: string,
  title: string
): Promise<AgentConversationOut> {
  return apiFetch(
    `/projects/${projectId}/agent/conversations/${conversationId}`,
    {
      method: "PATCH",
      body: JSON.stringify({ title }),
    }
  );
}

export function deleteAgentConversation(
  projectId: string,
  conversationId: string
): Promise<{ ok: boolean }> {
  return apiFetch(
    `/projects/${projectId}/agent/conversations/${conversationId}`,
    { method: "DELETE" }
  );
}

/** @deprecated prefer conversation APIs */
export type AgentSessionOut = AgentConversationOut;

/** @deprecated prefer putAgentConversation */
export function getAgentSession(id: string): Promise<AgentSessionOut> {
  return apiFetch(`/projects/${id}/agent/session`);
}

/** @deprecated prefer putAgentConversation */
export function putAgentSession(
  id: string,
  body: {
    messages?: AgentChatMessage[];
    chat_memory?: string;
    undo_stack?: unknown[];
    title?: string;
  }
): Promise<AgentSessionOut> {
  return apiFetch(`/projects/${id}/agent/session`, {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

export function voiceCheck(
  id: string,
  body: { chapter_id?: string; draft?: string }
): Promise<VoiceReport> {
  return apiFetch(`/projects/${id}/voice-check`, {
    method: "POST",
    body: JSON.stringify(body),
  });
}

export function runAi(
  id: string,
  body: {
    action: string;
    selection?: string;
    instruction?: string;
    format?: "renpy" | "blocks-json";
  }
): Promise<{ content: string; model: string }> {
  return apiFetch(`/projects/${id}/ai`, {
    method: "POST",
    body: JSON.stringify(body),
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
}

export function getShare(token: string): Promise<ShareOut> {
  return apiFetch(`/shares/${token}`, { skipAuthRedirect: true });
}

export function revokeShare(
  id: string,
  token: string
): Promise<{ ok: boolean }> {
  return apiFetch(`/projects/${id}/shares/${token}`, { method: "DELETE" });
}

// ---------------------------------------------------------------------------
// Settings
// ---------------------------------------------------------------------------

export function getSettings(): Promise<ServerSettingsOut> {
  return apiFetch<ServerSettingsOut>("/settings");
}

export function putSettings(
  body: Record<string, unknown>
): Promise<ServerSettingsOut> {
  return apiFetch<ServerSettingsOut>("/settings", {
    method: "PUT",
    body: JSON.stringify(body),
  });
}
