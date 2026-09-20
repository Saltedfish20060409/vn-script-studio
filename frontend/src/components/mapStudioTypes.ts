import type {
  CustomMapElementDef,
  Location,
  LocationLink,
  MapMeasure,
  MapStroke,
  SceneChapter,
} from "../types/vn";

export type Tool = "pan" | "select" | "place" | "link" | "draw";

export type MapStudioProps = {
  locations: Location[];
  links: LocationLink[];
  chapters: SceneChapter[];
  customElements: CustomMapElementDef[];
  strokes: MapStroke[];
  onChangeLocations: (locations: Location[]) => void;
  onChangeLinks: (links: LocationLink[]) => void;
  onChangeCustomElements: (defs: CustomMapElementDef[]) => void;
  onChangeStrokes: (strokes: MapStroke[]) => void;
  /** 测距比例尺（作品数据，跨设备跟着走；缺省时用本机默认值） */
  mapMeasure?: MapMeasure;
  onChangeMapMeasure: (next: MapMeasure) => void;
  onJumpToChapter?: (chapterId: string, blockIndex?: number) => void;
  focusLocationId?: string | null;
  focusTick?: number;
  onExtractFromScript?: () => void;
  onExtractRulesOnly?: () => void;
};
