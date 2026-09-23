// Core HTTP layer: token storage, apiFetch, refresh, and error handling.
// Every domain module re-uses these primitives.
// Type-only import from ./auth (auth.ts imports values from here) — erased at
// runtime, so this does not create a runtime circular dependency.
import type { TokenOut } from "./auth";
import { applyLlmHeaders } from "../lib/llmCredentials";
import { TIMEOUTS, networkErrorMessage, timeoutMessage } from "./timeouts";

export const API_BASE = "/api/v1";

let accessToken: string | null = null;

export function getToken(): string | null {
  return accessToken;
}

export function setToken(token: string) {
  accessToken = token;
}

export function clearToken() {
  accessToken = null;
}

function clearRefreshToken() {
  // No-op: cookie is cleared via POST /auth/logout.
}

export class ApiError extends Error {
  status: number;
  /** Parsed JSON `detail` when the API returns an object (e.g. 409 conflict). */
  detail?: unknown;
  constructor(status: number, message: string, detail?: unknown) {
    super(message);
    this.name = "ApiError";
    this.status = status;
    this.detail = detail;
  }
}

interface ApiFetchOptions extends RequestInit {
  /** Skip the auto clear-token + redirect-to-login behavior on 401 (used by public endpoints). */
  skipAuthRedirect?: boolean;
  /**
   * Per-request timeout. LLM endpoints MUST pass an explicit `TIMEOUTS.*` budget —
   * the fast default is only safe for non-LLM reads/writes (see ./timeouts.ts).
   */
  timeoutMs?: number;
}

export async function readErrorPayload(
  res: Response
): Promise<{ message: string; detail?: unknown }> {
  try {
    const data = await res.clone().json();
    if (data && typeof data === "object") {
      const d = (data as { detail?: unknown }).detail;
      if (typeof d === "string") return { message: d, detail: d };
      if (d && typeof d === "object") {
        const obj = d as { message?: string };
        return {
          message: typeof obj.message === "string" ? obj.message : JSON.stringify(d),
          detail: d,
        };
      }
      if (typeof (data as { message?: string }).message === "string") {
        return { message: (data as { message: string }).message };
      }
    }
  } catch {
    /* not JSON */
  }
  try {
    const text = await res.text();
    if (text) return { message: text };
  } catch {
    /* ignore */
  }
  return { message: res.statusText || `请求失败 (${res.status})` };
}

function redirectToLogin() {
  if (typeof window === "undefined") return;
  if (window.location.pathname === "/login") return;
  window.location.href = "/login";
}

/**
 * Default per-request timeout. Only safe for non-LLM endpoints — anything that
 * calls a model inside the request must pass an explicit `TIMEOUTS.*` budget.
 */
const REQUEST_TIMEOUT_MS = TIMEOUTS.fast;

async function fetchWithTimeout(
  input: string,
  init: RequestInit & { timeoutMs?: number }
): Promise<Response> {
  const timeout = init.timeoutMs ?? REQUEST_TIMEOUT_MS;
  const controller = new AbortController();
  const timer = window.setTimeout(() => controller.abort(), timeout);
  try {
    return await fetch(input, { ...init, signal: controller.signal });
  } catch (e) {
    if ((e as { name?: string })?.name === "AbortError") {
      // NOTE: 这里**不能**说"请检查后端"。后端通常完全正常，只是这次调用比预算慢；
      // 此前写成「请确认后端服务已启动」，慢思考模型的用户被这句话带偏了很久。
      throw new ApiError(408, timeoutMessage(timeout));
    }
    throw new ApiError(0, networkErrorMessage());
  } finally {
    window.clearTimeout(timer);
  }
}

/**
 * 作者所在地相对 UTC 的分钟偏移（东八区 = +480）。
 *
 * 为什么每个请求都带上它：写作活动（热力图 / 连载页的今日净增、连续更新天数）在后端是
 * 按**作者当地日期**记账的。不带这个头后端只能退回 UTC，于是东八区用户在本地
 * 00:00–08:00 写的字会落到前一天，连载页的「今日净增」在早上永远是 0。
 * 放在 `buildApiHeaders` 里统一带，是为了避免以后新增一条保存路径时漏掉——
 * 那种漏法在界面上表现为"数据不见了"，很难查。
 */
export function tzOffsetMinutes(now: Date = new Date()): number {
  // getTimezoneOffset 的符号与 ISO 相反（UTC+8 返回 -480）
  return -now.getTimezoneOffset();
}

/** Auth + browser-local LLM credentials (X-LLM-*). */
export function buildApiHeaders(init?: HeadersInit, jsonBody = false): Headers {
  const headers = new Headers(init);
  if (jsonBody && !headers.has("Content-Type")) {
    headers.set("Content-Type", "application/json");
  }
  const token = getToken();
  if (token) headers.set("Authorization", `Bearer ${token}`);
  if (!headers.has("X-TZ-Offset")) {
    headers.set("X-TZ-Offset", String(tzOffsetMinutes()));
  }
  applyLlmHeaders(headers);
  return headers;
}

/** Core fetch helper: prefixes /api/v1, attaches bearer token, handles JSON. */
export async function apiFetch<T = unknown>(
  path: string,
  options: ApiFetchOptions = {}
): Promise<T> {
  const isFormData =
    typeof FormData !== "undefined" && options.body instanceof FormData;
  const headers = buildApiHeaders(options.headers, !isFormData && options.body != null);

  let res = await fetchWithTimeout(`${API_BASE}${path}`, {
    ...options,
    headers,
  });

  // Expired access token → try one refresh, then replay the request once.
  // Refresh is attempted on ANY 401 (skipAuthRedirect only controls the final
  // redirect-to-login). Rationale: me() runs on every page mount including
  // public pages (/verify-email, /reset-password…). It must still be able to
  // restore a session via the refresh cookie, but its failure must NOT bounce
  // an anonymous visitor away from a public page before that page can act.
  if (res.status === 401) {
    if (await refreshOnce()) {
      const h2 = buildApiHeaders(
        options.headers,
        !isFormData && options.body != null
      );
      res = await fetchWithTimeout(`${API_BASE}${path}`, {
        ...options,
        headers: h2,
      });
    }
  }

  if (res.status === 401) {
    clearToken();
    clearRefreshToken();
    if (!options.skipAuthRedirect) redirectToLogin();
    throw new ApiError(401, "未登录或登录已过期");
  }

  if (!res.ok) {
    const err = await readErrorPayload(res);
    throw new ApiError(res.status, err.message, err.detail);
  }

  if (res.status === 204) return undefined as T;

  const contentType = res.headers.get("content-type") || "";
  if (contentType.includes("application/json")) {
    return (await res.json()) as T;
  }
  return (await res.text()) as unknown as T;
}

let refreshPromise: Promise<boolean> | null = null;

async function tryRefresh(): Promise<boolean> {
  // The refresh token is an HttpOnly cookie — fetch sends it automatically
  // (same-origin). No body, no local storage read.
  try {
    // A network blackhole must not leave every concurrent 401 replay waiting
    // forever — cap the refresh round-trip at 10s.
    const controller = new AbortController();
    const timer = window.setTimeout(() => controller.abort(), 10_000);
    try {
      const res = await fetch(`${API_BASE}/auth/refresh`, {
        method: "POST",
        credentials: "same-origin",
        signal: controller.signal,
      });
      if (!res.ok) return false;
      const data = (await res.json()) as TokenOut;
      if (data.access_token) {
        setToken(data.access_token);
        return true;
      }
      return false;
    } finally {
      window.clearTimeout(timer);
    }
  } catch {
    return false;
  }
}

/** Deduped refresh — concurrent 401s share one refresh round-trip. */
export function refreshOnce(): Promise<boolean> {
  if (!refreshPromise) {
    refreshPromise = tryRefresh().finally(() => {
      refreshPromise = null;
    });
  }
  return refreshPromise;
}

/** Raw fetch for binary/text downloads (keeps headers/blob semantics intact). */
export async function authedRawFetch(
  path: string,
  options: RequestInit = {}
): Promise<Response> {
  const headers = buildApiHeaders(options.headers);
  let res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (res.status === 401) {
    if (await refreshOnce()) {
      const h2 = buildApiHeaders(options.headers);
      res = await fetch(`${API_BASE}${path}`, { ...options, headers: h2 });
    }
  }
  if (res.status === 401) {
    clearToken();
    clearRefreshToken();
    redirectToLogin();
    throw new ApiError(401, "未登录或登录已过期");
  }
  if (!res.ok) {
    const err = await readErrorPayload(res);
    throw new ApiError(res.status, err.message, err.detail);
  }
  return res;
}
