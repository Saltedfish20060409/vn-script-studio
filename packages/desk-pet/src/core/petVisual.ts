/**
 * 状态 → 画面（纯函数）：身体用哪张图、脸叠哪个贴片、情绪符号挂在哪；
 * 以及按挂点把画布摆到屏幕上的换算。规则见 docs/mascot-pet-art-brief.md。
 */
import type { PetEmoteAnchors, PetBodyKey, PetFacePose, PetManifest, PetWalkDir } from "./petManifest";
import type { PetBody, PetEmote, PetMood, PetPlacement, PetState } from "./petMachine";

/** A 套运行时宽；显示宽 / 这个数 = 缩放（B 套显示宽是 A 的 3/4，缩放相同） */
export const PET_RUNTIME_A_W = 320;
export const PET_DISPLAY = { small: 96, medium: 128, large: 160 } as const;
/** 情绪符号在屏幕上的最小边长（CSS px），太小认不出 */
export const PET_EMOTE_MIN_PX = 22;

export type PetExpression = Exclude<PetMood, "neutral">;
export type PetEmoteAnchorKey = "above_right" | "zzz" | "temple";

export type PetVisualBody = PetBodyKey | "walk" | "feed" | "play";

export interface PetVisual {
  body: PetVisualBody;
  face: PetFacePose | null;
  /** 表情贴片；有表情时不眨眼、不播口型（表情优先） */
  expression: PetExpression | null;
  /** 睡着时直接用全闭贴片 */
  eyesClosed: boolean;
  canBlink: boolean;
  canTalk: boolean;
  /** 旅行 walk 才起伏；菜单 play 图集不起伏 */
  walkBob: boolean;
  emote: PetEmote;
  emoteAnchor: PetEmoteAnchorKey;
  /** peek_under：探头图和脸贴片整体转 180°，挂点改到顶边中心 */
  upsideDown: boolean;
  /** 靠框左侧外沿：身体水平镜像，贴框点落到画布右侧 */
  mirror: boolean;
}

/** 有专属姿势的位置：反应期间身体留在这个姿势上，只换脸 */
const PLACED_BODY: Partial<Record<PetPlacement, PetBodyKey>> = {
  perchTop: "perch_top",
  peekOver: "peek_over",
  peekUnder: "peek_over",
  perchSideLeft: "perch_side",
  perchSideRight: "perch_side",
  edgeLeft: "peek_side_l",
  edgeRight: "peek_side_r",
};

const GROUND_BODY: Record<PetBody, PetVisualBody> = {
  idle: "idle",
  walk: "walk",
  perchTop: "perch_top",
  peekOver: "peek_over",
  peekSide: "peek_side_r",
  hideCorner: "hide_corner",
  happy: "happy_jump",
  feed: "feed",
  play: "play",
  headpat: "headpat",
  nod: "idle",
  fluster: "idle",
  sleep: "sleep",
  held: "held",
  land: "idle",
};

const FACE_OF: Partial<Record<PetBodyKey, PetFacePose>> = {
  idle: "idle",
  perch_top: "perch_top",
  peek_over: "peek_over",
};

/** 有表情贴片的脸 */
const EXPRESSIVE: ReadonlySet<PetFacePose> = new Set<PetFacePose>(["idle", "peek_over"]);

function emoteAnchorFor(emote: PetEmote): PetEmoteAnchorKey {
  if (emote === "zzz") return "zzz";
  if (emote === "sweat") return "temple";
  return "above_right";
}

export function petVisual(s: Pick<PetState, "body" | "placement" | "mood" | "emote">): PetVisual {
  const placed = PLACED_BODY[s.placement];
  let body: PetVisualBody;
  // 喂食/玩耍图集必须盖过贴框姿势，否则只剩眨眼、看不到饼干/球
  if (
    s.body === "held" ||
    s.body === "walk" ||
    s.body === "feed" ||
    s.body === "play"
  ) {
    body = GROUND_BODY[s.body];
  } else if (placed) body = placed;
  else body = GROUND_BODY[s.body];

  const asleep = s.body === "sleep";
  const face =
    body === "walk" || body === "feed" || body === "play"
      ? null
      : (FACE_OF[body as PetBodyKey] ?? null);
  const eyesClosed = asleep && face !== null;
  const expression =
    face && !asleep && s.mood !== "neutral" && EXPRESSIVE.has(face) ? s.mood : null;
  return {
    body,
    face,
    expression,
    eyesClosed,
    canBlink: face !== null && !expression && !eyesClosed,
    canTalk: face === "idle" && !expression && !asleep,
    walkBob: body === "walk",
    emote: s.emote,
    emoteAnchor: emoteAnchorFor(s.emote),
    upsideDown: s.placement === "peekUnder",
    mirror: s.placement === "perchSideLeft",
  };
}

/** 松手时指针离屏幕左右边缘多近算贴边 */
export const EDGE_SNAP_PX = 14;
/** 脚落在框顶线上下这个范围内 → 坐框顶；框底线同宽 → 框下探头 */
export const FRAME_EDGE_BAND_PX = 36;
/** 脚落在框顶线以下、还没到框下探头带时 → 框后探头 */
export const PEEK_DEPTH_PX = 160;
/** 脚落在框左右外沿外侧这个宽度内，并且高度还在框的上下之间 → 靠框外沿 */
export const SIDE_BAND_PX = 72;

export interface FrameRect {
  left: number;
  right: number;
  top: number;
  bottom: number;
}

/**
 * 拖拽松手的落点。判定用站立脚位（和拎起图的脚同一列），屏幕贴边用指针的横坐标。
 * 框又矮又让顶带和底带叠在一起时，离哪条边近算哪条。
 */
export function classifyDrop(
  foot: { x: number; y: number },
  pointerX: number,
  frame: FrameRect | null,
  viewportW: number
): PetPlacement {
  if (pointerX <= EDGE_SNAP_PX) return "edgeLeft";
  if (pointerX >= viewportW - EDGE_SNAP_PX) return "edgeRight";
  if (!frame) return "free";
  const insideX = foot.x > frame.left && foot.x < frame.right;
  if (insideX) {
    const fromTop = Math.abs(foot.y - frame.top);
    const fromBottom = Math.abs(foot.y - frame.bottom);
    const nearTop = fromTop <= FRAME_EDGE_BAND_PX;
    const nearBottom = fromBottom <= FRAME_EDGE_BAND_PX;
    if (nearTop && nearBottom) return fromTop <= fromBottom ? "perchTop" : "peekUnder";
    if (nearTop) return "perchTop";
    if (nearBottom) return "peekUnder";
    const belowTop = foot.y - frame.top;
    if (belowTop > FRAME_EDGE_BAND_PX && belowTop <= PEEK_DEPTH_PX) return "peekOver";
  }
  const alongside = foot.y >= frame.top - FRAME_EDGE_BAND_PX && foot.y <= frame.bottom + FRAME_EDGE_BAND_PX;
  if (alongside && foot.x < frame.left && frame.left - foot.x <= SIDE_BAND_PX) return "perchSideLeft";
  if (alongside && foot.x > frame.right && foot.x - frame.right <= SIDE_BAND_PX) return "perchSideRight";
  return "free";
}

export function petScale(displayW: number): number {
  return displayW / PET_RUNTIME_A_W;
}

export interface PetBodyMetrics {
  w: number;
  h: number;
  anchor: { x: number; y: number };
  emote: PetEmoteAnchors;
}

export function bodyMetrics(
  m: PetManifest,
  body: PetVisualBody,
  dir: PetWalkDir = "r"
): PetBodyMetrics {
  if (body === "walk") {
    const w = m.walk[dir];
    return { ...m.canvas.A, anchor: w.anchor, emote: w.emote };
  }
  if (body === "feed") {
    const f = m.feed;
    return { ...m.canvas.A, anchor: f.anchor, emote: f.emote };
  }
  if (body === "play") {
    const p = m.play;
    return { ...m.canvas.A, anchor: p.anchor, emote: p.emote };
  }
  const b = m.bodies[body];
  return { ...m.canvas[b.canvas], anchor: b.anchor, emote: b.emote };
}

/** 框下探头：原底边中心转到顶边中心 */
export function upsideDownAnchor(met: PetBodyMetrics): PetBodyMetrics {
  return { ...met, anchor: { ...met.anchor, x: met.w - met.anchor.x, y: met.h - met.anchor.y } };
}

/** 靠框左侧：贴框点从画布左侧翻到右侧 */
export function mirroredAnchor(met: PetBodyMetrics): PetBodyMetrics {
  return { ...met, anchor: { ...met.anchor, x: met.w - met.anchor.x } };
}

export interface PetBox {
  left: number;
  top: number;
}

/** 让挂点落在屏幕坐标 (x, y) 时，画布左上角的位置 */
export function boxAt(metrics: PetBodyMetrics, scale: number, x: number, y: number): PetBox {
  return { left: x - metrics.anchor.x * scale, top: y - metrics.anchor.y * scale };
}

/** 画布左上角为 box 时，挂点的屏幕坐标 */
export function anchorOf(metrics: PetBodyMetrics, scale: number, box: PetBox): { x: number; y: number } {
  return { x: box.left + metrics.anchor.x * scale, y: box.top + metrics.anchor.y * scale };
}

export interface PetViewport {
  w: number;
  h: number;
  /** 底部固定条预留 */
  bottomReserve: number;
}

/**
 * 坐框顶的边界检查：脚垂到框顶线下方（母版 366px），不能出屏幕底部；
 * 头顶也不能出屏幕顶部。
 */
export function canPerchAt(m: PetManifest, scale: number, frameTop: number, vp: PetViewport): boolean {
  const met = bodyMetrics(m, "perch_top");
  const box = boxAt(met, scale, 0, frameTop);
  const feet = frameTop + (met.h - met.anchor.y) * scale;
  const headTop = box.top + met.h * 0.04 * scale;
  return feet <= vp.h - vp.bottomReserve && headTop >= 0;
}

/** 框后探头：头要露在屏幕内 */
export function canPeekAt(m: PetManifest, scale: number, frameTop: number): boolean {
  const met = bodyMetrics(m, "peek_over");
  const headTop = frameTop - (met.anchor.y - met.h * 0.3) * scale;
  return headTop >= 0;
}

/** 框下探头：身体挂在框底线下面，至少露出半个身位 */
export function canPeekUnderAt(m: PetManifest, scale: number, frameBottom: number, vp: PetViewport): boolean {
  const met = bodyMetrics(m, "peek_over");
  return frameBottom > 24 && frameBottom + met.h * scale * 0.55 <= vp.h - vp.bottomReserve;
}

/** 靠框外沿：贴框点外侧要容得下身体 */
export function canPerchSideAt(
  side: "perchSideLeft" | "perchSideRight",
  m: PetManifest,
  scale: number,
  frameEdgeX: number,
  vp: PetViewport
): boolean {
  const met = bodyMetrics(m, "perch_side");
  const reach = (met.w - met.anchor.x) * scale;
  return side === "perchSideRight" ? frameEdgeX + reach <= vp.w : frameEdgeX - reach >= 0;
}

/** 情绪符号在画布内的位置与边长（运行时像素），边长不低于屏幕上的最小值 */
export function emoteBox(
  metrics: PetBodyMetrics,
  anchor: PetEmoteAnchorKey,
  scale: number
): { cx: number; cy: number; size: number } {
  const [cx, cy] = metrics.emote[anchor];
  return { cx, cy, size: Math.max(metrics.emote.size, PET_EMOTE_MIN_PX / scale) };
}
