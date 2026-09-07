import { useMemo, useState } from "react";
import type { MapExtractProposal } from "../api/client";
import type { Location, LocationLink } from "../types/vn";
import styles from "./MapExtractReview.module.css";

type Props = {
  proposal: MapExtractProposal;
  warnings?: string[];
  modeLabel?: string;
  busy?: boolean;
  onConfirm: (placeIds: string[], linkIds: string[]) => void;
  onCancel: () => void;
};

export function MapExtractReview({
  proposal,
  warnings,
  modeLabel,
  busy = false,
  onConfirm,
  onCancel,
}: Props) {
  const places = useMemo(() => {
    const byId = new Map((proposal.locations || []).map((l) => [l.id, l] as const));
    return (proposal.newPlaceIds || [])
      .map((id) => byId.get(id))
      .filter((l): l is Location => Boolean(l));
  }, [proposal]);

  const links = useMemo(() => {
    const byId = new Map((proposal.locationLinks || []).map((l) => [l.id, l] as const));
    const locName = new Map(
      (proposal.locations || []).map((l) => [l.id, l.name] as const)
    );
    return (proposal.newLinkIds || [])
      .map((id) => byId.get(id))
      .filter((l): l is LocationLink => Boolean(l))
      .map((l) => ({
        link: l,
        label: `${locName.get(l.fromId) ?? "?"} — ${locName.get(l.toId) ?? "?"}`,
      }));
  }, [proposal]);

  const [placeIds, setPlaceIds] = useState<Set<string>>(
    () => new Set(proposal.newPlaceIds || [])
  );
  const [linkIds, setLinkIds] = useState<Set<string>>(
    () => new Set(proposal.newLinkIds || [])
  );

  function togglePlace(id: string) {
    setPlaceIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function toggleLink(id: string) {
    setLinkIds((prev) => {
      const next = new Set(prev);
      if (next.has(id)) next.delete(id);
      else next.add(id);
      return next;
    });
  }

  function selectAll(on: boolean) {
    setPlaceIds(on ? new Set(proposal.newPlaceIds || []) : new Set());
    setLinkIds(on ? new Set(proposal.newLinkIds || []) : new Set());
  }

  const selectedCount = placeIds.size + linkIds.size;

  return (
    <div className={styles.backdrop} role="presentation" onClick={onCancel}>
      <div
        className={styles.dialog}
        role="dialog"
        aria-modal
        aria-labelledby="map-extract-review-title"
        onClick={(e) => e.stopPropagation()}
      >
        <header className={styles.head}>
          <p className={styles.stamp}>MAP · REVIEW</p>
          <h2 id="map-extract-review-title">确认加入地图</h2>
          <p className={styles.sub}>
            {modeLabel ? `${modeLabel} · ` : ""}
            勾选要新增的地点与通路（只加地图，不改正文）；已经放在地图上的地点不会被移动。
          </p>
        </header>

        <div className={styles.toolbar}>
          <button
            type="button"
            className={styles.ghost}
            onClick={() => selectAll(true)}
            disabled={busy}
          >
            全选
          </button>
          <button
            type="button"
            className={styles.ghost}
            onClick={() => selectAll(false)}
            disabled={busy}
          >
            全不选
          </button>
          <span className={styles.count}>
            已选 {selectedCount} / {places.length + links.length}
          </span>
        </div>

        <div className={styles.cols}>
          <section>
            <p className={styles.label}>新地点 · {places.length}</p>
            {places.length === 0 ? (
              <p className={styles.empty}>没有新地点</p>
            ) : (
              <ul className={styles.list}>
                {places.map((p) => (
                  <li key={p.id}>
                    <label className={styles.row}>
                      <input
                        type="checkbox"
                        checked={placeIds.has(p.id)}
                        onChange={() => togglePlace(p.id)}
                        disabled={busy}
                      />
                      <span>
                        <strong>{p.name}</strong>
                        <em>{p.imageTag || p.elementKind || "地点"}</em>
                      </span>
                    </label>
                  </li>
                ))}
              </ul>
            )}
          </section>
          <section>
            <p className={styles.label}>新通路 · {links.length}</p>
            {links.length === 0 ? (
              <p className={styles.empty}>没有新通路</p>
            ) : (
              <ul className={styles.list}>
                {links.map(({ link, label }) => (
                  <li key={link.id}>
                    <label className={styles.row}>
                      <input
                        type="checkbox"
                        checked={linkIds.has(link.id)}
                        onChange={() => toggleLink(link.id)}
                        disabled={busy}
                      />
                      <span>
                        <strong>{label}</strong>
                      </span>
                    </label>
                  </li>
                ))}
              </ul>
            )}
          </section>
        </div>

        {warnings && warnings.length > 0 ? (
          <p className={styles.warn}>{warnings[0]}</p>
        ) : null}

        <footer className={styles.foot}>
          <button
            type="button"
            className={styles.ghost}
            onClick={onCancel}
            disabled={busy}
          >
            取消
          </button>
          <button
            type="button"
            className={styles.primary}
            disabled={busy}
            onClick={() => onConfirm([...placeIds], [...linkIds])}
          >
            {busy ? "写入中…" : selectedCount === 0 ? "不写入任何项" : "确认写入"}
          </button>
        </footer>
      </div>
    </div>
  );
}
