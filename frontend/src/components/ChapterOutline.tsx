import { useEffect, useState } from "react";
import type { SceneChapter, Volume } from "../types/vn";
import { LOOSE_VOLUME_ID, buildVolumeRows, volumeIdOfChapter } from "../lib/volumes";
import { formatWords } from "../lib/wordCount";
import styles from "./ChapterOutline.module.css";

const COLLAPSED_KEY = "vnss-chapter-outline-collapsed";
const NARROW_MQ = "(max-width: 720px)";

type Props = {
  /** vn：默认收起；novel：默认展开。用户手动折叠后仍以 localStorage 为准。 */
  genre?: "vn" | "novel";
  chapterId: string;
  chapters: SceneChapter[];
  volumes: Volume[];
  activeVolumeId: string;
  onSelectChapter: (id: string) => void;
  onAddChapter: () => void;
  onDeleteChapter: () => void;
  onSelectVolume: (volumeId: string) => void;
  onAddVolume: () => void;
  onRenameVolume: (volumeId: string) => void;
  onMoveVolume: (volumeId: string, delta: number) => void;
  onDeleteVolume: (volumeId: string) => void;
  onAssignChapter: (volumeId: string) => void;
  onRecap: () => void;
};

/**
 * 章节大纲：宽屏左侧栏，窄屏折回顶部横条。
 * 卷/章动作与旧 StudioChapterBar 一致，但不含「剧本/分析」页签。
 */
export function ChapterOutline(props: Props) {
  const [narrow, setNarrow] = useState(() =>
    typeof window !== "undefined" ? window.matchMedia(NARROW_MQ).matches : false
  );
  const [collapsed, setCollapsed] = useState(() => {
    try {
      const stored = localStorage.getItem(COLLAPSED_KEY);
      if (stored === "1") return true;
      if (stored === "0") return false;
    } catch {
      /* ignore */
    }
    return props.genre === "vn";
  });

  useEffect(() => {
    const mq = window.matchMedia(NARROW_MQ);
    const onChange = () => setNarrow(mq.matches);
    onChange();
    mq.addEventListener("change", onChange);
    return () => mq.removeEventListener("change", onChange);
  }, []);

  function toggleCollapsed() {
    setCollapsed((prev) => {
      const next = !prev;
      try {
        localStorage.setItem(COLLAPSED_KEY, next ? "1" : "0");
      } catch {
        /* ignore */
      }
      return next;
    });
  }

  if (narrow) {
    return <OutlineStrip {...props} />;
  }

  if (collapsed) {
    return (
      <aside className={styles.railCollapsed} data-testid="chapter-outline">
        <button
          type="button"
          className={styles.expandBtn}
          data-testid="outline-expand"
          onClick={toggleCollapsed}
          title="展开章节大纲"
        >
          大纲 ›
        </button>
      </aside>
    );
  }

  return (
    <aside className={styles.rail} data-testid="chapter-outline" aria-label="章节大纲">
      <div className={styles.railHead}>
        <strong>大纲</strong>
        <button
          type="button"
          className={styles.ghost}
          data-testid="outline-collapse"
          onClick={toggleCollapsed}
          title="收起大纲"
        >
          ‹
        </button>
      </div>
      <OutlineBody {...props} vertical />
    </aside>
  );
}

function OutlineStrip(props: Props) {
  return (
    <div className={styles.strip} data-testid="chapter-outline" data-layout="strip">
      <OutlineBody {...props} vertical={false} />
    </div>
  );
}

function OutlineBody({
  vertical,
  chapterId,
  chapters,
  volumes,
  activeVolumeId,
  onSelectChapter,
  onAddChapter,
  onDeleteChapter,
  onSelectVolume,
  onAddVolume,
  onRenameVolume,
  onMoveVolume,
  onDeleteVolume,
  onAssignChapter,
  onRecap,
}: Props & { vertical: boolean }) {
  const rows = buildVolumeRows(volumes, chapters);
  const hasVolumes = volumes.length > 0;
  const activeRow = hasVolumes
    ? rows.find((r) => r.id === activeVolumeId)
    : undefined;
  const shownChapters = hasVolumes ? activeRow?.chapters ?? [] : chapters;
  const currentVolumeId = volumeIdOfChapter(chapters, chapterId);
  const currentIndex = volumes.findIndex((v) => v.id === activeVolumeId);

  return (
    <div className={vertical ? styles.bodyVert : styles.bodyHoriz}>
      {hasVolumes ? (
        <div className={styles.volumeRow} data-testid="volume-row">
          {rows.map((row) => (
            <button
              key={row.id || "loose"}
              type="button"
              role="option"
              aria-selected={row.id === activeVolumeId}
              className={
                row.id === activeVolumeId ? styles.volumeOn : styles.volume
              }
              data-testid={`volume-chip-${row.id || "loose"}`}
              onClick={() => onSelectVolume(row.id)}
              title={`${row.chapters.length} 章 · ${row.words} 字`}
            >
              <span>{row.title}</span>
              <em>
                {row.chapters.length}章 · {formatWords(row.words)}字
              </em>
            </button>
          ))}
        </div>
      ) : null}

      {hasVolumes && activeVolumeId ? (
        <div className={styles.volumeActions}>
          <button
            type="button"
            className={styles.ghost}
            data-testid="volume-rename"
            onClick={() => onRenameVolume(activeVolumeId)}
          >
            ✎
          </button>
          <button
            type="button"
            className={styles.ghost}
            disabled={currentIndex <= 0}
            onClick={() => onMoveVolume(activeVolumeId, -1)}
          >
            ↑
          </button>
          <button
            type="button"
            className={styles.ghost}
            disabled={currentIndex < 0 || currentIndex >= volumes.length - 1}
            onClick={() => onMoveVolume(activeVolumeId, 1)}
          >
            ↓
          </button>
          <button
            type="button"
            className={styles.ghost}
            data-testid="volume-recap"
            onClick={onRecap}
          >
            前情
          </button>
          <button
            type="button"
            className={styles.ghost}
            data-testid="volume-delete"
            onClick={() => onDeleteVolume(activeVolumeId)}
          >
            删卷
          </button>
        </div>
      ) : null}

      <div
        className={styles.chapterList}
        role="listbox"
        aria-label="篇章"
      >
        {shownChapters.map((c) => {
          const globalIndex = chapters.indexOf(c);
          return (
            <button
              key={c.id}
              type="button"
              role="option"
              aria-selected={c.id === chapterId}
              className={
                c.id === chapterId ? styles.chapterOn : styles.chapter
              }
              data-testid={`chapter-chip-${globalIndex + 1}`}
              onClick={() => onSelectChapter(c.id)}
            >
              <em>{String(globalIndex + 1).padStart(2, "0")}</em>
              <span>{c.title || `第 ${globalIndex + 1} 章`}</span>
            </button>
          );
        })}
        {hasVolumes && shownChapters.length === 0 ? (
          <span className={styles.empty}>这一卷还没有章节</span>
        ) : null}
      </div>

      <div className={styles.footer}>
        {hasVolumes ? (
          <label className={styles.assign}>
            归入
            <select
              data-testid="chapter-volume-select"
              value={currentVolumeId}
              onChange={(e) => onAssignChapter(e.target.value)}
            >
              <option value={LOOSE_VOLUME_ID}>未分卷</option>
              {volumes.map((v) => (
                <option key={v.id} value={v.id}>
                  {v.title}
                </option>
              ))}
            </select>
          </label>
        ) : (
          <button
            type="button"
            className={styles.ghost}
            data-testid="volume-add"
            onClick={onAddVolume}
          >
            + 卷
          </button>
        )}
        {hasVolumes ? (
          <button
            type="button"
            className={styles.ghost}
            data-testid="volume-add"
            onClick={onAddVolume}
          >
            + 卷
          </button>
        ) : (
          <button
            type="button"
            className={styles.ghost}
            data-testid="chapter-recap"
            onClick={onRecap}
          >
            前情
          </button>
        )}
        <button type="button" className={styles.ghost} onClick={onAddChapter}>
          + 章
        </button>
        <button
          type="button"
          className={styles.ghost}
          disabled={chapters.length <= 1}
          onClick={onDeleteChapter}
        >
          删章
        </button>
      </div>
    </div>
  );
}
