import styles from "./CharacterWorkshop.module.css";

type Props = {
  busy: string;
  sceneText: string;
  hasCharacter: boolean;
  onTextChange: (value: string) => void;
  onAccept: () => void;
  onRegenerate: () => void;
  onGenerate: () => void;
};

export function VoiceSceneEditor({
  busy,
  sceneText,
  hasCharacter,
  onTextChange,
  onAccept,
  onRegenerate,
  onGenerate,
}: Props) {
  return (
    <div className={styles.sceneEditor}>
      {busy === "generating" ? (
        <div className={styles.busyBar} role="status" aria-live="polite">
          <span className={styles.busyStamp} aria-hidden>
            RUN
          </span>
          <span className={styles.busyPulse} aria-hidden />
          <span>生成进行中…长场次约需数十秒</span>
        </div>
      ) : sceneText.trim() ? (
        <>
          <p className={styles.muted}>生成后可编辑台词，确认无误后整段入库。</p>
          <textarea
            value={sceneText}
            onChange={(e) => onTextChange(e.target.value)}
            placeholder="角色：第一句&#10;对方：回应&#10;…"
          />
          <div className={styles.actions}>
            <button
              type="button"
              className={styles.primary}
              disabled={!!busy || !sceneText.trim()}
              onClick={onAccept}
            >
              {busy === "accept-scene" ? "入库中…" : "整段入库"}
            </button>
            <button type="button" disabled={!!busy} onClick={onRegenerate}>
              重新生成
            </button>
          </div>
        </>
      ) : (
        <div className={styles.emptyStage}>
          <p>长场次加厚</p>
          <span>一次约 8～12 轮，整段入库。无结果时看底部错误提示。</span>
          <button
            type="button"
            className={styles.primary}
            disabled={!!busy || !hasCharacter}
            onClick={onGenerate}
          >
            生成长场次
          </button>
        </div>
      )}
    </div>
  );
}
