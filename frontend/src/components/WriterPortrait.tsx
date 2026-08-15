import { useState } from "react";
import {
  writerPortraitAccent,
  writerPortraitUrl,
} from "../lib/writerPortraits";
import styles from "./WriterPortrait.module.css";

type Size = "xs" | "sm" | "md" | "lg";

type Props = {
  /** null = default LN/VN editor */
  lensId?: string | null;
  size?: Size;
  className?: string;
  selected?: boolean;
};

export function WriterPortrait({
  lensId = null,
  size = "md",
  className = "",
  selected = false,
}: Props) {
  const [failed, setFailed] = useState(false);
  const src = writerPortraitUrl(lensId);
  const accent = writerPortraitAccent(lensId);

  return (
    <div
      className={`${styles.wrap} ${styles[size]} ${selected ? styles.on : ""} ${className}`}
      style={{ ["--writer-accent" as string]: accent }}
      aria-hidden
    >
      {failed ? (
        <div className={styles.fallback} />
      ) : (
        <img
          className={styles.img}
          src={src}
          alt=""
          draggable={false}
          onError={() => setFailed(true)}
        />
      )}
    </div>
  );
}
