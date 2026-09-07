import type {
  MemoryArchiveDetail,
  MemoryArchiveSummary,
  SnapshotDiffResult,
  SnapshotSummary,
} from "../api/client";
import styles from "./StudioApp.module.css";

type Props = {
  memoryArchives: MemoryArchiveSummary[];
  memoryDetailBusy: boolean;
  memoryDetail: MemoryArchiveDetail | null;
  snapLabel: string;
  snapshots: SnapshotSummary[];
  compareBusy: boolean;
  compareResult: SnapshotDiffResult | null;
  compareAgainstId: string | null;
  shareUrl: string;
  hasShare: boolean;
  onArchiveMemory: () => void;
  onOpenMemoryArchive: (id: string) => void;
  onCloseMemoryDetail: () => void;
  onSnapLabelChange: (value: string) => void;
  onTakeSnapshot: () => void;
  onRestoreSnapshot: (id: string) => void;
  onDeleteSnapshot: (id: string) => void;
  onCompareSnapshot: (id: string) => void;
  onCloseCompare: () => void;
  onCreateShare: () => void;
  onRevokeShare: () => void;
};

function fmtDelta(diff: number, suffix = "字"): string {
  if (diff === 0) return "±0";
  return diff > 0 ? `+${diff}${suffix}` : `${diff}${suffix}`;
}

function CompareReport({
  result,
  onClose,
}: {
  result: SnapshotDiffResult;
  onClose: () => void;
}) {
  const changedChapters = result.chapters.filter((c) => c.status !== "same");
  const changedChars = result.characters.filter((c) => c.status !== "same");
  return (
    <div className={styles.memoryPeek}>
      <div className={styles.toolbar}>
        <strong>快照对比</strong>
        <button type="button" className={styles.ghost} onClick={onClose}>
          关闭
        </button>
      </div>
      <p className={styles.hint}>{result.summary}</p>
      {changedChapters.length > 0 && (
        <ul className={styles.snapList}>
          {changedChapters.map((c) => (
            <li key={c.chapterId}>
              <span>
                {c.title || c.chapterId}
                <br />
                <small>
                  {c.status === "added"
                    ? "新增章节"
                    : c.status === "removed"
                      ? "已删除章节"
                      : `字数 ${fmtDelta(c.wordsTo - c.wordsFrom)} · 对白 ${fmtDelta(
                          c.linesTo - c.linesFrom,
                          "行"
                        )}`}
                </small>
              </span>
            </li>
          ))}
        </ul>
      )}
      {changedChars.length > 0 && (
        <p className={styles.hint}>
          角色变化：
          {changedChars
            .map(
              (c) =>
                `${c.name}（${c.status === "added" ? "新增" : "移除"}）`
            )
            .join("、")}
        </p>
      )}
      {(result.locations.added > 0 ||
        result.locations.removed > 0 ||
        result.timeline.added > 0 ||
        result.timeline.removed > 0) && (
        <p className={styles.hint}>
          地点 +{result.locations.added}/-{result.locations.removed} ·
          时间线 +{result.timeline.added}/-{result.timeline.removed}
        </p>
      )}
      {changedChapters.length === 0 && changedChars.length === 0 ? (
        <p className={styles.hint}>与当前版本没有章节或角色差异。</p>
      ) : null}
    </div>
  );
}

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
  compareBusy,
  compareResult,
  compareAgainstId,
  shareUrl,
  hasShare,
  onArchiveMemory,
  onOpenMemoryArchive,
  onCloseMemoryDetail,
  onSnapLabelChange,
  onTakeSnapshot,
  onRestoreSnapshot,
  onDeleteSnapshot,
  onCompareSnapshot,
  onCloseCompare,
  onCreateShare,
  onRevokeShare,
}: Props) {
  return (
    <>
      <div className={styles.toolbar}>
        <span>版本快照可回退大改稿；只读链接给画师 / 配音看设定</span>
      </div>
      <div className={styles.shareBox}>
        <strong>章节记忆存档</strong>
        <p style={{ margin: 0, fontSize: "0.85rem", color: "var(--ink-soft)" }}>
          章节多起来后，点下面按钮把每 10 章左右的剧情要点整理成一段文字摘要存档，
          AI 写作时会参考存档的最新部分。注意：AI 记不住整本书，它只按需读取这份存档和你的设定，
          内容过长时会被截断。
        </p>
        <div className={styles.aiQuick}>
          <button type="button" className={styles.primary} onClick={onArchiveMemory}>
            生成章节记忆
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
          {memoryArchives.length === 0 && <li>还没有记忆存档。章节较多时点上方按钮生成。</li>}
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
            <p className={styles.hint}>记忆内容预览（只读，不改动你的正文；AI 写作时会参考这份记忆的最近部分）</p>
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
                {s.label.startsWith("自动备份") ? " · ⏱" : ""}
                <br />
                <small>{new Date(s.createdAt).toLocaleString()}</small>
              </span>
              <span>
                <button
                  type="button"
                  className={styles.ghost}
                  disabled={compareBusy}
                  onClick={() => onCompareSnapshot(s.id)}
                >
                  {compareBusy && compareAgainstId === s.id ? "对比中…" : "对比当前"}
                </button>
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
        {compareResult && <CompareReport result={compareResult} onClose={onCloseCompare} />}
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
