import { useCallback, useEffect, useState } from "react";
import { useLocation } from "react-router-dom";
import { apiFetch } from "../api/http";
import styles from "./NoticeBanner.module.css";

interface NoticeSection {
  heading: string;
  body: string;
}

interface Notice {
  version: number;
  title: string;
  updatedAt: string;
  sections: NoticeSection[];
}

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
 * 公告横幅：登录页自动弹出（新用户可见欢迎+起步指导），
 * 登录后不再全屏打扰（避免挡住编辑器操作）；后续更新公告只需 bump version。
 */
export function NoticeBanner() {
  const location = useLocation();
  const [notice, setNotice] = useState<Notice | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let alive = true;
    apiFetch<Notice>("/notice")
      .then((n) => {
        if (!alive || !n?.version) return;
        setNotice(n);
        if (!isRead(n.version)) setOpen(true);
      })
      .catch(() => {
        /* 拉取失败静默：不打扰使用 */
      });
    return () => {
      alive = false;
    };
  }, []);

  const close = useCallback(() => {
    if (notice) markRead(notice.version);
    setOpen(false);
  }, [notice]);

  // 只在登录页弹出：登录后的工作区不被全屏公告遮挡
  const isLogin = location.pathname === "/login";
  if (!isLogin || !open || !notice) return null;

  return (
    <div className={styles.overlay} role="dialog" aria-modal="true" aria-label={notice.title}>
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
        <p className={styles.kicker}>公告 · 更新于 {notice.updatedAt}</p>
        <h2>{notice.title}</h2>
        <div className={styles.body}>
          {notice.sections.map((s, i) => (
            <section key={i} className={styles.sec}>
              <h3>{s.heading}</h3>
              <p>{s.body}</p>
            </section>
          ))}
        </div>
        <button type="button" className={styles.gotIt} onClick={close}>
          我知道了，开始使用 →
        </button>
      </div>
    </div>
  );
}
