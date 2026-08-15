import type { ReactNode } from "react";
import { MascotFigure } from "./MascotFigure";
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

/** Persona empty board: mascot whisper only (no illustration). */
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
        <MascotFigure size={compact ? "md" : "lg"} mood="think" line={null} />
        <div className={styles.copy}>
          <p className={styles.title}>{title}</p>
          {line ? <p className={styles.whisper}>{line}</p> : null}
          {children}
        </div>
      </div>
    </div>
  );
}
