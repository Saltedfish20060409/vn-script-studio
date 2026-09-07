import type { VoiceVariant } from "../api/client";
import styles from "./CharacterWorkshop.module.css";

const AXIS_LETTERS = ["A", "B", "C"];

function linesBlock(lines: Array<{ speaker: string; text: string }>) {
  return lines.map((ln, i) => (
    <p key={i} className={styles.line}>
      <span className={styles.speaker}>
        {ln.speaker === "self" ? "角色" : ln.speaker === "other" ? "对方" : ln.speaker}
      </span>
      <span className={styles.lineText}>{ln.text}</span>
    </p>
  ));
}

type Props = {
  variants: VoiceVariant[];
  busy: string;
  /**
   * Preference mode treats placeholder variants as unusable (button disabled,
   * "不可入库" label); interview mode renders lines directly.
   */
  handlePlaceholder?: boolean;
  onAccept: (variant: VoiceVariant, index: number) => void;
};

export function VoiceVariantCards({
  variants,
  busy,
  handlePlaceholder = false,
  onAccept,
}: Props) {
  if (variants.length === 0) return null;
  return (
    <div className={styles.variantGrid}>
      {variants.map((v, i) => (
        <article key={v.axisId + i} className={styles.variantCard}>
          <div className={styles.cardLetter}>{AXIS_LETTERS[i] || i + 1}</div>
          <header className={styles.cardHead}>
            <h3>{v.axisLabel || v.axisId}</h3>
            <p>{v.hypothesis}</p>
          </header>
          <div className={styles.cardBody}>
            {handlePlaceholder && v.placeholder ? (
              <p className={styles.placeholderHint}>模型未生成完整，请重新生成本组</p>
            ) : (
              linesBlock(v.lines)
            )}
          </div>
          <footer className={styles.cardFoot}>
            <button
              type="button"
              className={styles.primary}
              disabled={!!busy || (handlePlaceholder && !!v.placeholder)}
              onClick={() => onAccept(v, i)}
            >
              {busy === `accept-${i}`
                ? "保存中…"
                : handlePlaceholder && v.placeholder
                  ? "无法保存"
                  : "选这组存为示例"}
            </button>
          </footer>
        </article>
      ))}
    </div>
  );
}
