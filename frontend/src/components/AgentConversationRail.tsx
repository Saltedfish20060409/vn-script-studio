import type { PointerEvent as ReactPointerEvent } from "react";
import type { AgentConversationSummary } from "../api/client";
import styles from "./AgentChat.module.css";

type Props = {
  conversations: AgentConversationSummary[];
  conversationId: string | null;
  titleDrafts: Record<string, string>;
  busy: boolean;
  loadingConv: boolean;
  sidebarW: number;
  dossierOpen: boolean;
  onNew: () => void;
  onSwitch: (id: string) => void;
  onClose: () => void;
  onRenameChange: (id: string, value: string) => void;
  onRenameCommit: (id: string, raw: string) => void;
  onDelete: (id: string) => void;
  /** 把输入框 DOM 注册进父组件的 titleInputRefs 映射（用于新建后聚焦） */
  onTitleRef: (id: string, el: HTMLInputElement | null) => void;
  /** resize 条 onPointerDown：父组件持有 resizing ref + pointer capture 逻辑 */
  onResizeStart: (e: ReactPointerEvent<HTMLDivElement>) => void;
};

/**
 * 卷宗侧栏（aside）：卷宗头 + 对话列表（重命名 input / 删除 / 空态）+ 拖拽宽度 resize 条。
 * 纯受控展示——state 与新建/切换/删除/重命名/缩放逻辑留在 AgentChat。
 */
export function AgentConversationRail({
  conversations,
  conversationId,
  titleDrafts,
  busy,
  loadingConv,
  sidebarW,
  dossierOpen,
  onNew,
  onSwitch,
  onClose,
  onRenameChange,
  onRenameCommit,
  onDelete,
  onTitleRef,
  onResizeStart,
}: Props) {
  return (
    <>
      {dossierOpen ? (
        <button
          type="button"
          className={styles.dossierScrim}
          aria-label="关闭卷宗"
          onClick={onClose}
        />
      ) : null}

      <aside
        className={`${styles.sidebar} ${dossierOpen ? styles.sidebarOpen : ""}`}
        style={{ width: sidebarW }}
        id="agent-dossier"
      >
        <div className={styles.sideStamp} aria-hidden>
          <span>卷</span>
          <em>DOSSIER</em>
        </div>
        <div className={styles.sideHead}>
          <span className={styles.sideTitle}>卷宗</span>
          <div className={styles.sideHeadActions}>
            <button
              type="button"
              className={styles.sideNew}
              disabled={busy || loadingConv}
              onClick={onNew}
              title="新建对话"
            >
              新建
            </button>
            <button
              type="button"
              className={styles.sideClose}
              onClick={onClose}
            >
              收起
            </button>
          </div>
        </div>
        <div className={styles.convList} role="listbox" aria-label="对话列表">
          {conversations.map((c, idx) => {
            const active = c.id === conversationId;
            const num = String(idx + 1).padStart(2, "0");
            return (
              <div
                key={c.id}
                role="option"
                aria-selected={active}
                className={
                  active
                    ? `${styles.convItem} ${styles.convItemActive}`
                    : styles.convItem
                }
                onClick={() => {
                  if (!active) onSwitch(c.id);
                  onClose();
                }}
              >
                <span className={styles.convIdx} aria-hidden>
                  {num}
                </span>
                <input
                  className={styles.convTitleInput}
                  value={titleDrafts[c.id] ?? c.title ?? "新对话"}
                  disabled={busy || loadingConv}
                  ref={(el) => onTitleRef(c.id, el)}
                  onClick={(e) => e.stopPropagation()}
                  onFocus={() => {
                    if (!active) onSwitch(c.id);
                  }}
                  onChange={(e) => onRenameChange(c.id, e.target.value)}
                  onBlur={(e) => onRenameCommit(c.id, e.target.value)}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      (e.target as HTMLInputElement).blur();
                    }
                    e.stopPropagation();
                  }}
                  aria-label="对话名称"
                />
                <button
                  type="button"
                  className={styles.convDel}
                  disabled={busy || loadingConv}
                  title="删除对话"
                  onClick={(e) => {
                    e.stopPropagation();
                    onDelete(c.id);
                  }}
                >
                  ×
                </button>
              </div>
            );
          })}
          {!loadingConv && conversations.length === 0 ? (
            <p className={styles.sideEmpty}>暂无对话</p>
          ) : null}
        </div>
        {dossierOpen ? (
          <div
            className={styles.dossierResize}
            role="separator"
            aria-orientation="vertical"
            aria-label="拖动调整卷宗宽度"
            aria-valuenow={sidebarW}
            onPointerDown={onResizeStart}
          />
        ) : null}
      </aside>
    </>
  );
}
