import { useCallback, useEffect, useMemo, useState } from "react";
import {
  loreChecklist,
  loreDeleteCard,
  loreInspire,
  loreListCards,
  loreLookup,
  loreMeta,
  loreSaveCard,
  loreSearch,
  type LoreCard,
} from "../api/client";
import styles from "./LorePanel.module.css";

type Props = {
  projectId: string;
};

const KIND_LABELS: Record<string, string> = {
  moe_attribute: "萌属性",
  genre: "题材",
  trope: "套路/桥段",
  term: "术语",
};

export function LorePanel({ projectId }: Props) {
  const [meta, setMeta] = useState<{
    moegirlEnabled: boolean;
    attribution: string;
  } | null>(null);
  const [cards, setCards] = useState<LoreCard[]>([]);
  const [checklist, setChecklist] = useState<LoreCard[]>([]);
  const [term, setTerm] = useState("");
  const [hits, setHits] = useState<Array<{ title: string; snippet?: string }>>([]);
  const [lookupCard, setLookupCard] = useState<LoreCard | null>(null);
  const [busy, setBusy] = useState("");
  const [error, setError] = useState("");
  const [inspireBlock, setInspireBlock] = useState("");

  const refresh = useCallback(async () => {
    const [m, c, chk] = await Promise.all([
      loreMeta(projectId),
      loreListCards(projectId),
      loreChecklist(projectId),
    ]);
    setMeta(m);
    setCards(c.cards || []);
    setChecklist(chk.cards || []);
  }, [projectId]);

  useEffect(() => {
    void refresh().catch((e) =>
      setError(String((e as { message?: unknown } | null)?.message ?? e))
    );
  }, [refresh]);

  const doSearch = useCallback(async () => {
    const t = term.trim();
    if (!t) return;
    setBusy("search");
    setError("");
    setLookupCard(null);
    try {
      const res = await loreSearch(projectId, t);
      if (!res.moegirlEnabled) setError("萌百未启用（MOEGIRL_ENABLED=false）");
      setHits(res.hits || []);
    } catch (e) {
      setError(String((e as { message?: unknown } | null)?.message ?? e));
    } finally {
      setBusy("");
    }
  }, [projectId, term]);

  const doLookup = useCallback(
    async (title: string) => {
      setBusy("lookup");
      setError("");
      try {
        const res = await loreLookup(projectId, title);
        setLookupCard(res.card ?? null);
        if (!res.card) setError("未找到该术语的精炼卡");
      } catch (e) {
        setError(String((e as { message?: unknown } | null)?.message ?? e));
      } finally {
        setBusy("");
      }
    },
    [projectId]
  );

  const saveCard = useCallback(
    async (card: LoreCard) => {
      setBusy("save");
      setError("");
      try {
        await loreSaveCard(projectId, card);
        await refresh();
      } catch (e) {
        setError(String((e as { message?: unknown } | null)?.message ?? e));
      } finally {
        setBusy("");
      }
    },
    [projectId, refresh]
  );

  const removeCard = useCallback(
    async (cardId: string) => {
      setBusy("del");
      setError("");
      try {
        await loreDeleteCard(projectId, cardId);
        await refresh();
      } catch (e) {
        setError(String((e as { message?: unknown } | null)?.message ?? e));
      } finally {
        setBusy("");
      }
    },
    [projectId, refresh]
  );

  const doInspire = useCallback(async () => {
    setBusy("inspire");
    setError("");
    try {
      const res = await loreInspire(projectId, "", undefined, 6);
      setInspireBlock(res.agentBlock || res.cards.map((c) => c.term).join("、"));
    } catch (e) {
      setError(String((e as { message?: unknown } | null)?.message ?? e));
    } finally {
      setBusy("");
    }
  }, [projectId]);

  const grouped = useMemo(() => {
    const m = new Map<string, LoreCard[]>();
    for (const c of cards) {
      const k = KIND_LABELS[c.kind] || c.kind || "术语";
      m.set(k, [...(m.get(k) || []), c]);
    }
    return [...m.entries()];
  }, [cards]);

  const lookupSaved = useMemo(
    () => cards.some((c) => c.term === lookupCard?.term),
    [cards, lookupCard]
  );

  return (
    <section className={styles.panel}>
      <header className={styles.head}>
        <h2>设定卡 · 工艺速查</h2>
        <p className={styles.sub}>
          {meta?.attribution ||
            "萌百启发精炼卡（非原文库）；用于写作时注入 Agent 上下文。"}
          {meta && !meta.moegirlEnabled && "（萌百未启用，仅离线种子与已存卡）"}
        </p>
      </header>

      {error && <p className={styles.error}>{error}</p>}

      <div className={styles.searchRow}>
        <input
          value={term}
          onChange={(e) => setTerm(e.target.value)}
          onKeyDown={(e) => {
            if (e.key === "Enter") void doSearch();
          }}
          placeholder="搜索萌百 / 查工艺术语，如：傲娇、病娇、修罗场"
          className={styles.input}
        />
        <button
          type="button"
          className={styles.primary}
          disabled={busy !== ""}
          onClick={() => void doSearch()}
        >
          {busy === "search" ? "搜索中…" : "搜索"}
        </button>
        <button
          type="button"
          className={styles.ghost}
          disabled={busy !== ""}
          onClick={() => void doInspire()}
        >
          {busy === "inspire" ? "生成中…" : "灵感抽查"}
        </button>
      </div>

      {hits.length > 0 && (
        <div className={styles.hits}>
          {hits.map((h) => (
            <button
              key={h.title}
              type="button"
              className={styles.hit}
              disabled={busy !== ""}
              onClick={() => void doLookup(h.title)}
            >
              <strong>{h.title}</strong>
              {h.snippet && <span className={styles.hitSnippet}>{h.snippet}</span>}
            </button>
          ))}
        </div>
      )}

      {lookupCard && (
        <article className={styles.card}>
          <h3>
            {lookupCard.term}{" "}
            <span className={styles.kind}>
              {KIND_LABELS[lookupCard.kind] || lookupCard.kind}
            </span>
          </h3>
          {lookupCard.definition_short && (
            <p className={styles.definition}>{lookupCard.definition_short}</p>
          )}
          {(lookupCard.do || []).length > 0 && (
            <div className={styles.lists}>
              <div>
                <strong>要做</strong>
                <ul>
                  {lookupCard.do!.map((x, i) => (
                    <li key={i}>{x}</li>
                  ))}
                </ul>
              </div>
              <div>
                <strong>别做</strong>
                <ul>
                  {lookupCard.dont!.map((x, i) => (
                    <li key={i}>{x}</li>
                  ))}
                </ul>
              </div>
            </div>
          )}
          {(lookupCard.vn_beats || []).length > 0 && (
            <details>
              <summary>VN 节拍</summary>
              <ul>
                {lookupCard.vn_beats!.map((x, i) => (
                  <li key={i}>{x}</li>
                ))}
              </ul>
            </details>
          )}
          <footer className={styles.cardFoot}>
            {lookupCard.source_url && (
              <a
                href={lookupCard.source_url}
                target="_blank"
                rel="noreferrer"
                className={styles.src}
              >
                来源
              </a>
            )}
            <button
              type="button"
              className={styles.primary}
              disabled={busy !== "" || lookupSaved}
              onClick={() => void saveCard(lookupCard!)}
            >
              {lookupSaved
                ? "已收藏到本作"
                : busy === "save"
                  ? "保存中…"
                  : "收藏到本作"}
            </button>
          </footer>
        </article>
      )}

      {inspireBlock && (
        <div className={styles.inspire}>
          <h4>当前 Agent 会看到的设定卡</h4>
          <pre>{inspireBlock}</pre>
        </div>
      )}

      <div className={styles.saved}>
        <h3>本作已收藏（{cards.length}）</h3>
        {grouped.length === 0 && (
          <p className={styles.empty}>暂无收藏卡；搜索后点「收藏到本作」。</p>
        )}
        {grouped.map(([kind, list]) => (
          <div key={kind} className={styles.group}>
            <h4>{kind}</h4>
            <ul>
              {list.map((c) => (
                <li key={c.id} className={styles.savedRow}>
                  <span className={styles.savedTerm}>{c.term}</span>
                  <button
                    type="button"
                    className={styles.ghost}
                    onClick={() => void removeCard(c.id)}
                  >
                    移除
                  </button>
                </li>
              ))}
            </ul>
          </div>
        ))}
      </div>

      {checklist.length > 0 && (
        <details className={styles.checklist}>
          <summary>灵感清单（{checklist.length}）</summary>
          <ul>
            {checklist.map((c) => (
              <li key={c.term}>
                <strong>{c.term}</strong>
                {c.definition_short && (
                  <span> — {c.definition_short.slice(0, 80)}</span>
                )}
              </li>
            ))}
          </ul>
        </details>
      )}
    </section>
  );
}
