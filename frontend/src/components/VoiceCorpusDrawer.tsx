import type { VoiceCorpusSample } from "../types/vn";
import styles from "./CharacterWorkshop.module.css";

export type ExtractRow = {
  preview: string;
  scenarioLabel: string;
  selected: boolean;
};

type Props = {
  open: boolean;
  sampleCount: number;
  busy: string;
  corpus: VoiceCorpusSample[];
  extractRows: ExtractRow[];
  onToggle: () => void;
  onExtract: () => void;
  onDelete: (id: string) => void;
  onToggleRow: (index: number, checked: boolean) => void;
  onAcceptExtract: () => void;
};

export function VoiceCorpusDrawer({
  open,
  sampleCount,
  busy,
  corpus,
  extractRows,
  onToggle,
  onExtract,
  onDelete,
  onToggleRow,
  onAcceptExtract,
}: Props) {
  return (
    <div className={styles.drawer}>
      <div className={styles.drawerTabs}>
        <button
          type="button"
          className={open ? styles.drawerTabOn : styles.drawerTab}
          onClick={onToggle}
        >
          语料库 ({sampleCount}) · 抽取工具
        </button>
      </div>
      {open && (
        <div className={styles.drawerBody}>
          <div className={styles.actions}>
            <button type="button" disabled={!!busy} onClick={onExtract}>
              从剧本抽取
            </button>
          </div>
          {corpus.length === 0 ? (
            <p className={styles.muted}>尚未入库。塑形后正例会出现在这里。</p>
          ) : (
            <ul className={styles.corpusList}>
              {corpus.map((s) => (
                <li key={s.id}>
                  <div>
                    <strong>{s.scenarioLabel || s.scenario}</strong>
                    {s.source ? ` · ${s.source}` : ""}
                    {s.axis ? ` · ${s.axis}` : ""}
                    <div className={styles.mini}>
                      {(s.lines || [])
                        .map((l) => l.text)
                        .filter(Boolean)
                        .join(" / ")}
                    </div>
                  </div>
                  <button
                    type="button"
                    className={styles.danger}
                    disabled={!!busy}
                    onClick={() => onDelete(s.id)}
                  >
                    删
                  </button>
                </li>
              ))}
            </ul>
          )}
          {extractRows.length > 0 && (
            <div className={styles.extract}>
              <ul>
                {extractRows.map((r, i) => (
                  <li key={i}>
                    <label>
                      <input
                        type="checkbox"
                        checked={r.selected}
                        onChange={(e) => onToggleRow(i, e.target.checked)}
                      />
                      <span>
                        [{r.scenarioLabel}] {r.preview}
                      </span>
                    </label>
                  </li>
                ))}
              </ul>
              <button
                type="button"
                className={styles.primary}
                disabled={!!busy}
                onClick={onAcceptExtract}
              >
                加入所选
              </button>
            </div>
          )}
        </div>
      )}
    </div>
  );
}
