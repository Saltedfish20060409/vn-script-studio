import type { CustomMapElementDef, MapElementKind } from "../types/vn";
import { MAP_ELEMENT_PRESETS } from "../lib/mapCatalog";
import { MapPinGlyph, isGlyphKey } from "./MapPinGlyph";
import type { Tool } from "./mapStudioTypes";
import styles from "./MapStudio.module.css";

type CustomFormState = { name: string; icon: string; color: string };

type Props = {
  tool: Tool;
  placeKind: MapElementKind;
  placeCustomId: string | null;
  customElements: CustomMapElementDef[];
  customForm: CustomFormState;
  onSetTool: (tool: Tool) => void;
  onSetPlaceKind: (kind: MapElementKind) => void;
  onSetPlaceCustomId: (id: string | null) => void;
  onSetCustomForm: (updater: (f: CustomFormState) => CustomFormState) => void;
  onChangeCustomElements: (defs: CustomMapElementDef[]) => void;
  onAddCustom: () => void;
};

/** Left rail: place-kind palette plus the custom-element form. Pure presentational. */
export function MapPalette({
  tool,
  placeKind,
  placeCustomId,
  customElements,
  customForm,
  onSetTool,
  onSetPlaceKind,
  onSetPlaceCustomId,
  onSetCustomForm,
  onChangeCustomElements,
  onAddCustom,
}: Props) {
  return (
    <aside className={styles.left}>
      <p className={styles.label}>NODE · 地点</p>
      <div className={styles.palette}>
        {MAP_ELEMENT_PRESETS.filter((p) => p.kind !== "custom").map((p) => (
          <button
            key={p.kind}
            type="button"
            className={
              tool === "place" && placeKind === p.kind && !placeCustomId
                ? styles.palActive
                : styles.palBtn
            }
            onClick={() => {
              onSetPlaceKind(p.kind);
              onSetPlaceCustomId(null);
              onSetTool("place");
            }}
            title={p.hint}
          >
            <MapPinGlyph kind={p.icon} color={p.color} size="sm" />
            {p.name}
          </button>
        ))}
        {customElements.map((c) => (
          <div
            key={c.id}
            className={
              tool === "place" && placeCustomId === c.id
                ? styles.palCustomActive
                : styles.palCustom
            }
          >
            <button
              type="button"
              className={styles.palCustomMain}
              onClick={() => {
                onSetPlaceKind("custom");
                onSetPlaceCustomId(c.id);
                onSetTool("place");
              }}
              title="选中以放置"
            >
              <MapPinGlyph
                kind={isGlyphKey(c.icon) ? c.icon : "custom"}
                color={c.color}
                size="sm"
              />
              {c.name}
            </button>
            <button
              type="button"
              className={styles.palCustomDel}
              title="从图鉴删除（已放置的图钉仍保留）"
              onClick={(e) => {
                e.stopPropagation();
                if (placeCustomId === c.id) {
                  onSetPlaceCustomId(null);
                  onSetPlaceKind("landmark");
                }
                onChangeCustomElements(
                  customElements.filter((x) => x.id !== c.id)
                );
              }}
            >
              ×
            </button>
          </div>
        ))}
      </div>
      {customElements.length > 0 && (
        <p className={styles.hintTiny}>
          内置元素不可删；自定义项点 × 可移除图鉴
        </p>
      )}

      <p className={styles.label}>自定义</p>
      <div className={styles.customForm}>
        <input
          value={customForm.name}
          onChange={(e) =>
            onSetCustomForm((f) => ({ ...f, name: e.target.value }))
          }
          placeholder="名称"
        />
        <div className={styles.customRow}>
          <span className={styles.hintTiny} style={{ alignSelf: "center" }}>
            章钉色
          </span>
          <input
            type="color"
            value={customForm.color}
            onChange={(e) =>
              onSetCustomForm((f) => ({
                ...f,
                color: e.target.value,
                icon: "custom",
              }))
            }
          />
        </div>
        <button type="button" className={styles.primary} onClick={onAddCustom}>
          加入图鉴并放置
        </button>
      </div>
    </aside>
  );
}
