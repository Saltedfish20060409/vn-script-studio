import { useEffect, useMemo, useState } from "react";
import { createPortal } from "react-dom";
import {
  buildReviseSegments,
  countRevisedKept,
  mergeReviseSegments,
  type ReviseSegment,
} from "../lib/chapterReviseSegments";
import styles from "./ChapterReviseReview.module.css";

type Props = {
  chapterTitle?: string;
  originalText: string;
  revisedText: string;
  diagnosisMd?: string;
  busy?: boolean;
  onApply: (mergedText: string, meta: { keptOriginal: number; keptRevised: number }) => void;
  onCancel: () => void;
};

export function ChapterReviseReview({
  chapterTitle,
  originalText,
  revisedText,
  diagnosisMd,
  busy = false,
  onApply,
  onCancel,
}: Props) {
  const initial = useMemo(
    () => buildReviseSegments(originalText, revisedText),
    [originalText, revisedText]
  );
  const [segments, setSegments] = useState<ReviseSegment[]>(initial);
  const [showDiag, setShowDiag] = useState(false);
  const counts = countRevisedKept(segments);

  useEffect(() => {
    setSegments(initial);
  }, [initial]);

  function setAll(useRevised: boolean) {
    setSegments((prev) => prev.map((s) => ({ ...s, useRevised })));
  }

  function toggle(id: string) {
    setSegments((prev) =>
      prev.map((s) => (s.id === id ? { ...s, useRevised: !s.useRevised } : s))
    );
  }

  return createPortal(
    <div className={styles.backdrop} role="presentation" onClick={onCancel}>
      <div
        className={styles.dialog}
        role="dialog"
        aria-modal
        aria-labelledby="chapter-revise-review-title"
        onClick={(e) => e.stopPropagation()}
      >
        <header className={styles.head}>
          <p className={styles.stamp}>REVISE · REVIEW</p>
          <h2 id="chapter-revise-review-title">
            对照挑选{chapterTitle ? ` · ${chapterTitle}` : ""}
          </h2>
          <p className={styles.sub}>
            左右是同一位置的修改前 / 修改后。关闭后预览仍会保留，可从写作区「改稿对照」再进。
          </p>
        </header>

        <div className={styles.toolbar}>
          <button type="button" className={styles.ghost} onClick={() => setAll(true)} disabled={busy}>
            全用改稿
          </button>
          <button type="button" className={styles.ghost} onClick={() => setAll(false)} disabled={busy}>
            全用原文
          </button>
          <span className={styles.count}>
            改稿 {counts.keptRevised} · 原文 {counts.keptOriginal}
          </span>
          {diagnosisMd ? (
            <button
              type="button"
              className={styles.ghost}
              onClick={() => setShowDiag((v) => !v)}
            >
              {showDiag ? "收起说明" : "责编说明"}
            </button>
          ) : null}
        </div>

        {showDiag && diagnosisMd ? (
          <pre className={styles.diag}>{diagnosisMd}</pre>
        ) : null}

        <div className={styles.list}>
          {segments.map((s, i) => {
            const changed = s.kind !== "equal";
            const kindLabel =
              s.kind === "added"
                ? "新增"
                : s.kind === "removed"
                  ? "删去"
                  : s.kind === "changed"
                    ? "有改动"
                    : "未改动";
            return (
              <article
                key={s.id}
                className={styles.card}
                data-active={s.useRevised ? "revised" : "original"}
                data-kind={s.kind}
              >
                <header className={styles.cardHead}>
                  <span className={styles.idx}>§{i + 1}</span>
                  <span className={styles.badge}>{kindLabel}</span>
                  {changed ? (
                    <div className={styles.toggle}>
                      <button
                        type="button"
                        className={s.useRevised ? styles.on : styles.off}
                        disabled={busy}
                        onClick={() => toggle(s.id)}
                      >
                        {s.kind === "removed"
                          ? s.useRevised
                            ? "确认删去"
                            : "保留原文"
                          : s.kind === "added"
                            ? s.useRevised
                              ? "保留新增"
                              : "不要这段"
                            : s.useRevised
                              ? "用改稿"
                              : "用原文"}
                      </button>
                    </div>
                  ) : null}
                </header>
                <div className={styles.cols}>
                  <div className={styles.col}>
                    <p className={styles.colLabel}>原文</p>
                    <p className={styles.body}>
                      {s.original || (s.kind === "added" ? "（无对应原文）" : "（空）")}
                    </p>
                  </div>
                  <div className={styles.col}>
                    <p className={styles.colLabel}>改稿</p>
                    <p className={styles.body}>
                      {s.revised || (s.kind === "removed" ? "（已删）" : "（空）")}
                    </p>
                  </div>
                </div>
              </article>
            );
          })}
        </div>

        <footer className={styles.foot}>
          <button type="button" className={styles.ghost} onClick={onCancel} disabled={busy}>
            稍后
          </button>
          <button
            type="button"
            className={styles.primary}
            disabled={busy}
            onClick={() =>
              onApply(mergeReviseSegments(segments), {
                keptOriginal: counts.keptOriginal,
                keptRevised: counts.keptRevised,
              })
            }
          >
            {busy ? "写入中…" : "按挑选写入当前章"}
          </button>
        </footer>
      </div>
    </div>,
    document.body
  );
}
