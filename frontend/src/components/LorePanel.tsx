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
  // Manual card form (no Moegirl dependency)
  const [manualTerm, setManualTerm] = useState("");
  const [manualDo, setManualDo] = useState("");
  const [manualDont, setManualDont] = useState("");
  const [manualBeats, setManualBeats] = useState("");

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
      if (!res.moegirlEnabled) setError("萌百搜索暂未启用：现在不能在线查词，但仍可手动添加参考卡。");
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

  const saveManual = useCallback(async () => {
    const t = manualTerm.trim();
    if (!t || busy) return;
    setBusy("manual");
    setError("");
    try {
      await loreSaveCard(projectId, {
        term: t,
        kind: "term",
        do: manualDo.split("\n").map((x) => x.trim()).filter(Boolean),
        dont: manualDont.split("\n").map((x) => x.trim()).filter(Boolean),
        vn_beats: manualBeats.split("\n").map((x) => x.trim()).filter(Boolean),
      });
      setManualTerm("");
      setManualDo("");
      setManualDont("");
      setManualBeats("");
      await refresh();
    } catch (e) {
      setError(String((e as { message?: unknown } | null)?.message ?? e));
    } finally {
      setBusy("");
    }
  }, [projectId, busy, manualTerm, manualDo, manualDont, manualBeats, refresh]);

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
        <h2>写作参考卡</h2>
        <p className={styles.sub}>
          收藏的参考卡会在 <strong>AI 写作时作为参考</strong>
          （教它这类套路具体怎么落地、什么写法要避免）。可手动添加，也可从萌百（萌娘百科）搜索词条、精炼后收藏。
          {meta && !meta.moegirlEnabled && "（萌百搜索暂未启用，只能用离线条目和手动添加）"}
        </p>
      </header>

      {error && <p className={styles.error}>{error}</p>}

      <details className={styles.checklist}>
        <summary>手动添加参考卡（不依赖萌百）</summary>
        <div className={styles.manualForm}>
          <input
            className={styles.input}
            value={manualTerm}
            onChange={(e) => setManualTerm(e.target.value)}
            placeholder="参考条目，如：傲娇、病娇、修罗场、放学后的屋顶"
          />
          <textarea
            rows={2}
            value={manualDo}
            onChange={(e) => setManualDo(e.target.value)}
            placeholder="要这样做（每行一条）：如「用动作/失言暴露在意，不让角色直接说」"
          />
          <textarea
            rows={2}
            value={manualDont}
            onChange={(e) => setManualDont(e.target.value)}
            placeholder="不要这样做（每行一条）：如「标签念经、告白太顺」"
          />
          <textarea
            rows={2}
            value={manualBeats}
            onChange={(e) => setManualBeats(e.target.value)}
            placeholder="可演节拍（每行一条，可选）：如「误会半揭 → 别扭关心 → 旁人点破」"
          />
          <button
            type="button"
            className={styles.primary}
            disabled={busy !== "" || !manualTerm.trim()}
            onClick={() => void saveManual()}
          >
            {busy === "manual" ? "保存中…" : "添加到本作"}
          </button>
        </div>
      </details>

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
          {busy === "inspire" ? "生成中…" : "查看 AI 会参考哪些卡"}
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
          <h4>当前 AI 写作时会参考的设定卡</h4>
          <pre>{inspireBlock}</pre>
        </div>
      )}

      <div className={styles.saved}>
        <h3>本作参考卡（{cards.length}）· AI 写作时会带上这些卡作参考</h3>
        {grouped.length === 0 && (
          <p className={styles.empty}>
            暂无参考卡；可手动添加，或搜索萌百后「收藏到本作」。
          </p>
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
