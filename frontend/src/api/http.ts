// Core HTTP layer: token storage, apiFetch, refresh, and error handling.
// Every domain module re-uses these primitives.
// Type-only import from ./auth (auth.ts imports values from here) — erased at
// runtime, so this does not create a runtime circular dependency.
import type { TokenOut } from "./auth";

export const TOKEN_KEY = "vnss-token";
export const REFRESH_TOKEN_KEY = "vnss-refresh-token";
export const API_BASE = "/api/v1";

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

export function getRefreshToken(): string | null {
  try {
    return localStorage.getItem(REFRESH_TOKEN_KEY);
  } catch {
    return null;
  }
}

export function setRefreshToken(token: string) {
  try {
    localStorage.setItem(REFRESH_TOKEN_KEY, token);
  } catch {
    /* ignore quota */
  }
}

export function clearRefreshToken() {
  try {
    localStorage.removeItem(REFRESH_TOKEN_KEY);
  } catch {
    /* ignore */
  }
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
          message:
            typeof obj.message === "string"
              ? obj.message
              : JSON.stringify(d),
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

export function redirectToLogin() {
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

  let res = await fetch(`${API_BASE}${path}`, { ...options, headers });

  // Expired access token → try one refresh, then replay the request once.
  if (res.status === 401 && !options.skipAuthRedirect) {
    if (await refreshOnce()) {
      const h2 = new Headers(options.headers);
      if (!isFormData && options.body != null && !h2.has("Content-Type")) {
        h2.set("Content-Type", "application/json");
      }
      const t2 = getToken();
      if (t2) h2.set("Authorization", `Bearer ${t2}`);
      res = await fetch(`${API_BASE}${path}`, { ...options, headers: h2 });
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
  const rt = getRefreshToken();
  if (!rt) return false;
  try {
    const res = await fetch(`${API_BASE}/auth/refresh`, {
      method: "POST",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify({ refresh_token: rt }),
    });
    if (!res.ok) return false;
    const data = (await res.json()) as TokenOut;
    if (data.access_token) {
      setToken(data.access_token);
      if (data.refresh_token) setRefreshToken(data.refresh_token);
      return true;
    }
    return false;
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
  const token = getToken();
  const headers = new Headers(options.headers);
  if (token) headers.set("Authorization", `Bearer ${token}`);
  let res = await fetch(`${API_BASE}${path}`, { ...options, headers });
  if (res.status === 401) {
    if (await refreshOnce()) {
      const h2 = new Headers(options.headers);
      const t2 = getToken();
      if (t2) h2.set("Authorization", `Bearer ${t2}`);
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
