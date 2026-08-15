import type { ReactNode } from "react";
import styles from "./StudioApp.module.css";

type Props = {
  /** Stamp shown inside the boot arc, e.g. LOAD / LIB */
  stamp: string;
  /** Title under the kicker; rendered as <p> or <h1> to match each screen */
  title: string;
  titleTag?: "p" | "h1";
  /** Optional lead line (only the empty-library screen shows one) */
  lead?: string;
  /** Optional content inside the .bootEmpty wrapper (empty-library actions) */
  children?: ReactNode;
};

/**
 * Full-screen boot / empty states: loading, no projects, project loading.
 * Pure presentational shell — callbacks stay in StudioApp.
 */
export function StudioBootScreen({
  stamp,
  title,
  titleTag = "p",
  lead,
  children,
}: Props) {
  return (
    <div className={`vnss-app ${styles.boot}`}>
      <div className={styles.bootArc} aria-hidden>
        <span>{stamp}</span>
      </div>
      <p className={styles.bootKicker}>SCRIPT STUDIO</p>
      {titleTag === "h1" ? (
        <h1 className={styles.bootTitle}>{title}</h1>
      ) : (
        <p className={styles.bootTitle}>{title}</p>
      )}
      {lead ? <p className={styles.bootLead}>{lead}</p> : null}
      {children ? <div className={styles.bootEmpty}>{children}</div> : null}
    </div>
  );
}
