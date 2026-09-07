import { SpeechInputButton } from "./SpeechInputButton";
import styles from "./StudioApp.module.css";

export type WriteMode = "prose" | "rpy";

type Props = {
  chapterTitle: string;
  writeMode: WriteMode;
  rpyStale?: boolean;
  generating?: boolean;
  showReviseActions: boolean;
  onWriteModeChange: (mode: WriteMode) => void;
  onGenerateRpy: () => void;
  onChapterTitleChange: (value: string) => void;
  onOpenRevise: () => void;
  onDiscardRevise: () => void;
  onDictateInsert?: (text: string) => void;
};

export function WriteToolbar({
  chapterTitle,
  writeMode,
  rpyStale,
  generating,
  showReviseActions,
  onWriteModeChange,
  onGenerateRpy,
  onChapterTitleChange,
  onOpenRevise,
  onDiscardRevise,
  onDictateInsert,
}: Props) {
  return (
    <div className={styles.toolbar}>
      <label className={styles.inlineLabel}>
        章节名
        <input
          value={chapterTitle}
          onChange={(e) => onChapterTitleChange(e.target.value)}
        />
      </label>
      <div className={styles.modeSwitch} role="tablist" aria-label="写作格式">
        <button
          type="button"
          role="tab"
          aria-selected={writeMode === "prose"}
          className={writeMode === "prose" ? styles.modeOn : styles.modeOff}
          onClick={() => onWriteModeChange("prose")}
        >
          剧本
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={writeMode === "rpy"}
          className={writeMode === "rpy" ? styles.modeOn : styles.modeOff}
          onClick={() => onWriteModeChange("rpy")}
        >
          RPY
        </button>
      </div>
      {writeMode === "rpy" ? (
        <button
          type="button"
          className={styles.ghost}
          disabled={generating}
          onClick={onGenerateRpy}
          title="根据自然语言剧本生成 Ren'Py 脚本"
        >
          {generating ? "生成中…" : "根据剧本生成"}
        </button>
      ) : null}
      {rpyStale && writeMode === "rpy" ? (
        <span className={styles.hintInline}>剧本已改，RPY 可能过期</span>
      ) : null}
      {onDictateInsert ? <SpeechInputButton onInsert={onDictateInsert} /> : null}
      {showReviseActions ? (
        <div className={styles.reviseDraftActions}>
          <button
            type="button"
            className={styles.reviseDraftBtn}
            title="打开未写入的改稿对照（刷新后仍可进入）"
            onClick={onOpenRevise}
          >
            查看改稿对比
          </button>
          <button
            type="button"
            className={styles.ghost}
            title="放弃这次改稿预览，正文保持原样"
            onClick={onDiscardRevise}
          >
            放弃改稿（正文不动）
          </button>
        </div>
      ) : writeMode === "prose" ? (
        <span className={styles.hintInline}>
          默认写普通剧本文字（对白写成「角色名：台词」）；想做成可试玩的游戏时，再切到 RPY 自动转换
        </span>
      ) : null}
    </div>
  );
}
