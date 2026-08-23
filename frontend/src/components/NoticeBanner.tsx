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
 * 公告横幅：登录页顶部滑入（非模态，不拦截表单点击）。
 * 未读版本才显示；关闭后本版本不再出现。后续更新公告只需 bump version。
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

  // 只在登录页显示；非模态横幅不遮挡表单
  const isLogin = location.pathname === "/login";
  if (!isLogin || !open || !notice) return null;

  return (
    <div className={styles.banner} role="region" aria-label={notice.title}>
      <div className={styles.content}>
        <p className={styles.kicker}>公告 · {notice.updatedAt}</p>
        <h2>{notice.title}</h2>
        <div className={styles.body}>
          {notice.sections.map((s, i) => (
            <section key={i} className={styles.sec}>
              <h3>{s.heading}</h3>
              <p>{s.body}</p>
            </section>
          ))}
        </div>
      </div>
      <button
        type="button"
        className={styles.closeBtn}
        onClick={close}
        aria-label="关闭公告"
        title="关闭"
      >
        ✕
      </button>
    </div>
  );
}
