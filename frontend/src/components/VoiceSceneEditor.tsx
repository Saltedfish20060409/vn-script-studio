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
          <p className={styles.muted}>这段是草稿，不会自动写进正文。先改好台词、确认无误后，再点「存为示例」。</p>
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
              {busy === "accept-scene" ? "保存中…" : "存为示例"}
            </button>
            <button type="button" disabled={!!busy} onClick={onRegenerate}>
              重新生成
            </button>
          </div>
        </>
      ) : (
        <div className={styles.emptyStage}>
          <p>长场次加厚</p>
          <span>让 AI 写一整场（约 8～12 轮对白）再存成示例，用来给角色积累更完整的长对话口吻。无结果时看底部错误提示。</span>
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
