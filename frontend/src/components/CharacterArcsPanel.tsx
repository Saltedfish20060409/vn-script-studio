import { useMemo } from "react";
import type { VnProject } from "../types/vn";
import { computeCharacterArcs, type CharacterArc } from "../lib/characterArcs";
import styles from "./CharacterArcsPanel.module.css";

const W = 680;
const H = 240;
const PAD = { top: 14, right: 14, bottom: 26, left: 40 };

function chapterLabel(n: number, total: number): string {
  if (total <= 8) return String(n + 1);
  // thin out labels on long novels
  if (total <= 20) return (n + 1) % 2 === 1 ? String(n + 1) : "";
  return (n + 1) % 4 === 1 ? String(n + 1) : "";
}

function ArcChart({ arcs }: { arcs: ReturnType<typeof computeCharacterArcs> }) {
  const { characters, chapters, maxLines } = arcs;
  const visible = characters.filter((c) => c.totalLines > 0);
  if (visible.length === 0 || chapters.length === 0) {
    return (
      <p className={styles.hint}>还没有角色对白数据。写几段对白后再来看看弧线吧。</p>
    );
  }

  const n = chapters.length;
  const innerW = W - PAD.left - PAD.right;
  const innerH = H - PAD.top - PAD.bottom;
  const xAt = (i: number) =>
    PAD.left + (n <= 1 ? innerW / 2 : (i / (n - 1)) * innerW);
  const yAt = (lines: number) =>
    PAD.top + (1 - lines / maxLines) * innerH;

  const gridY = [0, Math.round(maxLines / 2), maxLines];

  return (
    <div className={styles.chartWrap}>
      <svg
        viewBox={`0 0 ${W} ${H}`}
        className={styles.chart}
        role="img"
        aria-label="角色出场热度曲线（各章对白行数）"
        data-testid="arc-chart"
      >
        {/* grid */}
        {gridY.map((g) => (
          <g key={g}>
            <line
              x1={PAD.left}
              x2={W - PAD.right}
              y1={yAt(g)}
              y2={yAt(g)}
              className={styles.gridLine}
            />
            <text x={PAD.left - 6} y={yAt(g) + 3} className={styles.axisText} textAnchor="end">
              {g}
            </text>
          </g>
        ))}
        {/* chapter ticks */}
        {chapters.map((ch, i) => {
          const label = chapterLabel(i, n);
          return (
            <g key={ch.id}>
              <line
                x1={xAt(i)}
                x2={xAt(i)}
                y1={H - PAD.bottom}
                y2={H - PAD.bottom + 4}
                className={styles.axisTick}
              />
              {label ? (
                <text
                  x={xAt(i)}
                  y={H - PAD.bottom + 16}
                  className={styles.axisText}
                  textAnchor="middle"
                >
                  {label}
                </text>
              ) : null}
            </g>
          );
        })}
        {/* per-character polylines */}
        {visible.map((c) => {
          const points = c.chapterSeries
            .map((p, i) => `${xAt(i)},${yAt(p.lines)}`)
            .join(" ");
          return (
            <polyline
              key={c.id}
              points={points}
              fill="none"
              stroke={c.color}
              strokeWidth={2}
              strokeLinejoin="round"
              strokeLinecap="round"
              opacity={0.9}
            />
          );
        })}
      </svg>
      {/* legend */}
      <ul className={styles.legend}>
        {visible.map((c) => (
          <li key={c.id}>
            <span className={styles.swatch} style={{ background: c.color }} />
            {c.displayName}
            <span className={styles.legendCount}>{c.totalLines} 行</span>
          </li>
        ))}
      </ul>
    </div>
  );
}

function ArcCard({ arc }: { arc: CharacterArc }) {
  const firstLabel =
    arc.firstSeenIndex >= 0 ? String(arc.firstSeenIndex + 1) : "—";
  const lastLabel = arc.lastSeenIndex >= 0 ? String(arc.lastSeenIndex + 1) : "—";
  return (
    <li className={styles.card}>
      <header className={styles.cardHead}>
        <span className={styles.swatch} style={{ background: arc.color }} />
        <strong>{arc.displayName}</strong>
        <span className={styles.cardMeta}>
          {arc.totalLines} 行 · {arc.activeChapters} 章活跃
        </span>
      </header>
      <dl className={styles.cardGrid}>
        <div>
          <dt>首次出场</dt>
          <dd>第 {firstLabel} 章</dd>
        </div>
        <div>
          <dt>最后出场</dt>
          <dd>第 {lastLabel} 章</dd>
        </div>
        <div>
          <dt>最长断层</dt>
          <dd>{arc.gapChapters} 章</dd>
        </div>
      </dl>
      {arc.timelineEvents.length > 0 && (
        <ul className={styles.events}>
          {arc.timelineEvents.map((e, i) => (
            <li key={`${e.title}-${i}`}>
              {e.when ? <em>{e.when}</em> : null}
              {e.title}
            </li>
          ))}
        </ul>
      )}
    </li>
  );
}

export function CharacterArcsPanel({ project }: { project: VnProject }) {
  const arcs = useMemo(() => computeCharacterArcs(project), [project]);
  return (
    <div className={styles.wrap}>
      <ArcChart arcs={arcs} />
      <ul className={styles.cards}>
        {arcs.characters.map((c) => (
          <ArcCard key={c.id} arc={c} />
        ))}
      </ul>
    </div>
  );
}
