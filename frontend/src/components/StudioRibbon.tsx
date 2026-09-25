import type { ChangeEvent, RefObject } from "react";
import { copyFor, type GenreCopy } from "../lib/genreCopy";
import type { ProjectSub, ViewPanel } from "../lib/studioOverlay";
import { openNotice } from "../lib/notice";
import styles from "./StudioRibbon.module.css";

export type WriteMode = "prose" | "rpy";

type Props = {
  copy?: GenreCopy;
  title: string;
  username?: string;
  saveBadge?: "saving" | "error" | null;
  showFocusToggle: boolean;
  writeMode: WriteMode;
  rpyStale?: boolean;
  generating?: boolean;
  showReviseActions: boolean;
  showAdmin?: boolean;
  adminAlert?: boolean;
  canReturnDesktop?: boolean;
  fileInputRef: RefObject<HTMLInputElement | null>;
  onTitleChange: (value: string) => void;
  onFocusToggle: () => void;
  onNewProject: () => void;
  onImportClick: () => void;
  onFileChange: (e: ChangeEvent<HTMLInputElement>) => void;
  onSaveChapter: () => void;
  onExport: () => void;
  exportLabel: string;
  onOpenHelp: () => void;
  onOpenAdmin?: () => void;
  onOpenSettings: () => void;
  onReturnDesktop?: () => void;
  onLogout: () => void;
  onOpenFilePage: (page: ProjectSub) => void;
  onOpenViewPanel: (panel: ViewPanel) => void;
  onOpenAnalysis: () => void;
  onOpenAgent: () => void;
  onWriteModeChange: (mode: WriteMode) => void;
  onGenerateRpy: () => void;
  onFind: () => void;
  onOpenRevise: () => void;
  onDiscardRevise: () => void;
  onInsertScene?: () => void;
};

const FILE_PAGES: ReadonlyArray<readonly [ProjectSub, string]> = [
  ["library", "打开（剧本库）"],
  ["export", "导出…"],
  ["stats", "写作统计"],
  ["serial", "连载 / 发布"],
  ["audit", "稿件体检"],
  ["analysis", "结构分析"],
  ["ledger", "账本 / 摘要"],
  ["assets", "素材"],
  ["localization", "本地化"],
  ["history", "快照 / 分享"],
  ["members", "成员"],
];

/**
 * Word 式顶栏：作品标题 + 文件/开始/审阅/视图 四菜单。
 * 纯展示；所有动作经 callback 交给 StudioApp。
 */
export function StudioRibbon({
  copy = copyFor("vn"),
  title,
  username,
  saveBadge = null,
  showFocusToggle,
  writeMode,
  rpyStale,
  generating,
  showReviseActions,
  showAdmin = false,
  adminAlert = false,
  canReturnDesktop = false,
  fileInputRef,
  onTitleChange,
  onFocusToggle,
  onNewProject,
  onImportClick,
  onFileChange,
  onSaveChapter,
  onExport,
  exportLabel,
  onOpenHelp,
  onOpenAdmin,
  onOpenSettings,
  onReturnDesktop,
  onLogout,
  onOpenFilePage,
  onOpenViewPanel,
  onOpenAnalysis,
  onOpenAgent,
  onWriteModeChange,
  onGenerateRpy,
  onFind,
  onOpenRevise,
  onDiscardRevise,
  onInsertScene,
}: Props) {
  return (
    <header className={styles.ribbon} data-testid="studio-ribbon">
      <div className={styles.brandBlock}>
        <span className={styles.brandMark} aria-hidden>
          <em>SS</em>
          <span>VN</span>
        </span>
        <input
          className={styles.titleInput}
          value={title}
          onChange={(e) => onTitleChange(e.target.value)}
          aria-label="作品标题"
          placeholder="作品标题"
        />
        {saveBadge === "saving" ? (
          <span
            className={styles.saveBadge}
            data-testid="save-badge"
            data-kind="saving"
            role="status"
            aria-live="polite"
          >
            保存中…
          </span>
        ) : saveBadge === "error" ? (
          <span
            className={`${styles.saveBadge} ${styles.saveBadgeError}`}
            data-testid="save-badge"
            data-kind="error"
            role="status"
            aria-live="assertive"
            title="自动保存失败，可用「文件 → 保存章节」手动保存"
          >
            保存失败
          </span>
        ) : null}
      </div>

      <nav className={styles.menus} aria-label="写作菜单">
        <details className={styles.menu}>
          <summary>文件</summary>
          <div className={styles.panel} role="menu">
            <button type="button" role="menuitem" onClick={onNewProject}>
              {copy.newWork}
            </button>
            <button
              type="button"
              role="menuitem"
              onClick={() => onOpenFilePage("library")}
            >
              打开（剧本库）
            </button>
            <button type="button" role="menuitem" onClick={onImportClick}>
              导入文件
            </button>
            <button type="button" role="menuitem" onClick={onSaveChapter}>
              保存章节
            </button>
            <button type="button" role="menuitem" onClick={onExport}>
              {exportLabel}
            </button>
            <button
              type="button"
              role="menuitem"
              onClick={() => onOpenFilePage("export")}
            >
              导出…
            </button>
            <hr className={styles.sep} />
            {FILE_PAGES.filter(([id]) => id !== "library" && id !== "export").map(
              ([id, label]) => (
                <button
                  key={id}
                  type="button"
                  role="menuitem"
                  onClick={() => onOpenFilePage(id)}
                >
                  {label}
                </button>
              )
            )}
            <hr className={styles.sep} />
            {canReturnDesktop && onReturnDesktop ? (
              <button type="button" role="menuitem" onClick={onReturnDesktop}>
                返回桌面
              </button>
            ) : null}
            <button type="button" role="menuitem" onClick={onOpenSettings}>
              系统设置
            </button>
            <button type="button" role="menuitem" onClick={onOpenHelp}>
              帮助 / FAQ
            </button>
            <button type="button" role="menuitem" onClick={openNotice}>
              更新公告
            </button>
            {showAdmin && onOpenAdmin ? (
              <button type="button" role="menuitem" onClick={onOpenAdmin}>
                管理后台{adminAlert ? " · 有异常" : ""}
              </button>
            ) : null}
            <button type="button" role="menuitem" onClick={onLogout}>
              退出
            </button>
          </div>
        </details>

        <details className={styles.menu}>
          <summary>开始</summary>
          <div className={styles.panel} role="menu">
            <button
              type="button"
              role="menuitem"
              aria-checked={writeMode === "prose"}
              onClick={() => onWriteModeChange("prose")}
            >
              {copy.proseMode}
              {writeMode === "prose" ? " ✓" : ""}
            </button>
            <button
              type="button"
              role="menuitem"
              aria-checked={writeMode === "rpy"}
              onClick={() => onWriteModeChange("rpy")}
            >
              {copy.scriptMode}
              {writeMode === "rpy" ? " ✓" : ""}
            </button>
            {writeMode === "rpy" ? (
              <button
                type="button"
                role="menuitem"
                disabled={generating}
                onClick={onGenerateRpy}
              >
                {generating ? "生成中…" : copy.generateScript}
              </button>
            ) : null}
            {rpyStale && writeMode === "rpy" ? (
              <p className={styles.hint}>
                {copy.genre === "novel"
                  ? `${copy.proseMode}已改，${copy.scriptMode}可能过期`
                  : `${copy.proseMode}已改，${copy.scriptMode} 可能过期`}
              </p>
            ) : null}
            <hr className={styles.sep} />
            <button type="button" role="menuitem" onClick={onFind}>
              查找 / 替换
            </button>
            {onInsertScene ? (
              <button type="button" role="menuitem" onClick={onInsertScene}>
                插入分场标记
              </button>
            ) : null}
            {showFocusToggle ? (
              <button type="button" role="menuitem" onClick={onFocusToggle}>
                专注（Ctrl+\）
              </button>
            ) : null}
          </div>
        </details>

        <details className={styles.menu}>
          <summary>审阅</summary>
          <div className={styles.panel} role="menu">
            <button type="button" role="menuitem" onClick={onOpenAgent}>
              AI 责编
            </button>
            {showReviseActions ? (
              <>
                <button type="button" role="menuitem" onClick={onOpenRevise}>
                  查看改稿对比
                </button>
                <button type="button" role="menuitem" onClick={onDiscardRevise}>
                  放弃改稿（正文不动）
                </button>
              </>
            ) : null}
            <p className={styles.hint}>
              标记批改：在正文选中一段后按 Ctrl+M；批注在稿纸下方面板。
            </p>
          </div>
        </details>

        <details className={styles.menu}>
          <summary>视图</summary>
          <div className={styles.panel} role="menu">
            <button
              type="button"
              role="menuitem"
              onClick={() => onOpenViewPanel("world")}
            >
              设定
            </button>
            <button
              type="button"
              role="menuitem"
              onClick={() => onOpenViewPanel("voice")}
            >
              角色工坊
            </button>
            <button
              type="button"
              role="menuitem"
              onClick={() => onOpenViewPanel("map")}
            >
              地图
            </button>
            <button
              type="button"
              role="menuitem"
              onClick={() => onOpenViewPanel("system")}
            >
              剧情状态
            </button>
            <button type="button" role="menuitem" onClick={onOpenAnalysis}>
              写作分析
            </button>
          </div>
        </details>
      </nav>

      <div className={styles.actions}>
        {showFocusToggle ? (
          <button
            type="button"
            className={styles.focusBtn}
            onClick={onFocusToggle}
            title="专注全屏写作（快捷键 Ctrl+\\，Mac 为 ⌘\\）"
          >
            专注
            <kbd className={styles.kbd} aria-hidden>
              Ctrl+\
            </kbd>
          </button>
        ) : null}
        <button
          type="button"
          className={styles.ghost}
          onClick={onOpenAgent}
          title="打开审稿 Agent"
        >
          审稿
        </button>
        <button type="button" className={styles.primary} onClick={onExport}>
          {exportLabel}
        </button>
        {username ? (
          <span className={styles.userChip} title={username}>
            {username}
          </span>
        ) : null}
      </div>

      <input
        ref={fileInputRef}
        type="file"
        hidden
        accept=".docx,.txt,.md,.rpy,.json,.fountain"
        onChange={onFileChange}
      />
    </header>
  );
}
