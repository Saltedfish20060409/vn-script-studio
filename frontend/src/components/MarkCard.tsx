import { useEffect, useState, type ChangeEvent } from "react";
import { QUICK_FEEDBACK, shortQuote, type Mark } from "../lib/marks";
import styles from "./MarkCard.module.css";

type Props = {
  mark: Mark;
  index: number;
  total: number;
  busy: boolean;
  hasStyleMemory: boolean;
  onProcess: () => void;
  onAccept: (edited?: string) => void;
  onReject: () => void;
  onRevert: () => void;
  onClose: () => void;
  onPrev: () => void;
  onNext: () => void;
  onRemove: () => void;
  onInstruction: (value: string) => void;
  onIntent: (intent: "rewrite" | "advice") => void;
  /** 一键反馈：把这句话追加进要求并立刻重做这一处 */
  onQuickFeedback: (label: string) => void;
  /** 换个方向再来一版（多候选） */
  onMoreVariants: () => void;
  /** 跳到正文里这一处（重新选中） */
  onJump: () => void;
};

const STATUS_LABEL: Record<Mark["status"], string> = {
  pending: "待处理",
  suggested: "待决定",
  accepted: "已写入",
  rejected: "已忽略",
  stale: "已失效",
};

/**
 * 贴着所选那一行的标记卡片：处理、看对照、接受/忽略，都在正文旁边发生。
 *
 * 为什么不做成下方列表里的行：长章节里标记在上、面板在下，核对要来回滚。
 * 卡片由 ScriptEditor 定位（跟着编辑器滚动走），这里只管内容。
 */
export function MarkCard({
  mark,
  index,
  total,
  busy,
  hasStyleMemory,
  onProcess,
  onAccept,
  onReject,
  onRevert,
  onClose,
  onPrev,
  onNext,
  onRemove,
  onInstruction,
  onIntent,
  onQuickFeedback,
  onMoreVariants,
  onJump,
}: Props) {
  const [edit, setEdit] = useState(mark.replacement ?? "");
  // 换了标记 / 来了新结果 → 重置可编辑的改写稿
  useEffect(() => {
    setEdit(mark.replacement ?? "");
  }, [mark.id, mark.replacement]);

  const decided = mark.status === "accepted";
  const hasResult = Boolean(mark.replacement || mark.advice);

  return (
    <div className={styles.card} data-testid="mark-card">
      <div className={styles.head}>
        <span className={styles.seq}>
          标记 {index + 1}/{total}
        </span>
        <span className={`${styles.status} ${styles[`s_${mark.status}`]}`}>
          {busy ? "处理中…" : STATUS_LABEL[mark.status]}
        </span>
        {hasStyleMemory && mark.intent === "rewrite" ? (
          <span className={styles.styleTag} title="项目里学过你的文风：改写会尽量贴你自己的腔调">
            按你的文风改
          </span>
        ) : null}
        <span className={styles.spacer} />
        <button type="button" className={styles.icon} onClick={onPrev} title="上一个标记">
          ↑
        </button>
        <button type="button" className={styles.icon} onClick={onNext} title="下一个标记">
          ↓
        </button>
        <button type="button" className={styles.icon} onClick={onJump} title="在正文里重新选中这一处">
          ◎
        </button>
        <button type="button" className={styles.icon} onClick={onRemove} title="删掉这个标记（不改正文）">
          ✕
        </button>
        <button type="button" className={styles.icon} onClick={onClose} title="收起卡片（标记保留）">
          ⌄
        </button>
      </div>

      <p className={styles.quote} data-testid="mark-card-quote">
        {shortQuote(mark.quote, 60)}
      </p>

      {mark.status === "stale" ? (
        <p className={styles.error}>
          正文里已经找不到这一段了（被改过或删掉）。可以删掉这个标记，或先在正文里改回去。
        </p>
      ) : null}

      {mark.error ? <p className={styles.error}>出错了：{mark.error}</p> : null}

      {mark.advice && mark.intent === "advice" ? (
        <p className={styles.advice} data-testid="mark-card-advice">
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
            <span className={styles.diffLabel}>
              改后（可以直接改）
              {(mark.candidates?.length ?? 0) > 1 ? (
                <span className={styles.variantRow} data-testid="mark-card-variants">
                  {mark.candidates!.map((v, i) => (
                    <button
                      key={i}
                      type="button"
                      className={
                        v === edit ? styles.variantOn : styles.variant
                      }
                      data-testid={`mark-card-variant-${i}`}
                      onClick={() => setEdit(v)}
                      title={v.slice(0, 60)}
                    >
                      第 {i + 1} 版
                    </button>
                  ))}
                </span>
              ) : null}
            </span>
            <textarea
              className={styles.diffNew}
              data-testid="mark-card-replacement"
              value={edit}
              rows={Math.min(6, Math.max(2, Math.ceil(edit.length / 52)))}
              onChange={(e: ChangeEvent<HTMLTextAreaElement>) => setEdit(e.target.value)}
            />
          </div>
        </div>
      ) : null}

      {!decided ? (
        <div className={styles.quickRow} data-testid="mark-card-quick">
          {/* 快捷反馈：比打字说一句快，也比聊天更精准（直接进这次改写的指令） */}
          {QUICK_FEEDBACK.map((q) => (
            <button
              key={q.label}
              type="button"
              className={styles.quick}
              data-testid={`mark-card-quick-${q.id}`}
              disabled={busy || mark.status === "stale"}
              onClick={() => onQuickFeedback(q.label)}
              title={`在现有要求后面加上「${q.label}」，重新处理这一处`}
            >
              {q.label}
            </button>
          ))}
        </div>
      ) : null}

      {!decided ? (
        <div className={styles.row}>
          <div className={styles.intentSwitch} role="group" aria-label="标记意图">
            <button
              type="button"
              className={mark.intent === "rewrite" ? styles.intentOn : styles.intent}
              onClick={() => onIntent("rewrite")}
              title="按你的要求改写这一段"
            >
              改
            </button>
            <button
              type="button"
              className={mark.intent === "advice" ? styles.intentOn : styles.intent}
              onClick={() => onIntent("advice")}
              title="只让它指出问题、给建议，不动正文"
            >
              问
            </button>
          </div>
          <input
            className={styles.input}
            data-testid="mark-card-instruction"
            value={mark.instruction}
            placeholder={
              mark.intent === "advice"
                ? "想问什么（可留空）"
                : "要求，例如：更冷一点 / 短一些（可留空）"
            }
            onChange={(e) => onInstruction(e.target.value)}
          />
          <button
            type="button"
            className={styles.primary}
            data-testid="mark-card-process"
            disabled={busy || mark.status === "stale"}
            onClick={onProcess}
          >
            {hasResult ? "重新处理" : "处理"}
          </button>
          {mark.intent === "rewrite" ? (
            <button
              type="button"
              className={styles.ghost}
              data-testid="mark-card-more"
              disabled={busy || mark.status === "stale"}
              onClick={onMoreVariants}
              title="一次给我 3 个不同方向的改写，挑一版"
            >
              给我 3 版
            </button>
          ) : null}
        </div>
      ) : null}

      <div className={styles.actions}>
        {decided ? (
          <button type="button" className={styles.ghost} data-testid="mark-card-revert" onClick={onRevert}>
            ↩ 撤回这次改动
          </button>
        ) : (
          <>
            <button
              type="button"
              className={styles.accept}
              data-testid="mark-card-accept"
              disabled={!mark.replacement || mark.intent === "advice"}
              onClick={() => onAccept(edit)}
              title="写进正文（可随时撤回）"
            >
              ✓ 接受这条
            </button>
            <button
              type="button"
              className={styles.ghost}
              data-testid="mark-card-reject"
              onClick={onReject}
            >
              忽略
            </button>
          </>
        )}
      </div>
    </div>
  );
}
