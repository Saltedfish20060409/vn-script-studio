import type { VoiceAxisTag } from "../api/client";
import styles from "./CharacterWorkshop.module.css";

type Props = {
  tags: VoiceAxisTag[];
  selectedIds: string[];
  onToggle: (id: string) => void;
  onClear: () => void;
};

export function VoiceAxisTagPanel({ tags, selectedIds, onToggle, onClear }: Props) {
  return (
    <div className={styles.tagPanel}>
      <div className={styles.tagPanelHead}>
        <span>方向标签（可选，最多 3）</span>
        {selectedIds.length > 0 && (
          <button
            type="button"
            className={styles.tagClear}
            onClick={onClear}
          >
            清空
          </button>
        )}
      </div>
      <div className={styles.tagCloud} role="group" aria-label="方向标签">
        {tags.map((t) => {
          const on = selectedIds.includes(t.id);
          return (
            <button
              key={t.id}
              type="button"
              className={on ? styles.tagOn : styles.tag}
              title={t.hint}
              aria-pressed={on}
              onClick={() => onToggle(t.id)}
            >
              {t.label}
            </button>
          );
        })}
      </div>
    </div>
  );
}
