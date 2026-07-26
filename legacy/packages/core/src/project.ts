import type {
  Location,
  LocationLink,
  StoryBible,
  VnProject,
} from "./types.js";
import { normalizeMapStyle, presetByKind } from "./mapCatalog.js";

export function normalizeProject(
  raw: Partial<VnProject> & { title?: string }
): VnProject {
  const bible: StoryBible = {
    world: raw.bible?.world ?? raw.lore ?? "",
    background: raw.bible?.background ?? "",
    outline: raw.bible?.outline ?? "",
    themes: raw.bible?.themes ?? "",
    notes: raw.bible?.notes ?? "",
  };

  return {
    id: raw.id || `proj-${Date.now()}`,
    title: raw.title || "未命名剧本",
    logline: raw.logline,
    genre: raw.genre,
    characters: raw.characters ?? [],
    chapters:
      raw.chapters && raw.chapters.length > 0
        ? raw.chapters
        : [
            {
              id: "ch1",
              title: "第一章",
              blocks: [{ type: "label", id: "start", name: "start" }],
            },
          ],
    lore: bible.world,
    bible,
    locations: raw.locations ?? [],
    locationLinks: raw.locationLinks ?? [],
    mapStyle: normalizeMapStyle(raw.mapStyle),
    customMapElements: raw.customMapElements ?? [],
    mapStrokes: raw.mapStrokes ?? [],
    characterLinks: raw.characterLinks ?? [],
    timeline: raw.timeline ?? [],
    variables: raw.variables ?? [],
    sprites: raw.sprites ?? [],
    snapshots: raw.snapshots ?? [],
    shareId: raw.shareId,
    updatedAt: raw.updatedAt || new Date().toISOString(),
  };
}

export function touchProject(project: VnProject): VnProject {
  const bible = project.bible ?? {};
  return {
    ...project,
    lore: bible.world ?? project.lore,
    bible: {
      world: bible.world ?? project.lore ?? "",
      background: bible.background ?? "",
      outline: bible.outline ?? "",
      themes: bible.themes ?? "",
      notes: bible.notes ?? "",
    },
    locations: project.locations ?? [],
    locationLinks: project.locationLinks ?? [],
    mapStyle: normalizeMapStyle(project.mapStyle),
    customMapElements: project.customMapElements ?? [],
    mapStrokes: project.mapStrokes ?? [],
    characterLinks: project.characterLinks ?? [],
    timeline: project.timeline ?? [],
    variables: project.variables ?? [],
    sprites: project.sprites ?? [],
    snapshots: project.snapshots ?? [],
    updatedAt: new Date().toISOString(),
  };
}

/** Pull scene tags from script → locations + sequential links (merge, non-destructive). */
export function extractLocationsFromScript(project: VnProject): Location[] {
  return extractMapFromScript(project).locations;
}

export function extractMapFromScript(project: VnProject): {
  locations: Location[];
  locationLinks: LocationLink[];
  addedCount: number;
  linkCount: number;
} {
  const STAGE_X = 1300;
  const STAGE_Y = 1050;
  const existingByTag = new Map<string, Location>();
  for (const l of project.locations ?? []) {
    if (l.imageTag) existingByTag.set(normalizeSceneKey(l.imageTag), l);
  }

  const orderIds: string[] = [];
  const seenInPass = new Set<string>();
  let locations = [...(project.locations ?? [])];
  let addedCount = 0;

  const scenes: string[] = [];
  for (const ch of project.chapters) {
    walkBlocks(ch.blocks, (b) => {
      if (b.type === "scene" && b.image.trim()) {
        scenes.push(b.image.trim());
      }
    });
  }

  for (const image of scenes) {
    const key = normalizeSceneKey(image);
    let loc = existingByTag.get(key);
    if (!loc) {
      const preset = inferPresetFromScene(image);
      const idx = locations.length;
      loc = {
        id: uid("loc"),
        name: prettySceneName(image),
        imageTag: image.startsWith("bg ") || image.startsWith("bg_")
          ? image
          : image,
        description: "从剧本 scene 自动提取",
        elementKind: preset.kind,
        icon: preset.icon,
        color: preset.color,
        mapX: STAGE_X + 200 + (idx % 5) * 320,
        mapY: STAGE_Y + 280 + Math.floor(idx / 5) * 260,
        scale: 1,
        rotation: 0,
      };
      locations.push(loc);
      existingByTag.set(key, loc);
      addedCount += 1;
    } else if (loc.mapX == null || loc.mapY == null) {
      const idx = locations.findIndex((l) => l.id === loc!.id);
      const mapX = STAGE_X + 200 + (Math.max(0, idx) % 5) * 320;
      const mapY = STAGE_Y + 280 + Math.floor(Math.max(0, idx) / 5) * 260;
      locations = locations.map((l) =>
        l.id === loc!.id
          ? {
              ...l,
              mapX: l.mapX ?? mapX,
              mapY: l.mapY ?? mapY,
              icon: l.icon || inferPresetFromScene(image).icon,
              color: l.color || inferPresetFromScene(image).color,
              elementKind: l.elementKind || inferPresetFromScene(image).kind,
            }
          : l
      );
      loc = locations.find((l) => l.id === loc!.id)!;
      existingByTag.set(key, loc);
    }
    if (!seenInPass.has(loc.id)) {
      seenInPass.add(loc.id);
      orderIds.push(loc.id);
    }
  }

  const oldLinks = project.locationLinks ?? [];
  const linkKeys = new Set(
    oldLinks.map((l) => `${l.fromId}->${l.toId}:${l.relation}`)
  );
  const locationLinks = [...oldLinks];
  let linkCount = 0;
  for (let i = 0; i < orderIds.length - 1; i++) {
    const fromId = orderIds[i];
    const toId = orderIds[i + 1];
    if (fromId === toId) continue;
    const key = `${fromId}->${toId}:leads_to`;
    if (linkKeys.has(key)) continue;
    locationLinks.push(newLocationLink(fromId, toId, "leads_to"));
    linkKeys.add(key);
    linkCount += 1;
  }

  return { locations, locationLinks, addedCount, linkCount };
}

function normalizeSceneKey(image: string): string {
  return image.trim().toLowerCase().replace(/\s+/g, " ");
}

function prettySceneName(image: string): string {
  return image
    .replace(/^bg[_\s]+/i, "")
    .replace(/_/g, " ")
    .trim() || image;
}

function inferPresetFromScene(image: string): {
  kind: import("./types.js").MapElementKind;
  icon: string;
  color: string;
} {
  const s = image.toLowerCase();
  const table: [RegExp, import("./types.js").MapElementKind][] = [
    [/station|车站|月台|rail/, "station"],
    [/school|学校|教室|campus/, "school"],
    [/cafe|咖啡|茶/, "cafe"],
    [/home|家|房间|room/, "home"],
    [/park|公园/, "park"],
    [/hospital|医院/, "hospital"],
    [/shop|店|便利/, "shop"],
    [/office|公司|职场/, "office"],
    [/temple|神社|寺/, "temple"],
    [/forest|林|森/, "forest"],
    [/beach|海|海边/, "beach"],
    [/bridge|桥|通道|tunnel/, "bridge"],
    [/plaza|广场/, "plaza"],
    [/apartment|公寓/, "apartment"],
  ];
  for (const [re, kind] of table) {
    if (re.test(s)) {
      const p = presetByKind(kind);
      return { kind: p.kind, icon: p.icon, color: p.color };
    }
  }
  const p = presetByKind("landmark");
  return { kind: p.kind, icon: p.icon, color: p.color };
}

function walkBlocks(
  blocks: import("./types.js").ScriptBlock[],
  visit: (b: import("./types.js").ScriptBlock) => void
) {
  for (const b of blocks) {
    visit(b);
    if (b.type === "menu") {
      for (const c of b.choices) {
        if (c.blocks?.length) walkBlocks(c.blocks, visit);
      }
    }
  }
}

export function uid(prefix: string): string {
  return `${prefix}-${Date.now().toString(36)}-${Math.random().toString(36).slice(2, 7)}`;
}

export function newLocationLink(
  fromId: string,
  toId: string,
  relation: LocationLink["relation"] = "adjacent"
): LocationLink {
  return {
    id: uid("link"),
    fromId,
    toId,
    relation,
  };
}
