import { copyFor, type GenreCopy } from "../lib/genreCopy";
import { SpeechInputButton } from "./SpeechInputButton";
import styles from "./StudioApp.module.css";

export type WriteMode = "prose" | "rpy";

type Props = {
  /**
   * 用词表，由调用方按当前作品体裁注入。
   *
   * 可选 + 缺省 VN，理由：这个工具栏里"剧本 / RPY / 根据剧本生成"是同一个概念的
   * 三个叫法，必须整组一起换。调用方（StudioApp）还没接上时缺省走 VN 词，界面
   * 与改动前逐字一致，不会出现"按钮叫正文、提示还叫剧本"的半吊子状态。
   */
  copy?: GenreCopy;
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
  copy = copyFor("vn"),
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
          {copy.proseMode}
        </button>
        <button
          type="button"
          role="tab"
          aria-selected={writeMode === "rpy"}
          className={writeMode === "rpy" ? styles.modeOn : styles.modeOff}
          onClick={() => onWriteModeChange("rpy")}
        >
          {copy.scriptMode}
        </button>
      </div>
      {writeMode === "rpy" ? (
        <button
          type="button"
          className={styles.ghost}
          disabled={generating}
          onClick={onGenerateRpy}
          title={copy.generateScriptHint}
        >
          {generating ? "生成中…" : copy.generateScript}
        </button>
      ) : null}
      {rpyStale && writeMode === "rpy" ? (
        // 过期提示按体裁组词，而不是写死。中英之间那个空格是分开处理的：
        // VN 的 "RPY" 是拉丁字母，按排版习惯要和"可能过期"隔一个空格；
        // 小说的"脚本"本身是中文，再加空格会显得像错字。
        <span className={styles.hintInline}>
          {copy.genre === "novel"
            ? `${copy.proseMode}已改，${copy.scriptMode}可能过期`
            : `${copy.proseMode}已改，${copy.scriptMode} 可能过期`}
        </span>
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
        <span className={styles.hintInline}>{copy.proseHint}</span>
      ) : null}
    </div>
  );
}
