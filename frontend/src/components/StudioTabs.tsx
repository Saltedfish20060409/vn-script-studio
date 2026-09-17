import { STUDIO_TABS } from "../lib/studioTabs";
import type { StudioTab } from "../lib/workspacePersist";
import styles from "./StudioApp.module.css";

type Props = {
  tab: StudioTab;
  onSelect: (id: StudioTab) => void;
};

/**
 * Top-level tab rail. Pure presentational — the commit-before-switch
 * logic lives in the onSelect callback provided by StudioApp.
 */
export function StudioTabs({ tab, onSelect }: Props) {
  return (
    <nav className={`${styles.tabs} vnss-frost`} aria-label="剧本篇章">
      <span className={styles.tabsRail} aria-hidden />
      {STUDIO_TABS.map(([id, idx, label, short]) => (
        <button
          key={id}
          type="button"
          className={tab === id ? styles.tabActive : styles.tab}
          onClick={() => onSelect(id)}
        >
          <span className={styles.tabIdx} aria-hidden>
            {idx}
          </span>
          <span className={styles.tabLabelWide}>{label}</span>
          <span className={styles.tabLabelNarrow}>{short}</span>
        </button>
      ))}
    </nav>
  );
}
