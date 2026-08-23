import { useCallback, useEffect, useState } from "react";
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
 * 公告弹窗：居中卡片 + 黑色半透明遮罩（模态）。
 * 未读版本自动弹出一次；登录页右上角「公告」按钮可随时复看。
 */
export function NoticeBanner({ forceOpen, onClose }: { forceOpen?: boolean; onClose?: () => void }) {
  const [notice, setNotice] = useState<Notice | null>(null);
  const [open, setOpen] = useState(false);

  useEffect(() => {
    let alive = true;
    apiFetch<Notice>("/notice")
      .then((n) => {
        if (!alive || !n?.version) return;
        setNotice(n);
        if (forceOpen || !isRead(n.version)) setOpen(true);
      })
      .catch(() => {
        /* 拉取失败静默 */
      });
    return () => {
      alive = false;
    };
  }, [forceOpen]);

  const close = useCallback(() => {
    if (notice) markRead(notice.version);
    setOpen(false);
    onClose?.();
  }, [notice, onClose]);

  if (!open || !notice) return null;

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
