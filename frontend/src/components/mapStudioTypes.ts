import type {
  CustomMapElementDef,
  Location,
  LocationLink,
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
  onJumpToChapter?: (chapterId: string, blockIndex?: number) => void;
  focusLocationId?: string | null;
  focusTick?: number;
  onExtractFromScript?: () => void;
  onExtractRulesOnly?: () => void;
};
