import { shortQuote, type Mark } from "../lib/marks";
import styles from "./MarksPanel.module.css";

type Props = {
  marks: Mark[];
  /** 当前正在核对的标记（卡片贴在它那一行旁边） */
  activeId: string | null;
  busyId: string | null;
  progress: { done: number; total: number } | null;
  hasStyleMemory: boolean;
  /** 当前正文里选中了几个字（0 = 没选中，标记按钮会提示） */
  selectionLength: number;
  onMarkSelection: () => void;
  onProcessAll: () => void;
  onStop: () => void;
  /** 选中某条标记：编辑器滚到它那儿，卡片贴过去 */
  onSelect: (id: string) => void;
  onRemove: (id: string) => void;
};

const STATUS_LABEL: Record<Mark["status"], string> = {
  pending: "待处理",
  suggested: "待决定",
  accepted: "已写入",
  rejected: "已忽略",
  stale: "已失效",
};

/**
 * 标记条：所有标记的**导航 + 批量**入口。
 *
 * 明细（要求 / 对照稿 / 接受）不在这里做——那些都在贴着正文那一行的
 * `MarkCard` 上，因为长章节里"标记在上、面板在下"核对要来回滚。
 */
export function MarksPanel({
  marks,
  activeId,
  busyId,
  progress,
  hasStyleMemory,
  selectionLength,
  onMarkSelection,
  onProcessAll,
  onStop,
  onSelect,
  onRemove,
}: Props) {
  // 「可处理」= 还没结果的，或上次失败的（失效的标记没得处理，不该算进按钮数字里）
  const processable = marks.filter((m) => m.status === "pending" || Boolean(m.error)).length;
  const processing = busyId !== null || progress !== null;

  return (
    <section className={styles.wrap} data-testid="marks-panel">
      <div className={styles.head}>
        <strong className={styles.title}>标记批改</strong>
        <span className={styles.hint}>
          {selectionLength > 0
            ? `已选中 ${selectionLength} 字`
            : "选中正文里要改的一段，再点「标记这段」或按 Ctrl+M"}
        </span>
        <button
          type="button"
          className={styles.markBtn}
          data-testid="mark-selection"
          disabled={selectionLength === 0}
          onClick={onMarkSelection}
          title="把选中的这一段标成「要改」（随后在正文旁边直接处理）"
        >
          ✚ 标记这段
        </button>
        {marks.length > 0 ? (
          <button
            type="button"
            className={styles.primary}
            data-testid="marks-process-all"
            disabled={processing || processable === 0}
            onClick={onProcessAll}
            title="逐条处理所有待处理标记（每条失败不影响其它；已失效的不会处理）"
          >
            {progress ? `处理中 ${progress.done}/${progress.total}` : `按标记处理（${processable}）`}
          </button>
        ) : null}
        {processing ? (
          <button type="button" className={styles.ghost} onClick={onStop}>
            停止
          </button>
        ) : null}
        {hasStyleMemory ? (
          <span className={styles.styleTag} title="项目里学过你的文风，改写会尽量贴你自己的腔调">
            按你的文风改
          </span>
        ) : null}
      </div>

      {marks.length === 0 ? (
        <p className={styles.empty}>
          还没有标记。选中一段文字 → 点「标记这段」→ 正文里那一段会被标出来，旁边直接给出对照稿；接受才写进正文。
        </p>
      ) : (
        <ul className={styles.chips}>
          {marks.map((mark, idx) => (
            <li key={mark.id}>
              <button
                type="button"
                className={`${styles.chip} ${mark.id === activeId ? styles.chipActive : ""} ${
                  styles[`c_${mark.status}`]
                }`}
                data-testid={`mark-chip-${idx}`}
                onClick={() => onSelect(mark.id)}
                title={`${STATUS_LABEL[mark.status]}：${mark.quote}`}
              >
                <span className={styles.chipSeq}>{idx + 1}</span>
                <span className={styles.chipText}>{shortQuote(mark.quote, 18)}</span>
                <span className={styles.chipDot} aria-hidden />
              </button>
              <button
                type="button"
                className={styles.chipX}
                data-testid={`mark-chip-remove-${idx}`}
                onClick={() => onRemove(mark.id)}
                title="删掉这个标记"
              >
                ✕
              </button>
            </li>
          ))}
        </ul>
      )}

      {marks.length > 0 ? (
        <p className={styles.foot}>
          点标记条上的编号可以跳到那一处（卡片会贴着正文那一段）；正文被改动后定位不到的标记会标成「已失效」。
        </p>
      ) : null}
    </section>
  );
}
