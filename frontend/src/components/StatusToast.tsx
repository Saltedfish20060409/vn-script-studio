import { useEffect } from "react";
import styles from "./StatusToast.module.css";

export type StatusToastKind = "ok" | "error" | "busy" | "info";

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
      {kind === "busy" ? (
        <span className={styles.busyPulse} aria-hidden />
      ) : null}
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

/** Classify studio status strings into toast kinds. */
export function classifyStatusToast(
  status: string,
  error: string
): { message: string; kind: StatusToastKind } | null {
  if (error) return { message: error, kind: "error" };
  const msg = status.trim();
  if (!msg) return null;
  if (
    /中…|中\.\.\.|进行中|保存中|生成中|提取中|检查中|合成中|归档|写入语料|入库中/.test(
      msg
    )
  ) {
    return { message: msg, kind: "busy" };
  }
  if (/已|成功|同步|下载|复制|加入|创建|重命名|回退|撤销/.test(msg)) {
    return { message: msg, kind: "ok" };
  }
  return { message: msg, kind: "info" };
}
