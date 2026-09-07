import type { VoiceVariant } from "../api/client";
import styles from "./CharacterWorkshop.module.css";

const WHY_CHIPS = [
  "更克制",
  "关系距离对",
  "用词更像",
  "节奏对",
  "情绪对",
  "思维方式对",
] as const;

export type PendingAccept = {
  variant: VoiceVariant;
  index: number;
  source: "preference" | "interview";
};

type Props = {
  open: boolean;
  pending: PendingAccept | null;
  chips: string[];
  custom: string;
  busy: string;
  onToggleChip: (chip: string) => void;
  onCustomChange: (value: string) => void;
  onConfirm: (note: string) => void;
  onSkip: () => void;
  onCancel: () => void;
};

export function VoiceWhyPanel({
  open,
  pending,
  chips,
  custom,
  busy,
  onToggleChip,
  onCustomChange,
  onConfirm,
  onSkip,
  onCancel,
}: Props) {
  if (!open || !pending) return null;
  const label = pending.variant.axisLabel || pending.variant.axisId || "这组";
  return (
    <div className={styles.whyBox}>
      <p className={styles.manualHint}>
        为什么这一组更像「{label}」？（可选）点几个词或补一句理由，能帮 AI 更懂你想要的方向；不填也能直接保存。
      </p>
      <div className={styles.tagCloud} role="group" aria-label="为何更像">
        {WHY_CHIPS.map((chip) => {
          const on = chips.includes(chip);
          return (
            <button
              key={chip}
              type="button"
              className={on ? styles.tagOn : styles.tag}
              aria-pressed={on}
              onClick={() => onToggleChip(chip)}
            >
              {chip}
            </button>
          );
        })}
      </div>
      <label className={styles.field}>
        补充一句
        <input
          value={custom}
          onChange={(e) => onCustomChange(e.target.value)}
          placeholder="例如：少卖萌，更像她对后辈的距离"
        />
      </label>
      <div className={styles.actions}>
        <button
          type="button"
          className={styles.primary}
          disabled={!!busy}
          onClick={() =>
            onConfirm([...chips, custom.trim()].filter(Boolean).join("；"))
          }
        >
          {busy.startsWith("accept-") ? "保存中…" : "确认存为示例"}
        </button>
        <button type="button" disabled={!!busy} onClick={onSkip}>
          不填理由，直接保存
        </button>
        <button type="button" disabled={!!busy} onClick={onCancel}>
          取消
        </button>
      </div>
    </div>
  );
}
