import { useCallback, useEffect, useMemo, useState } from "react";
import { apiFetch } from "../api/http";
import {
  NOTICE_OPEN_EVENT,
  announcementBadge,
  formatNoticeDate,
  resolveAnnouncements,
  type Announcement,
  type NoticePayload,
} from "../lib/notice";
import styles from "./NoticeBanner.module.css";

const READ_KEY = "vnss-notice-read-v";

function isRead(version: number): boolean {
  try {
    return localStorage.getItem(READ_KEY + version) === "1";
  } catch {
    return false;
  }
}

function markRead(version: number): void {
  try {
    localStorage.setItem(READ_KEY + version, "1");
  } catch {
    /* ignore */
  }
}

/**
 * 公告弹窗：左边一栏是历史公告的名字，右边是正文（像游戏更新公告那样）。
 *
 * 它是**全局单例**（只在 App 根渲染一次）：
 * - 未读版本自动弹出一次；
 * - 顶栏「更多 → 更新公告」、登录页「公告」按钮通过 openNotice() 派发事件把它叫出来
 *   （已读也能复看）；
 * - 关掉时把**最新一版**标记为已读 —— 只翻了旧的那几版不算读完。
 */
export function NoticeBanner() {
  const [payload, setPayload] = useState<NoticePayload | null>(null);
  const [open, setOpen] = useState(false);
  const [selected, setSelected] = useState(0);

  // 顶栏 / 登录页的「公告」入口：派发事件即可把弹窗叫出来
  useEffect(() => {
    const onOpen = () => setOpen(true);
    window.addEventListener(NOTICE_OPEN_EVENT, onOpen);
    return () => window.removeEventListener(NOTICE_OPEN_EVENT, onOpen);
  }, []);

  useEffect(() => {
    let alive = true;
    apiFetch<NoticePayload>("/notice")
      .then((n) => {
        if (!alive || !n?.version) return;
        setPayload(n);
        if (!isRead(Number(n.version))) setOpen(true);
      })
      .catch(() => {
        /* 拉取失败静默 */
      });
    return () => {
      alive = false;
    };
  }, []);

  const announcements = useMemo(() => resolveAnnouncements(payload), [payload]);
  const latest = announcements[0];
  const current: Announcement | undefined = announcements[selected] ?? latest;

  const close = useCallback(() => {
    if (latest) markRead(latest.version);
    setOpen(false);
  }, [latest]);

  // ESC 关闭：公告是模态，键盘用户不该只能找那个 ✕
  useEffect(() => {
    if (!open) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") close();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, close]);

  if (!open || !current) return null;

  return (
    <div className={styles.overlay} role="dialog" aria-modal="true" aria-label="公告">
      <div className={styles.card}>
        <button
          type="button"
          className={styles.closeBtn}
          onClick={close}
          aria-label="关闭公告"
          title="关闭"
        >
          ✕
        </button>

        <aside className={styles.rail} aria-label="公告列表">
          <p className={styles.railTitle}>公告</p>
          <nav className={styles.railList}>
            {announcements.map((a, i) => (
              <button
                key={a.version}
                type="button"
                className={i === selected ? `${styles.railItem} ${styles.railItemOn}` : styles.railItem}
                onClick={() => setSelected(i)}
                aria-current={i === selected}
                data-testid={`notice-item-${a.version}`}
              >
                <span className={styles.railItemBadge}>
                  {announcementBadge(a, i === 0 && !isRead(a.version))}
                </span>
                <span className={styles.railItemTitle}>{a.title}</span>
                <span className={styles.railItemDate}>{formatNoticeDate(a.updatedAt)}</span>
              </button>
            ))}
          </nav>
        </aside>

        <div className={styles.main}>
          <header className={styles.head}>
            <p className={styles.kicker}>公告 · 更新于 {formatNoticeDate(current.updatedAt)}</p>
            <h2>{current.title}</h2>
          </header>
          <div className={styles.body}>
            {current.sections.map((s, i) => (
              <section key={i} className={styles.sec}>
                <h3>{s.heading}</h3>
                <p>{s.body}</p>
              </section>
            ))}
          </div>
          <footer className={styles.foot}>
            {announcements.length > 1 ? (
              <span className={styles.hint}>
                左边可切换往期公告（共 {announcements.length} 版）
              </span>
            ) : (
              <span className={styles.hint} />
            )}
            <button type="button" className={styles.gotIt} onClick={close}>
              我知道了，开始使用 →
            </button>
          </footer>
        </div>
      </div>
    </div>
  );
}
