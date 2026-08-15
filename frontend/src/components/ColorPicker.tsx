import styles from "./ColorPicker.module.css";

const PRESETS = [
  "#7eb8da",
  "#c4a574",
  "#d47b7b",
  "#6b9b7a",
  "#8b7bb8",
  "#d4a017",
  "#5c7a8a",
  "#2f5d50",
  "#b85c38",
  "#3d3832",
  "#6b7280",
  "#ffffff",
];

type Props = {
  value: string;
  onChange: (color: string) => void;
};

export function ColorPicker({ value, onChange }: Props) {
  const color = value || "#6b7280";
  const hexOk = /^#[0-9A-Fa-f]{6}$/.test(color);
  return (
    <div className={styles.wrap}>
      <div className={styles.row}>
        <label className={styles.preview} title="点击打开调色盘">
          <span className={styles.previewLabel}>当前色 · 点选</span>
          <span
            className={styles.previewFill}
            style={{ background: color }}
            aria-hidden
          />
          <input
            type="color"
            className={styles.native}
            value={hexOk ? color : "#6b7280"}
            onChange={(e) => onChange(e.target.value)}
            aria-label="打开调色盘"
          />
        </label>
        <label className={styles.hexField}>
          <span className={styles.hexLabel}>色号</span>
          <input
            className={styles.hex}
            value={color}
            onChange={(e) => onChange(e.target.value)}
            spellCheck={false}
            aria-label="色号"
            placeholder="#6b7280"
          />
        </label>
      </div>
      <div className={styles.presets} role="list" aria-label="常用色">
        {PRESETS.map((c) => {
          const on = color.toLowerCase() === c.toLowerCase();
          return (
            <button
              key={c}
              type="button"
              role="listitem"
              className={on ? styles.presetOn : styles.preset}
              style={{ background: c }}
              title={c}
              onClick={() => onChange(c)}
              aria-label={`选择颜色 ${c}`}
              aria-pressed={on}
            />
          );
        })}
      </div>
    </div>
  );
}
