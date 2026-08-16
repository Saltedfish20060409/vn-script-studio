import { createPortal } from "react-dom";
import styles from "./ChapterReviseModePicker.module.css";
import { REVISE_MODE_OPTIONS, type ReviseMode } from "../lib/chapterRevisePrefs";

type Props = {
  defaultMode?: ReviseMode;
  busy?: boolean;
  onPick: (mode: ReviseMode) => void;
  onCancel: () => void;
};

export function ChapterReviseModePicker({
  defaultMode = "human_warmth",
  busy = false,
  onPick,
  onCancel,
}: Props) {
  return createPortal(
    <div className={styles.backdrop} role="presentation" onClick={onCancel}>
      <div
        className={styles.dialog}
        role="dialog"
        aria-modal
        aria-labelledby="revise-mode-title"
        onClick={(e) => e.stopPropagation()}
      >
        <p className={styles.stamp}>REVISE · MODE</p>
        <h2 id="revise-mode-title">这次想怎么改？</h2>
        <p className={styles.sub}>
          选一个方向即可，之后还能用平常话说「再润」「别动某某」微调。
        </p>
        <div className={styles.grid}>
          {REVISE_MODE_OPTIONS.map((opt) => (
            <button
              key={opt.id}
              type="button"
              className={styles.card}
              data-default={opt.id === defaultMode ? "1" : undefined}
              disabled={busy}
              onClick={() => onPick(opt.id)}
            >
              <span className={styles.title}>{opt.title}</span>
              <span className={styles.blurb}>{opt.blurb}</span>
            </button>
          ))}
        </div>
        <button
          type="button"
          className={styles.cancel}
          onClick={onCancel}
          disabled={busy}
        >
          取消
        </button>
      </div>
    </div>,
    document.body
  );
}
