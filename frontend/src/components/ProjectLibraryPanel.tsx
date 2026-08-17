import type { RefObject } from "react";
import type { ProjectSummary } from "../api/client";
import { TemplatePicker } from "./TemplatePicker";
import styles from "./StudioApp.module.css";

type Props = {
  projectsList: ProjectSummary[];
  activeId: string;
  renamingId: string | null;
  renameDraft: string;
  renameInputRef?: RefObject<HTMLInputElement | null>;
  onRenameDraftChange: (value: string) => void;
  onStartRename: (id: string) => void;
  onCommitRename: () => void;
  onCancelRename: () => void;
  onOpen: (id: string) => void;
  onCreateBlank: () => void;
  onCreateDemo: () => void;
  onPickTemplate: (templateId: string) => void;
  onImportClick: () => void;
  onDuplicate: (id: string) => void;
  onDelete: (id: string) => void;
};

export function ProjectLibraryPanel({
  projectsList,
  activeId,
  renamingId,
  renameDraft,
  renameInputRef,
  onRenameDraftChange,
  onStartRename,
  onCommitRename,
  onCancelRename,
  onOpen,
  onCreateBlank,
  onCreateDemo,
  onPickTemplate,
  onImportClick,
  onDuplicate,
  onDelete,
}: Props) {
  return (
    <>
      <div className={styles.toolbar}>
        <span>管理多个剧本：新建、导入 Word/文本/JSON，或载入示例</span>
        <div className={styles.aiQuick}>
          <button type="button" onClick={onCreateBlank}>
            空白剧本
          </button>
          <button type="button" onClick={onCreateDemo}>
            示例《雨夜车站》
          </button>
          <button type="button" onClick={onImportClick}>
            导入文件
          </button>
        </div>
      </div>
      <TemplatePicker onPick={onPickTemplate} />
      <p className={styles.hint}>
        支持 .docx / .txt / .md / .rpy / 工程
        .json。卡片可点「重命名」或双击标题改名；顶栏标题也可随时改。
      </p>
      <div className={styles.libraryGrid}>
        {projectsList.map((p) => (
          <article
            key={p.id}
            className={
              p.id === activeId ? styles.libraryCardActive : styles.libraryCard
            }
          >
            {renamingId === p.id ? (
              <input
                ref={renameInputRef}
                className={styles.libraryRename}
                value={renameDraft}
                onChange={(e) => onRenameDraftChange(e.target.value)}
                onBlur={() => void onCommitRename()}
                onKeyDown={(e) => {
                  if (e.key === "Enter") {
                    e.preventDefault();
                    void onCommitRename();
                  }
                  if (e.key === "Escape") {
                    e.preventDefault();
                    onCancelRename();
                  }
                }}
                aria-label="重命名剧本"
              />
            ) : (
              <h3
                className={styles.libraryTitle}
                title="双击重命名"
                onDoubleClick={() => onStartRename(p.id)}
              >
                {p.title}
              </h3>
            )}
            <p>{p.logline || "暂无简介"}</p>
            <p className={styles.meta}>
              更新于 {new Date(p.updated_at).toLocaleString()}
            </p>
            <div className={styles.cardActions}>
              <button
                type="button"
                className={styles.primary}
                onClick={() => onOpen(p.id)}
              >
                打开
              </button>
              <button
                type="button"
                className={styles.ghost}
                onClick={() => onStartRename(p.id)}
              >
                重命名
              </button>
              <button
                type="button"
                className={styles.ghost}
                onClick={() => onDuplicate(p.id)}
              >
                复制
              </button>
              <button
                type="button"
                className={styles.ghost}
                onClick={() => onDelete(p.id)}
              >
                删除
              </button>
            </div>
          </article>
        ))}
      </div>
    </>
  );
}
