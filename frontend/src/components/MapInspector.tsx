import { MAP_LINE_STYLE_LABELS } from "../types/vn";
import type { CustomMapElementDef, Location, LocationLink } from "../types/vn";
import { primaryEvidence } from "../lib/mapOccurrences";
import type { LocationChapterOccurrence } from "../lib/mapOccurrences";
import { resolvePin } from "../lib/mapWorld";
import { MapPinGlyph } from "./MapPinGlyph";
import styles from "./MapStudio.module.css";

type Props = {
  selectedIds: string[];
  /** Single selected location, or null when nothing / multiple are selected */
  selected: Location | null;
  customElements: CustomMapElementDef[];
  occurrences: LocationChapterOccurrence[];
  links: LocationLink[];
  nameOf: (id: string) => string;
  onPatchSelected: (patch: Partial<Location>) => void;
  onDeleteSelected: () => void;
  onJumpToChapter?: (chapterId: string, blockIndex?: number) => void;
  onRemoveLink: (id: string) => void;
};

/** Right rail: single-location inspector, script occurrences and link list. Pure presentational. */
export function MapInspector({
  selectedIds,
  selected,
  customElements,
  occurrences,
  links,
  nameOf,
  onPatchSelected,
  onDeleteSelected,
  onJumpToChapter,
  onRemoveLink,
}: Props) {
  return (
    <aside className={styles.right}>
      <p className={styles.label}>NODE · 属性</p>
      {selectedIds.length > 1 ? (
        <div className={styles.inspector}>
          <p className={styles.empty}>已选 {selectedIds.length} 个地点</p>
          <button
            type="button"
            className={styles.danger}
            onClick={onDeleteSelected}
          >
            删除全部选中
          </button>
        </div>
      ) : !selected ? (
        <p className={styles.empty}>选中地点章钉以编辑属性</p>
      ) : (
        <div className={styles.inspector}>
          <label>
            名称
            <input
              value={selected.name}
              onChange={(e) => onPatchSelected({ name: e.target.value })}
            />
          </label>
          <div className={styles.inspectorPin}>
            <MapPinGlyph
              kind={resolvePin(selected, customElements).glyph}
              color={selected.color ?? resolvePin(selected, customElements).color}
              size="sm"
              active
            />
            <label>
              章钉色
              <input
                type="color"
                value={selected.color ?? "#002fa7"}
                onChange={(e) => onPatchSelected({ color: e.target.value })}
              />
            </label>
          </div>
          <label>
            scene 标签
            <input
              value={selected.imageTag ?? ""}
              onChange={(e) => onPatchSelected({ imageTag: e.target.value })}
              placeholder="bg station_night"
            />
          </label>
          <label>
            描述
            <textarea
              rows={3}
              value={selected.description ?? ""}
              onChange={(e) =>
                onPatchSelected({ description: e.target.value })
              }
            />
          </label>
          <label>
            缩放 {Math.round((selected.scale ?? 1) * 100)}%
            <input
              type="range"
              min={0.6}
              max={1.8}
              step={0.05}
              value={selected.scale ?? 1}
              onChange={(e) =>
                onPatchSelected({ scale: Number(e.target.value) })
              }
            />
          </label>
          <label>
            旋转 {Math.round(selected.rotation ?? 0)}°
            <input
              type="range"
              min={-45}
              max={45}
              step={1}
              value={selected.rotation ?? 0}
              onChange={(e) =>
                onPatchSelected({ rotation: Number(e.target.value) })
              }
            />
          </label>
          <button
            type="button"
            className={styles.danger}
            onClick={onDeleteSelected}
          >
            删除此地点
          </button>
        </div>
      )}

      <p className={styles.label}>SCENE · 出现</p>
      {selectedIds.length > 1 ? (
        <p className={styles.empty}>选中单个地点以查看出现章节</p>
      ) : !selected ? (
        <p className={styles.empty}>选中地点章钉以查看剧本出现</p>
      ) : occurrences.length === 0 ? (
        <p className={styles.empty}>
          剧本中暂无匹配。检查 scene 标签，或地名是否出现在对白/旁白中。
        </p>
      ) : (
        <ul className={styles.occList}>
          {occurrences.map((occ) => {
            const primary = primaryEvidence(occ);
            const n = occ.hits.length;
            return (
              <li key={occ.chapterId}>
                <button
                  type="button"
                  className={styles.occBtn}
                  disabled={!onJumpToChapter}
                  onClick={() =>
                    onJumpToChapter?.(occ.chapterId, primary.blockIndex)
                  }
                  title="跳到写作区并定位到对应段落"
                >
                  <strong>{occ.chapterTitle}</strong>
                  <span>
                    {primary.evidence}
                    {n > 1 ? ` · ×${n}` : ""}
                  </span>
                </button>
              </li>
            );
          })}
        </ul>
      )}

      <p className={styles.label}>LINK · 通路</p>
      <ul className={styles.linkList}>
        {links.map((l) => {
          const from = nameOf(l.fromId);
          const to = nameOf(l.toId);
          const ls = l.lineStyle ?? "solid";
          return (
            <li key={l.id}>
              <span>
                {from} — {to}
                <small> · {MAP_LINE_STYLE_LABELS[ls]}</small>
              </span>
              <button
                type="button"
                onClick={() => onRemoveLink(l.id)}
              >
                ×
              </button>
            </li>
          );
        })}
      </ul>
    </aside>
  );
}
