/**
 * 公告（更新日志）相关的小工具。
 *
 * 后端 /notice 同时返回"最新一版的顶层字段"（兼容旧前端）与 announcements 列表，
 * 这里负责把两种形状统一成一份可渲染的列表，并提供一个全局打开事件——
 * 顶栏「更多 → 更新公告」用它把已经关掉的公告重新叫出来。
 */

export type NoticeSection = { heading: string; body: string };

export type Announcement = {
  version: number;
  title: string;
  updatedAt: string;
  sections: NoticeSection[];
};

export type NoticePayload = {
  version?: number;
  title?: string;
  updatedAt?: string;
  sections?: NoticeSection[];
  announcements?: Announcement[];
};

/** 打开公告的事件名（顶栏派发、公告组件监听）。 */
export const NOTICE_OPEN_EVENT = "vnss:open-notice";

export function openNotice(): void {
  if (typeof window === "undefined") return;
  window.dispatchEvent(new Event(NOTICE_OPEN_EVENT));
}

/**
 * 把接口返回统一成**按版本倒序**的公告列表。
 *
 * - 新版后端：直接用 announcements；
 * - 旧后端 / 旧缓存：只有顶层那几个字段，就把它当成唯一一条；
 * - 顺手按 version 倒序、去掉没有内容的条目，避免界面出现空壳。
 */
export function resolveAnnouncements(payload: NoticePayload | null | undefined): Announcement[] {
  if (!payload) return [];
  const raw = Array.isArray(payload.announcements) && payload.announcements.length
    ? payload.announcements
    : [
        {
          version: Number(payload.version) || 0,
          title: payload.title || "",
          updatedAt: payload.updatedAt || "",
          sections: payload.sections || [],
        },
      ];
  return raw
    .filter((a) => a && Number(a.version) > 0 && (a.sections || []).length > 0)
    .slice()
    .sort((a, b) => b.version - a.version);
}

/** 列表里那一行的小标题：更新日志写「更新 v6」，欢迎公告写「欢迎 v5」。 */
export function announcementBadge(a: Announcement, isLatest: boolean): string {
  const base = a.title.includes("更新") ? `更新 v${a.version}` : `v${a.version}`;
  return isLatest ? `${base} · 最新` : base;
}

/** 日期显示成 2026-09-16 这种稳定格式（接口本来就给这个格式，兜底防止异常值）。 */
export function formatNoticeDate(value: string): string {
  const t = (value || "").trim();
  return /^\d{4}-\d{2}-\d{2}$/.test(t) ? t : t.slice(0, 10) || "—";
}
