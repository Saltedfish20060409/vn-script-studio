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
  /** 打开查找替换。键盘 Ctrl+F 也走同一个入口——但**必须有个看得见的按钮**：
   *  只留快捷键等于没做（作者不会去猜有什么快捷键）。 */
  onFind?: () => void;
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
  onFind,
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
      {onFind ? (
        <button
          type="button"
          className={styles.ghost}
          data-testid="open-find"
          title="查找 / 替换（快捷键 Ctrl+F，Mac 为 ⌘F）"
          onClick={onFind}
        >
          查找 / 替换
        </button>
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
