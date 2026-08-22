import type { ReactNode } from "react";
import styles from "./EmptyStage.module.css";

type Props = {
  title: string;
  line?: string;
  /** Short stamp, e.g. MAP */
  stamp?: string;
  children?: ReactNode;
  className?: string;
  compact?: boolean;
};

/** Empty board: stamp + copy (no mascot illustration). */
export function EmptyStage({
  title,
  line,
  stamp,
  children,
  className,
  compact,
}: Props) {
  return (
    <div
      className={`${styles.stage} ${compact ? styles.compact : ""} ${className ?? ""}`}
      role="status"
    >
      {stamp ? (
        <span className={styles.stamp} aria-hidden>
          {stamp}
        </span>
      ) : null}
      <div className={styles.body}>
        <div className={styles.copy}>
          <p className={styles.title}>{title}</p>
          {line ? <p className={styles.whisper}>{line}</p> : null}
          {children}
        </div>
      </div>
    </div>
  );
}
