import type { SceneChapter, Volume } from "../types/vn";
import { LOOSE_VOLUME_ID, buildVolumeRows, volumeIdOfChapter } from "../lib/volumes";
import { formatWords } from "../lib/wordCount";
import styles from "./StudioApp.module.css";

type WriteSub = "script" | "analysis";

type Props = {
  writeSub: WriteSub;
  chapterId: string;
  chapters: SceneChapter[];
  volumes: Volume[];
  /** 当前查看的卷（"" = 未分卷） */
  activeVolumeId: string;
  onSelectScript: () => void;
  onSelectAnalysis: () => void;
  onSelectChapter: (id: string) => void;
  onAddChapter: () => void;
  onDeleteChapter: () => void;
  onSelectVolume: (volumeId: string) => void;
  onAddVolume: () => void;
  onRenameVolume: (volumeId: string) => void;
  onMoveVolume: (volumeId: string, delta: number) => void;
  onDeleteVolume: (volumeId: string) => void;
  /** 把当前章节移入某卷（"" = 移出到未分卷） */
  onAssignChapter: (volumeId: string) => void;
};

/**
 * Write-tab secondary nav: 剧本 / 分析 switcher plus the chapter strip.
 *
 * 分卷时多一行卷标（含每卷章数与字数），章节条只显示当前卷的章节；不分卷时
 * 与原来完全一样（只有一行章节条），所以老工程的使用习惯不受影响。
 */
export function StudioChapterBar({
  writeSub,
  chapterId,
  chapters,
  volumes,
  activeVolumeId,
  onSelectScript,
  onSelectAnalysis,
  onSelectChapter,
  onAddChapter,
  onDeleteChapter,
  onSelectVolume,
  onAddVolume,
  onRenameVolume,
  onMoveVolume,
  onDeleteVolume,
  onAssignChapter,
}: Props) {
  const rows = buildVolumeRows(volumes, chapters);
  const hasVolumes = volumes.length > 0;
  const activeRow = hasVolumes
    ? rows.find((r) => r.id === activeVolumeId)
    : undefined;
  const shownChapters = hasVolumes
    ? activeRow?.chapters ?? []
    : chapters;
  const currentVolumeId = volumeIdOfChapter(chapters, chapterId);
  const currentIndex = volumes.findIndex((v) => v.id === activeVolumeId);

  return (
    <div className={styles.subNav} style={{ padding: "0.75rem 1.1rem 0" }}>
      <button
        type="button"
        className={writeSub === "script" ? styles.subActive : styles.subTab}
        onClick={onSelectScript}
      >
        剧本
      </button>
      <button
        type="button"
        className={writeSub === "analysis" ? styles.subActive : styles.subTab}
        onClick={onSelectAnalysis}
      >
        分析
      </button>
      <div className={styles.chapterBar}>
        <span className={styles.inlineLabel}>篇章</span>
        {hasVolumes ? (
          <div className={styles.volumeRow} data-testid="volume-row">
            {rows.map((row) => (
              <button
                key={row.id || "loose"}
                type="button"
                role="option"
                aria-selected={row.id === activeVolumeId}
                className={row.id === activeVolumeId ? styles.volumeChipOn : styles.volumeChip}
                data-testid={`volume-chip-${row.id || "loose"}`}
                onClick={() => onSelectVolume(row.id)}
                title={`${row.chapters.length} 章 · ${row.words} 字`}
              >
                <span className={styles.volumeChipTitle}>{row.title}</span>
                <em className={styles.volumeChipMeta}>
                  {row.chapters.length} 章 · {formatWords(row.words)}字
                </em>
              </button>
            ))}
            {activeVolumeId ? (
              <span className={styles.volumeActions}>
                <button
                  type="button"
                  className={styles.ghost}
                  data-testid="volume-rename"
                  onClick={() => onRenameVolume(activeVolumeId)}
                  title="改这一卷的名字"
                >
                  ✎ 改名
                </button>
                <button
                  type="button"
                  className={styles.ghost}
                  disabled={currentIndex <= 0}
                  onClick={() => onMoveVolume(activeVolumeId, -1)}
                  title="这一卷往前挪"
                >
                  ↑
                </button>
                <button
                  type="button"
                  className={styles.ghost}
                  disabled={currentIndex < 0 || currentIndex >= volumes.length - 1}
                  onClick={() => onMoveVolume(activeVolumeId, 1)}
                  title="这一卷往后挪"
                >
                  ↓
                </button>
                <button
                  type="button"
                  className={styles.ghost}
                  data-testid="volume-delete"
                  onClick={() => onDeleteVolume(activeVolumeId)}
                  title="删掉这一卷（里面的章节会回到「未分卷」，不会删章节）"
                >
                  ✕ 删卷
                </button>
              </span>
            ) : null}
            <button
              type="button"
              className={styles.ghost}
              data-testid="volume-add"
              onClick={onAddVolume}
            >
              + 卷
            </button>
          </div>
        ) : null}
        <div className={styles.chapterStrip} role="listbox" aria-label="篇章">
          {shownChapters.map((c) => {
            const globalIndex = chapters.indexOf(c);
            return (
              <button
                key={c.id}
                type="button"
                role="option"
                aria-selected={c.id === chapterId}
                className={c.id === chapterId ? styles.chapterChipOn : styles.chapterChip}
                data-testid={`chapter-chip-${globalIndex + 1}`}
                onClick={() => onSelectChapter(c.id)}
              >
                <em>{String(globalIndex + 1).padStart(2, "0")}</em>
                <span>{c.title || `第 ${globalIndex + 1} 章`}</span>
              </button>
            );
          })}
          {hasVolumes && shownChapters.length === 0 ? (
            <span className={styles.volumeEmpty}>这一卷还没有章节，点「+ 章」新建</span>
          ) : null}
        </div>
        {hasVolumes ? (
          <label className={styles.volumeAssign} title="把当前这一章放进别的卷">
            <span className={styles.inlineLabel}>本章归入</span>
            <select
              className={styles.chapterSelect}
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
            title="长篇按卷连载时把章节分组（轻小说/网文常用）"
          >
            + 卷
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
