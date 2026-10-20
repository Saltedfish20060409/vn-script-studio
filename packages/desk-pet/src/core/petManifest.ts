/**
 * 桌宠运行时资源清单 — `/pet/v1/manifest.json`，结构见 docs/mascot-pet-spec.md §4。
 * 坐标全部是运行时像素（A 320×480 / B 240×240）。清单加载失败时返回 null，
 * 渲染层退回 SVG 占位小人，本次会话不再重试。
 */

export const PET_ASSET_BASE = "/pet/v1/";

export type PetCanvasId = "A" | "B";

export type PetBodyKey =
  | "idle"
  | "perch_top"
  | "peek_over"
  | "peek_side_r"
  | "peek_side_l"
  | "hide_corner"
  | "sleep"
  | "headpat"
  | "held"
  | "happy_jump"
  | "happy_land"
  | "perch_side";

export type PetFacePose = "idle" | "perch_top" | "peek_over";

export type PetWalkDir = "r" | "l";

export type PetAnchorType = "foot" | "sit" | "bottom" | "grip" | "grab" | "side";

export interface PetAnchor {
  type: PetAnchorType;
  x: number;
  y: number;
}

export interface PetEmoteAnchors {
  /** 符号框边长 */
  size: number;
  above_right: [number, number];
  zzz: [number, number];
  temple: [number, number];
}

export interface PetBodyAsset {
  canvas: PetCanvasId;
  src: string;
  anchor: PetAnchor;
  emote: PetEmoteAnchors;
}

export interface PetWalkAsset {
  src: string;
  /** [x, y, w, h]，图集内坐标 */
  frames: [number, number, number, number][];
  ms: number;
  anchor: PetAnchor;
  emote: PetEmoteAnchors;
}

/** 多帧图集（喂食 / 玩耍），结构同 walk */
export type PetSeqAsset = PetWalkAsset;

export interface PetFaceAtlas {
  src: string;
  /** 贴片在身体图上的位置 [x, y, w, h] */
  rect: [number, number, number, number];
  /** 变体名 → 图集内左上角 */
  variants: Record<string, [number, number]>;
}

export interface PetManifest {
  version: 1;
  canvas: Record<PetCanvasId, { w: number; h: number }>;
  bodies: Record<PetBodyKey, PetBodyAsset>;
  walk: Record<PetWalkDir, PetWalkAsset>;
  /** 菜单喂食：饼干由大到小 */
  feed: PetSeqAsset;
  /** 菜单玩耍：hold→toss→catch→settle */
  play: PetSeqAsset;
  faces: Partial<Record<PetFacePose, PetFaceAtlas>>;
}

export function petAssetUrl(file: string): string {
  return PET_ASSET_BASE + file;
}

export function isPetManifest(v: unknown): v is PetManifest {
  if (!v || typeof v !== "object") return false;
  const m = v as Partial<PetManifest>;
  return (
    m.version === 1 &&
    !!m.canvas?.A &&
    !!m.canvas?.B &&
    !!m.bodies?.idle &&
    !!m.walk?.r &&
    !!m.walk?.l &&
    !!m.feed?.src &&
    !!m.play?.src
  );
}

let pending: Promise<PetManifest | null> | null = null;

export function loadPetManifest(): Promise<PetManifest | null> {
  if (!pending) {
    pending = fetch(petAssetUrl("manifest.json"))
      .then((r) => (r.ok ? r.json() : null))
      .then((j: unknown) => (isPetManifest(j) ? j : null))
      .catch(() => null);
  }
  return pending;
}

function warm(src: string): void {
  const img = new Image();
  img.decoding = "async";
  img.src = petAssetUrl(src);
}

/**
 * 分期预加载：先暖待机身体+脸，再在空闲时逐张拉其余图。
 * 避免一次解码全部 WebP 造成内存尖峰；切姿势仍尽量不闪白。
 */
export function preloadPetAssets(m: PetManifest): void {
  warm(m.bodies.idle.src);
  const faceIdle = m.faces.idle?.src;
  if (faceIdle) warm(faceIdle);

  const rest = [
    ...Object.entries(m.bodies)
      .filter(([k]) => k !== "idle")
      .map(([, b]) => b.src),
    ...Object.values(m.walk).map((w) => w.src),
    m.feed.src,
    m.play.src,
    ...Object.entries(m.faces)
      .filter(([k]) => k !== "idle")
      .map(([, f]) => f!.src),
  ];
  let i = 0;
  const step = () => {
    if (i >= rest.length) return;
    warm(rest[i]!);
    i += 1;
    const ric = (window as Window & {
      requestIdleCallback?: (cb: () => void, opts?: { timeout: number }) => number;
    }).requestIdleCallback;
    if (ric) ric(step, { timeout: 1200 });
    else window.setTimeout(step, 120);
  };
  const ric = (window as Window & {
    requestIdleCallback?: (cb: () => void, opts?: { timeout: number }) => number;
  }).requestIdleCallback;
  if (ric) ric(step, { timeout: 800 });
  else window.setTimeout(step, 800);
}
