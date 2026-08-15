import type { SceneChapter } from "../types/vn";
import styles from "./StudioApp.module.css";

type WriteSub = "script" | "analysis";

type Props = {
  writeSub: WriteSub;
  chapterId: string;
  chapters: SceneChapter[];
  onSelectScript: () => void;
  onSelectAnalysis: () => void;
  onSelectChapter: (id: string) => void;
  onAddChapter: () => void;
  onDeleteChapter: () => void;
};

/**
 * Write-tab secondary nav: 剧本 / 分析 switcher plus the chapter chip strip
 * (+ 章 / 删章). Pure presentational — commit/save logic stays in StudioApp.
 */
export function StudioChapterBar({
  writeSub,
  chapterId,
  chapters,
  onSelectScript,
  onSelectAnalysis,
  onSelectChapter,
  onAddChapter,
  onDeleteChapter,
}: Props) {
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
        <div
          className={styles.chapterStrip}
          role="listbox"
          aria-label="篇章"
        >
          {chapters.map((c, i) => (
            <button
              key={c.id}
              type="button"
              role="option"
              aria-selected={c.id === chapterId}
              className={
                c.id === chapterId
                  ? styles.chapterChipOn
                  : styles.chapterChip
              }
              onClick={() => onSelectChapter(c.id)}
            >
              <em>{String(i + 1).padStart(2, "0")}</em>
              <span>{c.title || `第 ${i + 1} 章`}</span>
            </button>
          ))}
        </div>
        <button
          type="button"
          className={styles.ghost}
          onClick={onAddChapter}
        >
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
