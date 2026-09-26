import { copyFor, type GenreCopy } from "../lib/genreCopy";
import { SpeechInputButton } from "./SpeechInputButton";
import styles from "./StudioApp.module.css";

export type WriteMode = "prose" | "rpy";

type Props = {
  copy?: GenreCopy;
  writeMode?: WriteMode;
  rpyStale?: boolean;
  generating?: boolean;
  showReviseActions?: boolean;
  onWriteModeChange?: (mode: WriteMode) => void;
  onGenerateRpy?: () => void;
  onOpenRevise?: () => void;
  onDiscardRevise?: () => void;
  onDictateInsert?: (text: string) => void;
  onFind?: () => void;
};

/**
 * 稿纸旁工具条：
 * - VN：剧本/RPY、生成、查找、语音、改稿（脚本工作台高频）
 * - 小说：只留语音（格式进「开始」菜单，少占正文）
 */
export function WriteToolbar({
  copy = copyFor("vn"),
  writeMode = "prose",
  rpyStale,
  generating,
  showReviseActions,
  onWriteModeChange,
  onGenerateRpy,
  onOpenRevise,
  onDiscardRevise,
  onDictateInsert,
  onFind,
}: Props) {
  const isVn = copy.genre === "vn";

  if (!isVn) {
    if (!onDictateInsert) return null;
    return (
      <div className={styles.toolbar} data-testid="write-toolbar-slim">
        <SpeechInputButton onInsert={onDictateInsert} />
        <span className={styles.hintInline}>
          格式切换、查找、改稿在顶栏「开始 / 审阅」
        </span>
      </div>
    );
  }

  return (
    <div className={styles.toolbar} data-testid="write-toolbar-vn">
      {onWriteModeChange ? (
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
      ) : null}
      {writeMode === "rpy" && onGenerateRpy ? (
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
        <span className={styles.hintInline}>
          {copy.proseMode}已改，{copy.scriptMode} 可能过期
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
      {showReviseActions && onOpenRevise && onDiscardRevise ? (
        <div className={styles.reviseDraftActions}>
          <button
            type="button"
            className={styles.reviseDraftBtn}
            title="打开未写入的改稿对照"
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
            放弃改稿
          </button>
        </div>
      ) : writeMode === "prose" ? (
        /* 格式说明（"默认写普通剧本文字…"）原来平铺在这里，是一整句话：
           窄一点的窗口就会换行，把工具条撑成两行、正文跟着往下挪。
           收成「？」按钮：鼠标悬停能看到全文，读屏用户拿 aria-label 也能听到，
           而工具条永远只有一行。 */
        <button
          type="button"
          className={styles.ghost}
          data-testid="write-mode-hint"
          title={copy.proseHint}
          aria-label={`写作格式说明：${copy.proseHint}`}
        >
          ？
        </button>
      ) : null}
    </div>
  );
}
