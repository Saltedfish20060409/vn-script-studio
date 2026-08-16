import { useEffect } from "react";
import type { StatusToastKind } from "../lib/statusToast";
import styles from "./StatusToast.module.css";

type Props = {
  message: string;
  kind: StatusToastKind;
  quiet?: boolean;
  onDismiss: () => void;
};

const KIND_STAMP: Record<StatusToastKind, string> = {
  ok: "OK",
  error: "ERR",
  busy: "RUN",
  info: "INF",
};

/** Corner Persona toast — beveled hard edge, no history queue. */
export function StatusToast({ message, kind, quiet, onDismiss }: Props) {
  useEffect(() => {
    if (kind === "busy" || kind === "error") return;
    const t = window.setTimeout(onDismiss, 3800);
    return () => window.clearTimeout(t);
  }, [kind, message, onDismiss]);

  return (
    <div
      className={`${styles.toast} ${styles[kind]} ${quiet ? styles.quiet : ""}`}
      role={kind === "error" ? "alert" : "status"}
      aria-live={kind === "error" ? "assertive" : "polite"}
    >
      <span className={styles.stamp} aria-hidden>
        {KIND_STAMP[kind]}
      </span>
      {kind === "busy" ? <span className={styles.busyPulse} aria-hidden /> : null}
      <p className={styles.msg}>{message}</p>
      <button
        type="button"
        className={styles.close}
        onClick={onDismiss}
        aria-label="关闭提示"
      >
        ×
      </button>
    </div>
  );
}

