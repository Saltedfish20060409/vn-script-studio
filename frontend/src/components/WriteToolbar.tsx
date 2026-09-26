import { useState } from "react";
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
  const [hintOpen, setHintOpen] = useState(false);

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
        /* 格式说明收成「？」：悬停看 title；点击/触屏展开一行（再点收起），
           平时工具条仍只占一行。 */
        <>
          <button
            type="button"
            className={styles.ghost}
            data-testid="write-mode-hint"
            title={copy.proseHint}
            aria-label={`写作格式说明：${copy.proseHint}`}
            aria-expanded={hintOpen}
            onClick={() => setHintOpen((open) => !open)}
          >
            ？
          </button>
          {hintOpen ? (
            <span className={styles.hintInline} role="status" data-testid="write-mode-hint-body">
              {copy.proseHint}
            </span>
          ) : null}
        </>
      ) : null}
    </div>
  );
}
