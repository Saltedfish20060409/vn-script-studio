import type { ChangeEvent, RefObject } from "react";
import styles from "./StudioApp.module.css";

type Props = {
  title: string;
  username?: string;
  /** Show the 专注 button only inside the script editor outside focus mode */
  showFocusToggle: boolean;
  /** Hidden file input lives here; the ref is owned by StudioApp */
  fileInputRef: RefObject<HTMLInputElement | null>;
  onTitleChange: (value: string) => void;
  onFocusToggle: () => void;
  onNewProject: () => void;
  onImportClick: () => void;
  onFileChange: (e: ChangeEvent<HTMLInputElement>) => void;
  onSaveChapter: () => void;
  onExportRpy: () => void;
  onLogout: () => void;
};

/**
 * Top application bar: brand + editable title, focus toggle, 更多 menu,
 * hidden import input, export button, user chip, logout.
 * Pure presentational — every action is a prop callback.
 */
export function StudioTopBar({
  title,
  username,
  showFocusToggle,
  fileInputRef,
  onTitleChange,
  onFocusToggle,
  onNewProject,
  onImportClick,
  onFileChange,
  onSaveChapter,
  onExportRpy,
  onLogout,
}: Props) {
  return (
    <header className={`${styles.top} vnss-frost`}>
      <div className={styles.brandBlock}>
        <span className={styles.brandMark} aria-hidden>
          <em>SS</em>
          <span>VN</span>
        </span>
        <div className={styles.brandText}>
          <p className={styles.brandKicker}>VISUAL NOVEL</p>
          <p className={styles.brand}>Script Studio</p>
          <input
            className={styles.titleInput}
            value={title}
            onChange={(e) => onTitleChange(e.target.value)}
            aria-label="作品标题"
            placeholder="作品标题"
          />
        </div>
      </div>
      <div className={styles.topActions}>
        {showFocusToggle ? (
          <button
            type="button"
            className={styles.focusToggle}
            aria-pressed={false}
            onClick={onFocusToggle}
            title="专注全屏写作 (Ctrl+\\)"
          >
            专注
          </button>
        ) : null}
        <details className={styles.moreMenu}>
          <summary>更多</summary>
          <div className={styles.morePanel} role="menu">
            <button type="button" role="menuitem" onClick={onNewProject}>
              新建剧本
            </button>
            <button type="button" role="menuitem" onClick={onImportClick}>
              导入文件
            </button>
            <button type="button" role="menuitem" onClick={onSaveChapter}>
              保存章节
            </button>
          </div>
        </details>
        <input
          ref={fileInputRef}
          type="file"
          hidden
          accept=".docx,.txt,.md,.rpy,.json,.fountain"
          onChange={onFileChange}
        />
        <button type="button" className={styles.primary} onClick={onExportRpy}>
          导出 .rpy
        </button>
        {username ? (
          <span className={styles.userChip} title={username}>
            {username}
          </span>
        ) : null}
        <button type="button" className={styles.ghost} onClick={onLogout}>
          退出
        </button>
      </div>
    </header>
  );
}
