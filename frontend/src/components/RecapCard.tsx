import { useEffect, useState } from "react";
import styles from "./RecapCard.module.css";

type Props = {
  /** 回述范围（后端给的说明，例如「「第二卷」之前的 3 章」） */
  label: string;
  text: string;
  model: string;
  chaptersUsed: number;
  busy: boolean;
  error: string;
  /** 回述范围：before = 这一卷之前（卷首前情）；volume = 本卷（卷末收束/给 AI 当本卷摘要） */
  scope: "before" | "volume";
  /** 有卷时才显示范围切换 */
  canUseVolumeScope: boolean;
  onScopeChange: (scope: "before" | "volume") => void;
  onRegenerate: () => void;
  onClose: () => void;
  onInsert: (text: string, position: "prepend" | "append") => void;
};

/**
 * 卷首「前情提要」卡片：生成 → 可编辑 → 复制 / 插入本卷第一章。
 *
 * 为什么不自动写入正文：回述是**给读者看的成品**，作者多半要改口气、删剧透，
 * 所以默认只展示，插入由作者点。
 */
export function RecapCard({
  label,
  text,
  model,
  chaptersUsed,
  busy,
  error,
  scope,
  canUseVolumeScope,
  onScopeChange,
  onRegenerate,
  onClose,
  onInsert,
}: Props) {
  const [draft, setDraft] = useState(text);
  const [copied, setCopied] = useState(false);

  useEffect(() => {
    setDraft(text);
    setCopied(false);
  }, [text]);

  const copy = async () => {
    try {
      await navigator.clipboard.writeText(draft);
      setCopied(true);
      window.setTimeout(() => setCopied(false), 1600);
    } catch {
      setCopied(false);
    }
  };

  return (
    <section className={styles.wrap} data-testid="recap-card">
      <div className={styles.head}>
        <strong className={styles.title}>前情提要</strong>
        {canUseVolumeScope ? (
          <span className={styles.scopeSwitch} role="group" aria-label="回述范围">
            <button
              type="button"
              className={scope === "before" ? styles.scopeOn : styles.scope}
              data-testid="recap-scope-before"
              disabled={busy}
              onClick={() => onScopeChange("before")}
              title="回述这一卷之前发生的事（卷首回顾）"
            >
              前情
            </button>
            <button
              type="button"
              className={scope === "volume" ? styles.scopeOn : styles.scope}
              data-testid="recap-scope-volume"
              disabled={busy}
              onClick={() => onScopeChange("volume")}
              title="回述本卷（卷末收束，也可以当成喂给 AI 的本卷摘要）"
            >
              本卷
            </button>
          </span>
        ) : null}
        <span className={styles.hint} data-testid="recap-label">
          {busy ? "正在读前面的章节…" : label || "（未生成）"}
        </span>
        <button
          type="button"
          className={styles.primary}
          data-testid="recap-regenerate"
          disabled={busy}
          onClick={onRegenerate}
          title="重新生成一版（可以多试几次挑一版）"
        >
          {busy ? "生成中…" : "重新生成"}
        </button>
        <button type="button" className={styles.ghost} onClick={onClose} title="收起">
          ⌄
        </button>
      </div>

      {error ? (
        <p className={styles.error} data-testid="recap-error">
          {error}
        </p>
      ) : null}

      {text ? (
        <>
          <textarea
            className={styles.text}
            data-testid="recap-text"
            value={draft}
            rows={Math.min(14, Math.max(5, Math.ceil(draft.length / 40)))}
            onChange={(e) => setDraft(e.target.value)}
          />
          <div className={styles.actions}>
            <button
              type="button"
              className={styles.accept}
              data-testid="recap-insert-prepend"
              onClick={() => onInsert(draft, "prepend")}
              title="插到本卷第一章的开头"
            >
              ⤵ 插到本卷第一章开头
            </button>
            <button
              type="button"
              className={styles.ghost}
              data-testid="recap-insert-append"
              onClick={() => onInsert(draft, "append")}
              title="追加到当前这一章的结尾"
            >
              ⤴ 追加到本章结尾
            </button>
            <button type="button" className={styles.ghost} onClick={() => void copy()}>
              {copied ? "已复制" : "复制"}
            </button>
            <span className={styles.meta}>
              {chaptersUsed ? `依据 ${chaptersUsed} 章` : ""}
              {model ? ` · ${model}` : ""}
            </span>
          </div>
        </>
      ) : null}

      {!text && !busy && !error ? (
        <p className={styles.hint}>点「重新生成」开始；生成的是给读者看的回述，可以直接编辑。</p>
      ) : null}
    </section>
  );
}
