import { useEffect } from "react";
import { Link } from "react-router-dom";
import { HELP_DISCLAIMER, HELP_FAQ, HELP_QUICK } from "../lib/helpContent";
import styles from "./HelpSheet.module.css";

type Props = {
  open: boolean;
  onClose: () => void;
  /** 嵌进桌面窗口里用：不画遮罩/不抢 ESC（窗口自己有标题栏与关闭按钮） */
  embedded?: boolean;
};

export function HelpSheet({ open, onClose, embedded = false }: Props) {
  useEffect(() => {
    if (!open || embedded) return;
    const onKey = (e: KeyboardEvent) => {
      if (e.key === "Escape") onClose();
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [open, onClose, embedded]);

  if (!open) return null;
  const sheet = (
    <div className={embedded ? styles.sheetEmbedded : styles.sheet} onClick={(e) => e.stopPropagation()}>
      <div className={styles.body}>
        <p className={styles.idx}>HOW TO</p>
        <h2 id="help-sheet-title" className={styles.title}>
          使用说明
        </h2>
        <div className={styles.sections}>
          {HELP_QUICK.map((s) => (
            <section key={s.title}>
              <h3>{s.title}</h3>
              <p>{s.body}</p>
            </section>
          ))}
        </div>
        <div className={styles.faqList}>
          {HELP_FAQ.map((item) => (
            <details key={item.q}>
              <summary>{item.q}</summary>
              <p>{item.a}</p>
            </details>
          ))}
        </div>
        <p className={styles.disclaimer}>{HELP_DISCLAIMER}</p>
        <div className={styles.actions}>
          <Link
            to="/guide"
            target="_blank"
            rel="noreferrer"
            className={styles.link}
          >
            打开完整使用指南
          </Link>
          {!embedded ? (
            <button type="button" className={styles.primary} onClick={onClose}>
              知道了
            </button>
          ) : null}
        </div>
      </div>
    </div>
  );
  if (embedded) return sheet;
  return (
    <div
      className={styles.backdrop}
      role="dialog"
      aria-modal="true"
      aria-labelledby="help-sheet-title"
      onClick={onClose}
    >
      {sheet}
    </div>
  );
}
