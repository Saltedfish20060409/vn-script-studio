import { useMemo, useState } from "react";
import type { FactInboxItem, VnProject } from "../types/vn";
import styles from "./FactExtractReview.module.css";

type Props = {
  items: FactInboxItem[];
  project: VnProject;
  busy?: boolean;
  onConfirm: (ids: string[]) => void;
  onReject?: (ids: string[]) => void;
  onCancel: () => void;
};

function charName(project: VnProject, id: string): string {
  return project.characters.find((c) => c.id === id)?.displayName ?? id;
}

export function FactExtractReview({
  items,
  project,
  busy = false,
  onConfirm,
  onReject,
  onCancel,
}: Props) {
  const links = useMemo(
    () => items.filter((i) => i.kind === "character_link"),
    [items]
  );
  const events = useMemo(
    () => items.filter((i) => i.kind === "timeline_event"),
    [items]
  );

  const [selected, setSelected] = useState<Set<string>>(
    () => new Set(items.map((i) => i.id))
  );

  function toggle(id: string) {
    setSelected((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function selectAll(on: boolean) {
    setSelected(on ? new Set(items.map((i) => i.id)) : new Set());
  }

  return (
    <div className={styles.backdrop} role="presentation" onClick={onCancel}>
      <div
        className={styles.dialog}
        role="dialog"
        aria-modal
        aria-labelledby="fact-extract-review-title"
        onClick={(e) => e.stopPropagation()}
      >
        <header className={styles.head}>
          <p className={styles.stamp}>FACT · REVIEW</p>
          <h2 id="fact-extract-review-title">确认写入分析事实</h2>
          <p className={styles.sub}>
            候选来自剧本 / 圣经 / 角色卡（及粘贴源）。勾选后可接受写入或单独拒绝；「稍后处理」只关对话框，保留托盘。
          </p>
        </header>

        <div className={styles.toolbar}>
          <button type="button" className={styles.ghost} onClick={() => selectAll(true)}>
            全选
          </button>
          <button type="button" className={styles.ghost} onClick={() => selectAll(false)}>
            清空
          </button>
          <span className={styles.count}>
            {selected.size} / {items.length}
          </span>
        </div>

        <div className={styles.cols}>
          <section>
            <h3>角色关系</h3>
            <ul className={styles.list}>
              {links.length === 0 ? (
                <li className={styles.empty}>无关系候选</li>
              ) : (
                links.map((item) => {
                  const fromId = String(item.payload.fromId ?? "");
                  const toId = String(item.payload.toId ?? "");
                  const label = String(item.payload.label ?? "关系");
                  const quote = item.evidence?.[0]?.quote;
                  return (
                    <li key={item.id}>
                      <label className={styles.row}>
                        <input
                          type="checkbox"
                          checked={selected.has(item.id)}
                          onChange={() => toggle(item.id)}
                        />
                        <span>
                          <strong>
                            {charName(project, fromId)} —{label}→{" "}
                            {charName(project, toId)}
                          </strong>
                          {quote ? (
                            <em className={styles.quote}>「{quote}」</em>
                          ) : null}
                        </span>
                      </label>
                    </li>
                  );
                })
              )}
            </ul>
          </section>
          <section>
            <h3>时间线</h3>
            <ul className={styles.list}>
              {events.length === 0 ? (
                <li className={styles.empty}>无时间线候选</li>
              ) : (
                events.map((item) => {
                  const title = String(item.payload.title ?? "节点");
                  const when = item.payload.when
                    ? String(item.payload.when)
                    : "";
                  const quote = item.evidence?.[0]?.quote;
                  return (
                    <li key={item.id}>
                      <label className={styles.row}>
                        <input
                          type="checkbox"
                          checked={selected.has(item.id)}
                          onChange={() => toggle(item.id)}
                        />
                        <span>
                          <strong>{title}</strong>
                          {when ? <span className={styles.meta}>{when}</span> : null}
                          {quote ? (
                            <em className={styles.quote}>「{quote}」</em>
                          ) : null}
                        </span>
                      </label>
                    </li>
                  );
                })
              )}
            </ul>
          </section>
        </div>

        <footer className={styles.foot}>
          <button type="button" className={styles.ghost} onClick={onCancel} disabled={busy}>
            稍后处理
          </button>
          {onReject ? (
            <button
              type="button"
              className={styles.ghost}
              disabled={busy || selected.size === 0}
              onClick={() => onReject([...selected])}
            >
              拒绝所选
            </button>
          ) : null}
          <button
            type="button"
            className={styles.primary}
            disabled={busy || selected.size === 0}
            onClick={() => onConfirm([...selected])}
          >
            {busy ? "写入中…" : `接受 ${selected.size} 条`}
          </button>
        </footer>
      </div>
    </div>
  );
}
