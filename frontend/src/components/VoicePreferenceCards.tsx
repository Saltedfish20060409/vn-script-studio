import type { VoiceVariant } from "../api/client";
import { VoiceVariantCards } from "./VoiceVariantCards";
import { VoiceWhyPanel, type PendingAccept } from "./VoiceWhyPanel";
import styles from "./CharacterWorkshop.module.css";

type Props = {
  variants: VoiceVariant[];
  busy: string;
  hasCharacter: boolean;
  unlikeOpen: boolean;
  unlikeAxis: string;
  unlikeCustomAxis: string;
  unlikeText: string;
  pendingAccept: PendingAccept | null;
  whyOpen: boolean;
  whyChips: string[];
  whyCustom: string;
  onGenerate: () => void;
  onAcceptVariant: (variant: VoiceVariant, index: number) => void;
  onUnlikeAxisSelect: (axis: string) => void;
  onUnlikeCustomAxisChange: (value: string) => void;
  onUnlikeTextChange: (value: string) => void;
  onAcceptUnlike: () => void;
  onDiscardUnlike: () => void;
  onToggleWhyChip: (chip: string) => void;
  onWhyCustomChange: (value: string) => void;
  onWhyConfirm: (note: string) => void;
  onWhySkip: () => void;
  onWhyCancel: () => void;
};

export function VoicePreferenceCards({
  variants,
  busy,
  hasCharacter,
  unlikeOpen,
  unlikeAxis,
  unlikeCustomAxis,
  unlikeText,
  pendingAccept,
  whyOpen,
  whyChips,
  whyCustom,
  onGenerate,
  onAcceptVariant,
  onUnlikeAxisSelect,
  onUnlikeCustomAxisChange,
  onUnlikeTextChange,
  onAcceptUnlike,
  onDiscardUnlike,
  onToggleWhyChip,
  onWhyCustomChange,
  onWhyConfirm,
  onWhySkip,
  onWhyCancel,
}: Props) {
  return (
    <div className={styles.cardStage}>
      {variants.length === 0 && !busy && (
        <div className={styles.emptyStage}>
          <p>定声音</p>
          <span>
            选场景 → 生成三组（动态轴）→ 选最像的入库。都不像可手写并记方向。
          </span>
          <button
            type="button"
            className={styles.primary}
            disabled={!!busy || !hasCharacter}
            onClick={onGenerate}
          >
            生成三组
          </button>
        </div>
      )}
      {busy === "generating" && (
        <div className={styles.busyBar} role="status" aria-live="polite">
          <span className={styles.busyStamp} aria-hidden>
            RUN
          </span>
          <span className={styles.busyPulse} aria-hidden />
          <span>生成进行中…按本轮三轴拉开差异</span>
        </div>
      )}
      <VoiceVariantCards
        variants={variants}
        busy={busy}
        handlePlaceholder
        onAccept={onAcceptVariant}
      />
      <VoiceWhyPanel
        open={whyOpen}
        pending={pendingAccept}
        chips={whyChips}
        custom={whyCustom}
        busy={busy}
        onToggleChip={onToggleWhyChip}
        onCustomChange={onWhyCustomChange}
        onConfirm={onWhyConfirm}
        onSkip={onWhySkip}
        onCancel={onWhyCancel}
      />
      {unlikeOpen && (
        <div className={styles.unlikeBox}>
          <p className={styles.manualHint}>
            都不像：手写更贴的对白，并确认本轮<strong>方向标签</strong>
            （可从本轮三轴选，或自填）。
          </p>
          <div className={styles.unlikeAxes}>
            {variants.map((v) => (
              <button
                key={v.axisId}
                type="button"
                className={
                  unlikeAxis === v.axisLabel && !unlikeCustomAxis.trim()
                    ? styles.tagOn
                    : styles.tag
                }
                onClick={() => onUnlikeAxisSelect(v.axisLabel || v.axisId)}
              >
                {v.axisLabel || v.axisId}
              </button>
            ))}
          </div>
          <label className={styles.field}>
            或自填方向
            <input
              value={unlikeCustomAxis}
              onChange={(e) => onUnlikeCustomAxisChange(e.target.value)}
              placeholder="例如：温柔劝说"
            />
          </label>
          <textarea
            rows={4}
            value={unlikeText}
            onChange={(e) => onUnlikeTextChange(e.target.value)}
            placeholder={"对方：……\n角色：……"}
          />
          <div className={styles.actions}>
            <button
              type="button"
              className={styles.primary}
              disabled={!!busy || !unlikeText.trim()}
              onClick={onAcceptUnlike}
            >
              {busy === "accept-unlike" ? "入库中…" : "手写入库"}
            </button>
            <button
              type="button"
              disabled={!!busy}
              onClick={onDiscardUnlike}
            >
              丢弃并重开
            </button>
          </div>
        </div>
      )}
    </div>
  );
}
