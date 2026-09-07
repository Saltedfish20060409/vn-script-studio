import type { VoiceVariant } from "../api/client";
import { VoiceVariantCards } from "./VoiceVariantCards";
import { VoiceWhyPanel, type PendingAccept } from "./VoiceWhyPanel";
import styles from "./CharacterWorkshop.module.css";

type Props = {
  question: string;
  genQuestion: string | undefined;
  variants: VoiceVariant[];
  busy: string;
  hasCharacter: boolean;
  interviewManual: string;
  pendingAccept: PendingAccept | null;
  whyOpen: boolean;
  whyChips: string[];
  whyCustom: string;
  onGenerate: () => void;
  onAcceptVariant: (variant: VoiceVariant, index: number) => void;
  onManualChange: (value: string) => void;
  onAcceptManual: () => void;
  onToggleWhyChip: (chip: string) => void;
  onWhyCustomChange: (value: string) => void;
  onWhyConfirm: (note: string) => void;
  onWhySkip: () => void;
  onWhyCancel: () => void;
};

export function VoiceInterviewPanel({
  question,
  genQuestion,
  variants,
  busy,
  hasCharacter,
  interviewManual,
  pendingAccept,
  whyOpen,
  whyChips,
  whyCustom,
  onGenerate,
  onAcceptVariant,
  onManualChange,
  onAcceptManual,
  onToggleWhyChip,
  onWhyCustomChange,
  onWhyConfirm,
  onWhySkip,
  onWhyCancel,
}: Props) {
  return (
    <>
      {(question || genQuestion) && (
        <p className={styles.interviewQ}>{question || genQuestion}</p>
      )}
      <div className={styles.cardStage}>
        {variants.length === 0 && !busy && (
          <div className={styles.emptyStage}>
            <p>扮演采访</p>
            <span>给角色出一道难回答的题（如被误会、被当众质问），AI 会生成三种不同风格的回答；挑最接近他平时说话方式的一种，存成示例（只作参考，不会写进正文）。</span>
            <button
              type="button"
              className={styles.primary}
              disabled={!!busy || !hasCharacter}
              onClick={onGenerate}
            >
              生成三组回答
            </button>
          </div>
        )}
        {busy === "generating" && (
          <div className={styles.busyBar} role="status" aria-live="polite">
            <span className={styles.busyStamp} aria-hidden>
              RUN
            </span>
            <span className={styles.busyPulse} aria-hidden />
            <span>生成进行中…角色正在组织回答</span>
          </div>
        )}
        <VoiceVariantCards variants={variants} busy={busy} onAccept={onAcceptVariant} />
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
      </div>
      <div className={styles.manualBox}>
        <p className={styles.manualHint}>或手写回答（一行或多行），存成这个角色的示例</p>
        <textarea
          rows={4}
          value={interviewManual}
          onChange={(e) => onManualChange(e.target.value)}
          placeholder="直接写角色会怎么答…"
        />
        <button
          type="button"
          className={styles.primary}
          disabled={!!busy || !interviewManual.trim()}
          onClick={onAcceptManual}
        >
          {busy === "accept-interview" ? "保存中…" : "存为示例"}
        </button>
      </div>
    </>
  );
}
