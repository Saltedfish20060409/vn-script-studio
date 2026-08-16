import type {
  MemoryArchiveDetail,
  MemoryArchiveSummary,
  SnapshotSummary,
} from "../api/client";
import styles from "./StudioApp.module.css";

type Props = {
  memoryArchives: MemoryArchiveSummary[];
  memoryDetailBusy: boolean;
  memoryDetail: MemoryArchiveDetail | null;
  snapLabel: string;
  snapshots: SnapshotSummary[];
  shareUrl: string;
  hasShare: boolean;
  onArchiveMemory: () => void;
  onOpenMemoryArchive: (id: string) => void;
  onCloseMemoryDetail: () => void;
  onSnapLabelChange: (value: string) => void;
  onTakeSnapshot: () => void;
  onRestoreSnapshot: (id: string) => void;
  onDeleteSnapshot: (id: string) => void;
  onCreateShare: () => void;
  onRevokeShare: () => void;
};

/**
 * 项目 → 快照 / 分享 sub-tab: long-term memory archives, snapshots, share link.
 * Pure presentational — async work and status logic stay in StudioApp.
 */
export function ProjectHistoryPanel({
  memoryArchives,
  memoryDetailBusy,
  memoryDetail,
  snapLabel,
  snapshots,
  shareUrl,
  hasShare,
  onArchiveMemory,
  onOpenMemoryArchive,
  onCloseMemoryDetail,
  onSnapLabelChange,
  onTakeSnapshot,
  onRestoreSnapshot,
  onDeleteSnapshot,
  onCreateShare,
  onRevokeShare,
}: Props) {
  return (
    <>
      <div className={styles.toolbar}>
        <span>版本快照可回退大改稿；只读链接给画师 / 配音看设定</span>
      </div>
      <div className={styles.shareBox}>
        <strong>长程章节记忆</strong>
        <p style={{ margin: 0, fontSize: "0.85rem", color: "var(--ink-soft)" }}>
          借鉴 NovelMaster：每 10 章一段 continuity，拆成 PostgreSQL TEXT 切片；Agent
          会自动注入最新段。
        </p>
        <div className={styles.aiQuick}>
          <button type="button" className={styles.primary} onClick={onArchiveMemory}>
            归档长程记忆
          </button>
        </div>
        <ul className={styles.snapList}>
          {memoryArchives.map((a) => (
            <li key={a.id}>
              <span>
                {a.label}
                {a.isLatest ? " · 最新" : ""}
                <br />
                <small>
                  第 {a.rangeFrom}–{a.rangeTo} 章 · {a.wordCount} 字
                </small>
              </span>
              <button
                type="button"
                className={styles.ghost}
                disabled={memoryDetailBusy}
                onClick={() => onOpenMemoryArchive(a.id)}
              >
                查看
              </button>
            </li>
          ))}
          {memoryArchives.length === 0 && <li>尚未归档。章节较多时点上方按钮生成。</li>}
        </ul>
        {memoryDetail && (
          <div className={styles.memoryPeek}>
            <div className={styles.toolbar}>
              <strong>{memoryDetail.label}</strong>
              <button
                type="button"
                className={styles.ghost}
                onClick={onCloseMemoryDetail}
              >
                关闭
              </button>
            </div>
            <p className={styles.hint}>continuity 切片预览（Agent 注入用最新段）</p>
            <pre className={styles.pre}>
              {(memoryDetail.continuityText || "").slice(0, 4000) ||
                "（无 continuity 正文）"}
              {(memoryDetail.continuityText || "").length > 4000 ? "\n…(已截断)" : ""}
            </pre>
          </div>
        )}
      </div>
      <div className={styles.shareBox}>
        <strong>快照</strong>
        <div className={styles.aiQuick}>
          <input
            value={snapLabel}
            onChange={(e) => onSnapLabelChange(e.target.value)}
            placeholder="快照备注（可选）"
          />
          <button type="button" className={styles.primary} onClick={onTakeSnapshot}>
            保存当前快照
          </button>
        </div>
        <ul className={styles.snapList}>
          {snapshots.map((s) => (
            <li key={s.id}>
              <span>
                {s.label}
                <br />
                <small>{new Date(s.createdAt).toLocaleString()}</small>
              </span>
              <span>
                <button
                  type="button"
                  className={styles.ghost}
                  onClick={() => onRestoreSnapshot(s.id)}
                >
                  回退到此
                </button>
                <button
                  type="button"
                  className={styles.ghost}
                  onClick={() => onDeleteSnapshot(s.id)}
                >
                  删除
                </button>
              </span>
            </li>
          ))}
          {snapshots.length === 0 && <li>尚无快照</li>}
        </ul>
      </div>
      <div className={styles.shareBox}>
        <strong>只读分享</strong>
        <p className={styles.hint}>
          生成链接后任何人都可打开只读页面查看设定摘要；可随时撤销。
        </p>
        <div className={styles.aiQuick}>
          <button type="button" className={styles.primary} onClick={onCreateShare}>
            生成并复制链接
          </button>
          {hasShare && (
            <button type="button" onClick={onRevokeShare}>
              撤销分享
            </button>
          )}
        </div>
        {shareUrl && (
          <input readOnly value={shareUrl} onFocus={(e) => e.target.select()} />
        )}
      </div>
    </>
  );
}
