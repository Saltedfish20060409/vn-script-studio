/**
 * 错误上报 — 全局捕获 window error / unhandledrejection / React 边界错误，
 * fire-and-forget 发送到 /api/v1/errors（后端按 IP 限流、存库诊断）。
 * 会话内去重 + 限量，绝不影响主流程。
 */

import { getToken } from "../api/http";

const SESSION_LIMIT = 20;
let sentCount = 0;
const seenMessages = new Set<string>();

/**
 * 已知噪音：这些消息对我们没有可操作性，上报只会淹没真问题。
 * （线上 43 条报错里绝大多数是这个 ResizeObserver 提示。）
 */
const NOISE_PATTERNS: RegExp[] = [
  /ResizeObserver loop (completed with undelivered notifications|limit exceeded)/i,
];

export function isBenignNoise(message: string): boolean {
  return NOISE_PATTERNS.some((re) => re.test(message || ""));
}

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
  if (isBenignNoise(message)) return;
  if (sentCount >= SESSION_LIMIT) return;
  const key = `${payload.component || ""}:${message}`;
  if (seenMessages.has(key)) return;
  seenMessages.add(key);
  sentCount += 1;

  try {
    // SECURITY (M-4): token is memory-only (see api/http.ts) — localStorage
    // never holds it, so reading it there sent anonymous reports.
    const token = getToken() || "";
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
  installChunkReloadGuard();
}

/**
 * 部署后"白屏"的防治：老页面上的懒加载 chunk 已经不存在了，动态 import 会失败。
 *
 * 触发场景：用户开着旧标签页，我们发布了新版本（assets 文件名带新哈希，旧的被删）。
 * 这时点进任意懒加载路由（如登录页、工坊）就会报
 * "Failed to fetch dynamically imported module" —— 线上确实出现过。
 *
 * 处理：自动刷新一次（新 HTML 会引用新 chunk），并用 sessionStorage 做 60 秒防抖，
 * 避免"刷新后仍然失败"时陷入无限刷新。
 */
const CHUNK_RELOAD_KEY = "vnss-chunk-reload-at";
const CHUNK_RELOAD_COOLDOWN_MS = 60_000;

/**
 * 是否允许为"chunk 加载失败"再刷一次页面（纯函数，便于测试）。
 *
 * @param lastReloadAt 上次自动刷新的时间戳（0 = 从没刷过）
 * @param now          当前时间
 * @param cooldownMs   冷却窗口：窗口内已经刷过就不再刷，避免无限刷新
 */
export function shouldReloadForChunkError(
  lastReloadAt: number,
  now: number,
  cooldownMs: number = CHUNK_RELOAD_COOLDOWN_MS
): boolean {
  if (!Number.isFinite(lastReloadAt) || lastReloadAt <= 0) return true;
  return now - lastReloadAt >= cooldownMs;
}

function installChunkReloadGuard(): void {
  window.addEventListener("vite:preloadError", (event) => {
    let last: number;
    try {
      last = Number(sessionStorage.getItem(CHUNK_RELOAD_KEY) || "0");
    } catch {
      last = 0;
    }
    if (!shouldReloadForChunkError(last, Date.now())) {
      // 刚刷过还是失败：交给错误边界提示，不要再刷新
      return;
    }
    try {
      sessionStorage.setItem(CHUNK_RELOAD_KEY, String(Date.now()));
    } catch {
      /* sessionStorage 不可用时也允许刷一次 */
    }
    (event as Event & { preventDefault?: () => void }).preventDefault?.();
    reportError({
      message: "chunk 加载失败（版本已更新），自动刷新一次",
      component: "chunk",
      level: "warn",
    });
    window.location.reload();
  });
}
