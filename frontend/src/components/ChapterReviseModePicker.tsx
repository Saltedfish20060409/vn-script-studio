import { useState } from "react";
import { createPortal } from "react-dom";
import styles from "./ChapterReviseModePicker.module.css";
import { FOLLOW_NOTE_MODE, REVISE_MODE_OPTIONS, type ReviseMode } from "../lib/chapterRevisePrefs";

type PickOpts = {
  /** 作者自己写的改法（走「就照我说的改」时带上）。 */
  customNote?: string;
  /** 勾了「以后直接照我说的改」→ 记住，下次不再问。 */
  rememberNoAsk?: boolean;
};

type Props = {
  defaultMode?: ReviseMode;
  busy?: boolean;
  onPick: (mode: ReviseMode, opts?: PickOpts) => void;
  onCancel: () => void;
};

/**
 * 改章方向选择。
 *
 * 为什么长这样：原先只有三张固定方向的卡片（只去说明书 / 加强人味 / 轻润不改结构），
 * 而实测反馈是"那三种很多时候并不符合我想改的，更多时候看 Agent 理解"。所以把**用自己的
 * 话说**提成主路径（输入框 + 主按钮），三张卡片降为分隔线下的备选；
 * 并且给了「以后直接照我说的改」——勾上就不再每次都拦你一下。
 */
export function ChapterReviseModePicker({
  defaultMode = "human_warmth",
  busy = false,
  onPick,
  onCancel,
}: Props) {
  const [custom, setCustom] = useState("");
  const [noAsk, setNoAsk] = useState(false);
  const trimmed = custom.trim();

  return createPortal(
    <div className={styles.backdrop} role="presentation" onClick={onCancel}>
      <div
        className={styles.dialog}
        role="dialog"
        aria-modal
        aria-labelledby="revise-mode-title"
        onClick={(e) => e.stopPropagation()}
      >
        <p className={styles.stamp}>REVISE · MODE</p>
        <h2 id="revise-mode-title">这次想怎么改？</h2>
        <p className={styles.sub}>
          直接用你自己的话说最准（例如「把后面那段展开重写，别动前面的雨夜戏」）。
          下面三个固定方向只是不想细说时的省事选项。
        </p>

        <div className={styles.custom}>
          <textarea
            className={styles.customInput}
            value={custom}
            disabled={busy}
            data-testid="revise-custom-note"
            placeholder="想怎么改？用平常话说就行——说要动哪一段、动成什么样、哪些别碰。"
            onChange={(e) => setCustom(e.target.value)}
            onKeyDown={(e) => {
              // Ctrl/Cmd+Enter 提交，跟聊天框的习惯一致
              if ((e.ctrlKey || e.metaKey) && e.key === "Enter" && trimmed && !busy) {
                e.preventDefault();
                onPick(FOLLOW_NOTE_MODE, {
                  customNote: trimmed,
                  rememberNoAsk: noAsk,
                });
              }
            }}
          />
          <div className={styles.customActions}>
            <button
              type="button"
              className={styles.customGo}
              disabled={busy || !trimmed}
              data-testid="revise-custom-go"
              title={trimmed ? undefined : "写一句再点，或者从下面选一个固定方向"}
              onClick={() =>
                onPick(FOLLOW_NOTE_MODE, {
                  customNote: trimmed,
                  rememberNoAsk: noAsk,
                })
              }
            >
              就照我说的改
            </button>
            <label className={styles.noAsk}>
              <input
                type="checkbox"
                checked={noAsk}
                disabled={busy}
                onChange={(e) => setNoAsk(e.target.checked)}
              />
              以后直接照我说的改，不再问
            </label>
          </div>
        </div>

        <p className={styles.divider}>或者选一个固定方向</p>

        <div className={styles.grid}>
          {REVISE_MODE_OPTIONS.map((opt) => (
            <button
              key={opt.id}
              type="button"
              className={styles.card}
              data-default={opt.id === defaultMode ? "1" : undefined}
              disabled={busy}
              onClick={() => onPick(opt.id, { rememberNoAsk: noAsk })}
            >
              <span className={styles.title}>{opt.title}</span>
              <span className={styles.blurb}>{opt.blurb}</span>
            </button>
          ))}
        </div>
        <button
          type="button"
          className={styles.cancel}
          onClick={onCancel}
          disabled={busy}
        >
          取消
        </button>
      </div>
    </div>,
    document.body
  );
}
