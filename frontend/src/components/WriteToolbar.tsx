import styles from "./StudioApp.module.css";

type Props = {
  chapterTitle: string;
  /** Whether an uncommitted revise draft exists for this chapter */
  showReviseActions: boolean;
  onChapterTitleChange: (value: string) => void;
  onOpenRevise: () => void;
  onDiscardRevise: () => void;
};

/**
 * Script-editor toolbar: chapter title input plus either the revise-draft
 * actions or the location-hint line. Pure presentational — all actions are
 * prop callbacks provided by StudioApp.
 */
export function WriteToolbar({
  chapterTitle,
  showReviseActions,
  onChapterTitleChange,
  onOpenRevise,
  onDiscardRevise,
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
      {showReviseActions ? (
        <div className={styles.reviseDraftActions}>
          <button
            type="button"
            className={styles.reviseDraftBtn}
            title="打开未写入的改稿对照（刷新后仍可进入）"
            onClick={onOpenRevise}
          >
            改稿对照
          </button>
          <button
            type="button"
            className={styles.ghost}
            title="丢弃本章未写入的改稿预览"
            onClick={onDiscardRevise}
          >
            丢弃预览
          </button>
        </div>
      ) : (
        <span className={styles.hintInline}>
          地名会高亮，点击可跳到地图 · 续写用右下角 Agent
        </span>
      )}
    </div>
  );
}
