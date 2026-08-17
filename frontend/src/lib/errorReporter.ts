/**
 * 错误上报 — 全局捕获 window error / unhandledrejection / React 边界错误，
 * fire-and-forget 发送到 /api/v1/errors（后端按 IP 限流、存库诊断）。
 * 会话内去重 + 限量，绝不影响主流程。
 */

const SESSION_LIMIT = 20;
let sentCount = 0;
const seenMessages = new Set<string>();

export interface ErrorPayload {
  message: string;
  stack?: string;
  url?: string;
  level?: "error" | "warn";
  component?: string;
}

export function reportError(payload: ErrorPayload): void {
  if (typeof window === "undefined") return;
  const message = (payload.message || "").slice(0, 2000);
  if (!message) return;
  if (sentCount >= SESSION_LIMIT) return;
  const key = `${payload.component || ""}:${message}`;
  if (seenMessages.has(key)) return;
  seenMessages.add(key);
  sentCount += 1;

  try {
    const token = localStorage.getItem("vnss-token") || "";
    void fetch("/api/v1/errors", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
        ...(token ? { Authorization: `Bearer ${token}` } : {}),
      },
      body: JSON.stringify({
        message,
        stack: (payload.stack || "").slice(0, 8000),
        url: (payload.url || window.location.href).slice(0, 1024),
        level: payload.level ?? "error",
        component: (payload.component || "").slice(0, 64),
      }),
      keepalive: true,
    }).catch(() => {
      /* fire-and-forget */
    });
  } catch {
    /* never break the app for reporting */
  }
}

function installGlobalHandlers(): void {
  window.addEventListener("error", (e) => {
    reportError({
      message: e.message || "Uncaught error",
      stack: e.error?.stack || "",
      component: "window",
    });
  });
  window.addEventListener("unhandledrejection", (e) => {
    const reason = e.reason as { message?: string; stack?: string } | string | undefined;
    reportError({
      message:
        typeof reason === "string" ? reason : reason?.message || "Unhandled rejection",
      stack: typeof reason === "object" ? reason?.stack || "" : "",
      component: "promise",
    });
  });
}

export function installErrorReporter(): void {
  if (typeof window === "undefined") return;
  installGlobalHandlers();
}
