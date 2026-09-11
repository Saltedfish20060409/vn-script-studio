/**
 * 产品埋点（前端侧）— 只上报「客户端才知道」的动作。
 *
 * 设计约束（见 docs/roadmap-2026-09.md 方向 B）：
 * - 只记动作是否发生，**绝不带正文/设定/Key**；
 * - fire-and-forget：失败绝不打扰用户，也不阻塞任何交互；
 * - 会话内去重同类事件（避免一次渲染打十遍），并限量；
 * - 攒批上报（默认 1.5s 合并一次），页面隐藏时用 keepalive 兜底。
 */

import { apiFetch } from "../api/http";

/** 与后端 app/core/analytics.py 的白名单保持一致。 */
export const EVENTS = {
  playtestOpened: "playtest_opened",
  exportDone: "export_done",
  proseSaved: "prose_saved",
  aiCall: "ai_call",
  shareCreated: "share_created",
  inviteSent: "invite_sent",
} as const;

type Props = Record<string, string | number | boolean>;

const SESSION_LIMIT = 60;
const FLUSH_DELAY_MS = 1500;

let queue: Array<{ name: string; props?: Props }> = [];
let sent = 0;
let timer: number | null = null;
const onceSeen = new Set<string>();
const sessionSeen = new Set<string>();

function flush(useKeepalive = false) {
  if (timer !== null) {
    window.clearTimeout(timer);
    timer = null;
  }
  if (queue.length === 0) return;
  const batch = queue.slice(0, 20);
  queue = queue.slice(20);
  // apiFetch 处理鉴权与 401 静默续期；失败就丢弃，不做重试（埋点不值得刷请求）。
  void apiFetch("/events", {
    method: "POST",
    body: JSON.stringify({ events: batch }),
    skipAuthRedirect: true,
  }).catch(() => undefined);
  if (useKeepalive) {
    // keepalive 仅在页面隐藏时使用：确保最后一个事件尽量发出去。
    try {
      const blob = JSON.stringify({ events: batch });
      navigator.sendBeacon?.("/api/v1/events", new Blob([blob], { type: "application/json" }));
    } catch {
      /* ignore */
    }
  }
}

function schedule() {
  if (timer !== null) return;
  timer = window.setTimeout(() => flush(false), FLUSH_DELAY_MS);
}

/**
 * 上报一个事件。
 * @param name 事件名（必须与后端白名单一致）
 * @param props 只允许白名单键（后端会再过滤一次）
 * @param opts.once 同一会话只报一次（用于"首次"类动作）
 */
export function track(name: string, props?: Props, opts?: { once?: boolean }): void {
  if (typeof window === "undefined") return;
  if (sent >= SESSION_LIMIT) return;
  if (opts?.once) {
    if (sessionSeen.has(name)) return;
    sessionSeen.add(name);
  }
  queue.push({ name, props });
  sent += 1;
  schedule();
}

/** 每用户只报一次（跨刷新用 localStorage 记住，避免"首次"被反复上报）。 */
export function trackOncePerUser(name: string, props?: Props): void {
  if (typeof window === "undefined") return;
  const key = `vnss-tracked:${name}`;
  try {
    if (localStorage.getItem(key)) return;
    localStorage.setItem(key, "1");
  } catch {
    /* storage 不可用就退化成会话内一次 */
  }
  track(name, props, { once: true });
}

if (typeof window !== "undefined") {
  const onHide = () => {
    if (document.visibilityState === "hidden") flush(true);
  };
  document.addEventListener("visibilitychange", onHide);
  window.addEventListener("pagehide", () => flush(true));
}

/** 仅测试用：清空内部状态。 */
export function __resetTrackForTest(): void {
  queue = [];
  sent = 0;
  if (timer !== null) {
    window.clearTimeout(timer);
    timer = null;
  }
  onceSeen.clear();
  sessionSeen.clear();
}
