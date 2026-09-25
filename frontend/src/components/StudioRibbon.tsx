import { useState, type ChangeEvent, type RefObject } from "react";
import { copyFor, type GenreCopy } from "../lib/genreCopy";
import type { ProjectSub, ViewPanel } from "../lib/studioOverlay";
import { openNotice } from "../lib/notice";
import styles from "./StudioRibbon.module.css";

export type WriteMode = "prose" | "rpy";

type MenuId = "file" | "home" | "review" | "view";

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
  /** 当前视图抽屉面板：快捷条高亮用（仅 VN） */
  activeViewPanel?: ViewPanel | null;
  /** 结构分析抽屉是否开着（仅 VN 的快捷条用） */
  analysisOpen?: boolean;
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

const FILE_PAGES_NOVEL: ReadonlyArray<readonly [ProjectSub, string]> = [
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

/** VN：统计/连载往后排，素材与分析更靠前 */
const FILE_PAGES_VN: ReadonlyArray<readonly [ProjectSub, string]> = [
  ["audit", "稿件体检"],
  ["analysis", "结构分析"],
  ["assets", "素材"],
  ["localization", "本地化"],
  ["history", "快照 / 分享"],
  ["members", "成员"],
  ["ledger", "账本 / 摘要"],
  ["stats", "写作统计"],
  ["serial", "连载 / 发布"],
];

const VIEW_QUICK: ReadonlyArray<readonly [ViewPanel, string]> = [
  ["world", "设定"],
  ["voice", "角色工坊"],
  ["map", "地图"],
  ["system", "剧情状态"],
];

/**
 * Word 式顶栏：作品标题 + 文件/开始/审阅/视图。
 * 菜单互斥：同时只开一组；点菜单项后关闭。
 *
 * VN 多一条「视图快捷条」（设定/角色工坊/地图/剧情状态 + 结构分析）：
 * 轻小说的结构单位是"章"，左侧大纲就够；VN 的结构单位是"场景 / 分支 / 结局"，
 * 写作时要反复在稿纸与结构之间来回看——所以它必须是一击可达，
 * 而不是埋在「视图 → 写作分析」里（用户反馈："不如原来适合写 VN 剧本"）。
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
  activeViewPanel = null,
  analysisOpen = false,
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
  const [openMenu, setOpenMenu] = useState<MenuId | null>(null);
  const filePages = copy.genre === "vn" ? FILE_PAGES_VN : FILE_PAGES_NOVEL;
  const showViewQuick = copy.genre === "vn";

  function toggleMenu(id: MenuId) {
    setOpenMenu((prev) => (prev === id ? null : id));
  }

  function runAndClose(fn: () => void) {
    fn();
    setOpenMenu(null);
  }

  return (
    <header className={styles.ribbonWrap} data-testid="studio-ribbon">
      <div className={styles.ribbon}>
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
          <details className={styles.menu} open={openMenu === "file"}>
            <summary
              onClick={(e) => {
                e.preventDefault();
                toggleMenu("file");
              }}
            >
              文件
            </summary>
            <div className={styles.panel} role="menu">
              <button
                type="button"
                role="menuitem"
                onClick={() => runAndClose(onNewProject)}
              >
                {copy.newWork}
              </button>
              <button
                type="button"
                role="menuitem"
                onClick={() => runAndClose(() => onOpenFilePage("library"))}
              >
                打开（{copy.library}）
              </button>
              <button
                type="button"
                role="menuitem"
                onClick={() => runAndClose(onImportClick)}
              >
                导入文件
              </button>
              <button
                type="button"
                role="menuitem"
                onClick={() => runAndClose(onSaveChapter)}
              >
                保存章节
              </button>
              <button
                type="button"
                role="menuitem"
                onClick={() => runAndClose(onExport)}
              >
                {exportLabel}
              </button>
              <button
                type="button"
                role="menuitem"
                onClick={() => runAndClose(() => onOpenFilePage("export"))}
              >
                导出…
              </button>
              <hr className={styles.sep} />
              {filePages.map(([id, label]) => (
                <button
                  key={id}
                  type="button"
                  role="menuitem"
                  onClick={() => runAndClose(() => onOpenFilePage(id))}
                >
                  {label}
                </button>
              ))}
              <hr className={styles.sep} />
              {canReturnDesktop && onReturnDesktop ? (
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => runAndClose(onReturnDesktop)}
                >
                  返回桌面
                </button>
              ) : null}
              <button
                type="button"
                role="menuitem"
                onClick={() => runAndClose(onOpenSettings)}
              >
                系统设置
              </button>
              <button
                type="button"
                role="menuitem"
                onClick={() => runAndClose(onOpenHelp)}
              >
                帮助 / FAQ
              </button>
              <button
                type="button"
                role="menuitem"
                onClick={() => runAndClose(openNotice)}
              >
                更新公告
              </button>
              {showAdmin && onOpenAdmin ? (
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => runAndClose(onOpenAdmin)}
                >
                  管理后台{adminAlert ? " · 有异常" : ""}
                </button>
              ) : null}
              <button
                type="button"
                role="menuitem"
                onClick={() => runAndClose(onLogout)}
              >
                退出
              </button>
            </div>
          </details>

          <details className={styles.menu} open={openMenu === "home"}>
            <summary
              onClick={(e) => {
                e.preventDefault();
                toggleMenu("home");
              }}
            >
              开始
            </summary>
            <div className={styles.panel} role="menu">
              <button
                type="button"
                role="menuitem"
                aria-checked={writeMode === "prose"}
                onClick={() => runAndClose(() => onWriteModeChange("prose"))}
              >
                {copy.proseMode}
                {writeMode === "prose" ? " ✓" : ""}
              </button>
              <button
                type="button"
                role="menuitem"
                aria-checked={writeMode === "rpy"}
                onClick={() => runAndClose(() => onWriteModeChange("rpy"))}
              >
                {copy.scriptMode}
                {writeMode === "rpy" ? " ✓" : ""}
              </button>
              {writeMode === "rpy" ? (
                <button
                  type="button"
                  role="menuitem"
                  disabled={generating}
                  onClick={() => runAndClose(onGenerateRpy)}
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
              <button
                type="button"
                role="menuitem"
                onClick={() => runAndClose(onFind)}
              >
                查找 / 替换
              </button>
              {onInsertScene ? (
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => runAndClose(onInsertScene)}
                >
                  插入分场标记
                </button>
              ) : null}
              {showFocusToggle ? (
                <button
                  type="button"
                  role="menuitem"
                  onClick={() => runAndClose(onFocusToggle)}
                >
                  专注（Ctrl+\）
                </button>
              ) : null}
            </div>
          </details>

          <details className={styles.menu} open={openMenu === "review"}>
            <summary
              onClick={(e) => {
                e.preventDefault();
                toggleMenu("review");
              }}
            >
              审阅
            </summary>
            <div className={styles.panel} role="menu">
              <button
                type="button"
                role="menuitem"
                onClick={() => runAndClose(onOpenAgent)}
              >
                AI 责编
              </button>
              {showReviseActions ? (
                <>
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => runAndClose(onOpenRevise)}
                  >
                    查看改稿对比
                  </button>
                  <button
                    type="button"
                    role="menuitem"
                    onClick={() => runAndClose(onDiscardRevise)}
                  >
                    放弃改稿（正文不动）
                  </button>
                </>
              ) : null}
              <p className={styles.hint}>
                标记批改：在正文选中一段后按 Ctrl+M；批注在稿纸下方面板。
              </p>
            </div>
          </details>

          <details className={styles.menu} open={openMenu === "view"}>
            <summary
              onClick={(e) => {
                e.preventDefault();
                toggleMenu("view");
              }}
            >
              视图
            </summary>
            <div className={styles.panel} role="menu">
              {VIEW_QUICK.map(([id, label]) => (
                <button
                  key={id}
                  type="button"
                  role="menuitem"
                  onClick={() => runAndClose(() => onOpenViewPanel(id))}
                >
                  {label}
                </button>
              ))}
              <button
                type="button"
                role="menuitem"
                onClick={() => runAndClose(onOpenAnalysis)}
              >
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
      </div>

      {showViewQuick ? (
        <div
          className={styles.viewQuick}
          data-testid="vn-view-quick"
          role="toolbar"
          aria-label="视图快捷入口"
        >
          {VIEW_QUICK.map(([id, label]) => (
            <button
              key={id}
              type="button"
              className={
                activeViewPanel === id ? styles.viewQuickOn : styles.viewQuickBtn
              }
              aria-pressed={activeViewPanel === id}
              onClick={() => onOpenViewPanel(id)}
            >
              {label}
            </button>
          ))}
          {/* 结构分析（分支 / 选项 / 结局 / 节奏）是 VN 最常用的对照面，
              所以它也在快捷条上，而不是只在「视图」菜单里。 */}
          <button
            type="button"
            className={analysisOpen ? styles.viewQuickOn : styles.viewQuickBtn}
            data-testid="vn-quick-analysis"
            aria-pressed={analysisOpen}
            title="结构分析：分支 / 选项 / 结局 / 节奏（与稿纸来回对照）"
            onClick={onOpenAnalysis}
          >
            结构分析
          </button>
        </div>
      ) : null}
    </header>
  );
}
