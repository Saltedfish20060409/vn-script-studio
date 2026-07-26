"use client";

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
  return (
    <div className={styles.wrap}>
      <div className={styles.row}>
        <input
          type="color"
          className={styles.native}
          value={/^#[0-9A-Fa-f]{6}$/.test(color) ? color : "#6b7280"}
          onChange={(e) => onChange(e.target.value)}
          aria-label="打开调色盘"
          title="打开系统调色盘"
        />
        <input
          className={styles.hex}
          value={color}
          onChange={(e) => onChange(e.target.value)}
          spellCheck={false}
          aria-label="色号"
        />
        <span
          className={styles.swatch}
          style={{ background: color }}
          aria-hidden
        />
      </div>
      <div className={styles.presets}>
        {PRESETS.map((c) => (
          <button
            key={c}
            type="button"
            className={styles.preset}
            style={{ background: c }}
            title={c}
            onClick={() => onChange(c)}
            aria-label={`选择颜色 ${c}`}
          />
        ))}
      </div>
    </div>
  );
}
