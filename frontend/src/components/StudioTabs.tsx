import type { StudioTab } from "../lib/workspacePersist";
import styles from "./StudioApp.module.css";

const TABS: ReadonlyArray<readonly [StudioTab, string, string, string]> = [
  ["write", "01", "写作", "写作"],
  ["world", "02", "设定", "设定"],
  ["voice", "03", "角色工坊", "工坊"],
  ["map", "04", "地图", "地图"],
  ["system", "05", "剧情状态", "状态"],
  ["project", "06", "项目", "项目"],
];

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
      {TABS.map(([id, idx, label, short]) => (
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
