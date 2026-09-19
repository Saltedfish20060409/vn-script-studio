import { useState, type ChangeEvent } from "react";
import { shortQuote, type Mark } from "../lib/marks";
import styles from "./MarksPanel.module.css";

type Props = {
  marks: Mark[];
  /** 正在处理的标记 id（单条） */
  busyId: string | null;
  /** 批量处理的进度（处理中才非空） */
  progress: { done: number; total: number } | null;
  /** 有没有可用的文风记忆（决定"按你的文风改"是否生效） */
  hasStyleMemory: boolean;
  /** 当前正文里选中了几个字（0 = 没选中，标记按钮会提示） */
  selectionLength: number;
  onMarkSelection: () => void;
  onProcess: (id: string) => void;
  onProcessAll: () => void;
  onStop: () => void;
  onAccept: (id: string, edited?: string) => void;
  onReject: (id: string) => void;
  onRevert: (id: string) => void;
  onRemove: (id: string) => void;
  onJump: (id: string) => void;
  onInstruction: (id: string, value: string) => void;
  onIntent: (id: string, intent: "rewrite" | "advice") => void;
};

const STATUS_LABEL: Record<Mark["status"], string> = {
  pending: "待处理",
  suggested: "待决定",
  accepted: "已写入",
  rejected: "已忽略",
  stale: "已失效",
};

/**
 * 写作页的「标记批改」面板：作者标出来的每一处 + AI 的对照稿，逐条接受/拒绝。
 *
 * 设计取舍：默认**不自动写入**正文（每条都要点接受），因为改稿最怕"悄悄改过"；
 * 接受后可以单独撤回，正文改动仍然走编辑器原有的保存/快照链路。
 */
export function MarksPanel({
  marks,
  busyId,
  progress,
  hasStyleMemory,
  selectionLength,
  onMarkSelection,
  onProcess,
  onProcessAll,
  onStop,
  onAccept,
  onReject,
  onRevert,
  onRemove,
  onJump,
  onInstruction,
  onIntent,
}: Props) {
  const [editing, setEditing] = useState<Record<string, string>>({});
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
          title="把选中的这一段标成「要改」（可以之后再补一句要求）"
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
            title="逐条处理所有待处理标记（每条失败不影响其它；已失效的标记不会处理）"
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
          还没有标记。选中一段文字 → 点「标记这段」→ 一次点「按标记处理」，AI 只改这一处，其余一字不动。
        </p>
      ) : null}

      <ul className={styles.list}>
        {marks.map((mark, idx) => {
          const busy = busyId === mark.id;
          const editValue = editing[mark.id] ?? mark.replacement ?? "";
          return (
            <li
              key={mark.id}
              className={`${styles.item} ${mark.status === "accepted" ? styles.itemDone : ""} ${
                mark.status === "stale" ? styles.itemStale : ""
              }`}
              data-testid={`mark-item-${idx}`}
            >
              <div className={styles.itemHead}>
                <span className={styles.seq}>{idx + 1}</span>
                <button
                  type="button"
                  className={styles.quote}
                  onClick={() => onJump(mark.id)}
                  title="跳到正文里这一处"
                >
                  {shortQuote(mark.quote, 34)}
                </button>
                <span className={`${styles.status} ${styles[`status_${mark.status}`]}`}>
                  {busy ? "处理中…" : STATUS_LABEL[mark.status]}
                </span>
                <button
                  type="button"
                  className={styles.ghost}
                  onClick={() => onRemove(mark.id)}
                  title="删掉这个标记（不改正文）"
                >
                  ✕
                </button>
              </div>

              {mark.status !== "accepted" ? (
                <div className={styles.row}>
                  <div className={styles.intentSwitch} role="group" aria-label="标记意图">
                    <button
                      type="button"
                      className={mark.intent === "rewrite" ? styles.intentOn : styles.intent}
                      onClick={() => onIntent(mark.id, "rewrite")}
                      title="按你的要求改写这一段"
                    >
                      改
                    </button>
                    <button
                      type="button"
                      className={mark.intent === "advice" ? styles.intentOn : styles.intent}
                      onClick={() => onIntent(mark.id, "advice")}
                      title="只让它指出问题、给建议，不动正文"
                    >
                      问
                    </button>
                  </div>
                  <input
                    className={styles.input}
                    value={mark.instruction}
                    placeholder={
                      mark.intent === "advice" ? "想问什么（可留空）" : "要求，例如：更冷一点 / 短一些（可留空）"
                    }
                    onChange={(e: ChangeEvent<HTMLInputElement>) =>
                      onInstruction(mark.id, e.target.value)
                    }
                  />
                  <button
                    type="button"
                    className={styles.primary}
                    disabled={processing}
                    onClick={() => onProcess(mark.id)}
                  >
                    {mark.replacement || mark.advice ? "重新处理" : "处理"}
                  </button>
                </div>
              ) : null}

              {mark.error ? <p className={styles.error}>出错了：{mark.error}</p> : null}

              {mark.advice && mark.intent === "advice" ? (
                <p className={styles.advice} data-testid={`mark-advice-${idx}`}>
                  {mark.advice}
                </p>
              ) : null}

              {mark.replacement && mark.intent === "rewrite" ? (
                <div className={styles.diff}>
                  <div className={styles.diffSide}>
                    <span className={styles.diffLabel}>原文</span>
                    <p className={styles.diffOld}>{mark.quote}</p>
                  </div>
                  <div className={styles.diffSide}>
                    <span className={styles.diffLabel}>改后（可以直接改）</span>
                    <textarea
                      className={styles.diffNew}
                      data-testid={`mark-replacement-${idx}`}
                      value={editValue}
                      rows={Math.min(6, Math.max(2, Math.ceil(editValue.length / 46)))}
                      onChange={(e) => setEditing((p) => ({ ...p, [mark.id]: e.target.value }))}
                    />
                  </div>
                </div>
              ) : null}

              <div className={styles.actions}>
                {mark.status !== "accepted" ? (
                  <>
                    <button
                      type="button"
                      className={styles.accept}
                      data-testid={`mark-accept-${idx}`}
                      disabled={!mark.replacement || mark.intent === "advice"}
                      onClick={() => onAccept(mark.id, editing[mark.id])}
                      title="写入正文（可以之后再撤回）"
                    >
                      ✓ 接受
                    </button>
                    <button
                      type="button"
                      className={styles.ghost}
                      data-testid={`mark-reject-${idx}`}
                      onClick={() => onReject(mark.id)}
                    >
                      忽略
                    </button>
                  </>
                ) : (
                  <button
                    type="button"
                    className={styles.ghost}
                    data-testid={`mark-revert-${idx}`}
                    onClick={() => onRevert(mark.id)}
                  >
                    ↩ 撤回这次改动
                  </button>
                )}
              </div>
            </li>
          );
        })}
      </ul>

      {marks.some((m) => m.status === "accepted") ? (
        <p className={styles.foot}>已写入的改动可以逐条撤回；正文保存/快照走原有流程。</p>
      ) : null}
    </section>
  );
}
