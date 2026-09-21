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
  const lore = useMemo(
    () => items.filter((i) => i.kind === "lore_entry"),
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
          <h2 id="fact-extract-review-title">确认加入关系与时间线</h2>
          <p className={styles.sub}>
            候选来自剧本、作品设定和角色卡（及你粘贴的内容）。勾选后点「接受」才会把条目
            加进角色关系、时间线与设定条目（只加资料，不改正文）；AI 不会直接改动你的设定库。
            「稍后处理」只关弹窗，候选仍保留，可稍后再看。
          </p>
        </header>

        <div className={styles.toolbar}>
          <button
            type="button"
            className={styles.ghost}
            onClick={() => selectAll(true)}
          >
            全选
          </button>
          <button
            type="button"
            className={styles.ghost}
            onClick={() => selectAll(false)}
          >
            清空
          </button>
          <span className={styles.count}>
            {selected.size} / {items.length}
          </span>
        </div>

        <div className={styles.cols}>
          {/* 设定条目单独一段：AI 只能提议，你勾了才进设定库 */}
          {lore.length > 0 ? (
            <section data-testid="fact-review-lore">
              <h3>设定条目（AI 提议，接受后才进设定库）</h3>
              <ul className={styles.list}>
                {lore.map((item) => {
                  const title = String(item.payload.title ?? "（无标题）");
                  const body = String(item.payload.body ?? "");
                  const kw = Array.isArray(item.payload.keywords)
                    ? (item.payload.keywords as unknown[]).map(String)
                    : [];
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
                          {kw.length ? (
                            <span className={styles.meta}>触发词：{kw.join("、")}</span>
                          ) : (
                            <span className={styles.meta}>
                              没有触发词（以后要按别名叫它，建议补一个）
                            </span>
                          )}
                          {body ? (
                            <span className={styles.meta}>
                              {body.slice(0, 120)}
                              {body.length > 120 ? "…" : ""}
                            </span>
                          ) : null}
                          {quote ? <em className={styles.quote}>「{quote}」</em> : null}
                        </span>
                      </label>
                    </li>
                  );
                })}
              </ul>
            </section>
          ) : null}
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
                          {quote ? <em className={styles.quote}>「{quote}」</em> : null}
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
                  const when = item.payload.when ? String(item.payload.when) : "";
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
                          {quote ? <em className={styles.quote}>「{quote}」</em> : null}
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
          <button
            type="button"
            className={styles.ghost}
            onClick={onCancel}
            disabled={busy}
          >
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
            {busy ? "处理中…" : `接受所选 ${selected.size} 条`}
          </button>
        </footer>
      </div>
    </div>
  );
}
