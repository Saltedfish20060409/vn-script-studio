import { useState } from "react";
import { createPortal } from "react-dom";
import styles from "./ChapterReviseModePicker.module.css";
import { FOLLOW_NOTE_MODE, REVISE_MODE_OPTIONS, type ReviseMode } from "../lib/chapterRevisePrefs";

type PickOpts = {
  /** 作者自己写的改法（走「就照我说的改」时带上）。 */
  customNote?: string;
};

type Props = {
  defaultMode?: ReviseMode;
  busy?: boolean;
  onPick: (mode: ReviseMode, opts?: PickOpts) => void;
  onCancel: () => void;
};

/**
 * 改章方向选择（**按需打开**）。
 *
 * 它过去会在每次"改这一章"前自动弹出，逼作者在三选一里挑一个。作者反馈那三种方向
 * "很多时候并不符合我想改的"，弹窗"很多余"——而那三种方向本来就能用话说出来
 * （「只去说明书 / 轻润 / 人味」由 `agentIntent` 认），所以自动弹窗只是多余的一层。
 * 现在只有作者显式说「选个方向」才会打开（见 `agentIntent` 的 `revise_pick`），
 * 平时改章直接照他的话改。
 */
export function ChapterReviseModePicker({
  defaultMode = "human_warmth",
  busy = false,
  onPick,
  onCancel,
}: Props) {
  const [custom, setCustom] = useState("");
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
          平时不用进这里——直接说就行（「轻润一下」「只去说明书」「写得更有人味」都认）。
          你主动打开了这个面板，那就挑一个方向，或者用自己的话写清楚。
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
                onPick(FOLLOW_NOTE_MODE, { customNote: trimmed });
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
              onClick={() => onPick(FOLLOW_NOTE_MODE, { customNote: trimmed })}
            >
              就照我说的改
            </button>
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
              onClick={() => onPick(opt.id)}
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
