/**
 * Q 版桌宠动作配置 — 逐帧参数来自 docs/mascot-pet-art-brief.md。
 *
 * 帧数/停留时长/循环规则按文档定死；美术 PNG 按
 * `pet/{A_body|B_peek}/pet_{action}_{flip?}_{NN}.png` 命名交付，
 * 缺帧时播放器回退到 Q 版占位（PetPlaceholder）。
 */

export type PetCanvas = "A" | "B";

export type PetActionId =
  // P0
  | "breath_idle"
  | "blink"
  | "walk_side_r"
  | "perch_top"
  | "peek_over"
  | "peek_side_r"
  // P1
  | "perch_side_r"
  | "peek_under"
  | "hide_corner"
  | "slip_r"
  | "react_fluster"
  | "react_cheer"
  // P2（框架支持，默认缺帧占位）
  | "fall_asleep"
  | "drag_held"
  | "drop_land"
  | "read_over_shoulder";

export interface PetAnimationSpec {
  id: PetActionId;
  canvas: PetCanvas;
  /** 帧文件名前缀（目录内的基础名） */
  base: string;
  /** 总帧数（文档定死） */
  frames: number;
  /** 每帧停留毫秒（文档建议，程序可微调） */
  holdMs: number[];
  /** 循环动作：最后一帧接回第 01 帧 */
  loop: boolean;
  /** 面朝右的侧向动作（程序对朝左做镜像） */
  flip?: boolean;
  /** 单次动作可停在第 N 帧（1-based；peek 停在 03） */
  stopAt?: number;
  /** 挂点（画布内坐标；文档规则：foot=水平中线/底部上48px 等） */
  anchor?: {
    foot?: { x: number; y: number };
    sit_contact?: { x: number; y: number };
    hand_grip?: { x: number; y: number };
    head_center?: { x: number; y: number };
  };
}

export const PET_CANVAS: Record<PetCanvas, { w: number; h: number }> = {
  A: { w: 512, h: 768 }, // 全身
  B: { w: 384, h: 384 }, // 探头（头+肩）
};

function a(id: PetActionId, frames: number, holdMs: number[], loop: boolean, extra?: Partial<PetAnimationSpec>): PetAnimationSpec {
  return {
    id,
    canvas: "A",
    base: id,
    frames,
    holdMs,
    loop,
    ...extra,
  };
}

/** 单次插播/反应：播完回 breath_idle */
function oneShot(id: PetActionId, frames: number, holdMs: number[], extra?: Partial<PetAnimationSpec>): PetAnimationSpec {
  return { ...a(id, frames, holdMs, false, extra), loop: false };
}

export const PET_ANIMATIONS: Record<PetActionId, PetAnimationSpec> = {
  // ---- P0 ----
  breath_idle: a("breath_idle", 4, [400, 400, 400, 400], true, {
    anchor: { foot: { x: 256, y: 768 - 48 } },
  }),
  blink: oneShot("blink", 3, [60, 80, 60], {
    anchor: { foot: { x: 256, y: 768 - 48 } },
  }),
  walk_side_r: a("walk_side_r", 6, [120, 120, 120, 120, 120, 120], true, {
    flip: true,
    anchor: { foot: { x: 256, y: 768 - 48 } },
  }),
  perch_top: a("perch_top", 2, [1000, 1000], true, {
    anchor: { sit_contact: { x: 256, y: 384 } },
  }),
  peek_over: oneShot("peek_over", 4, [80, 100, 120, 120], {
    canvas: "B",
    stopAt: 3,
    anchor: { head_center: { x: 192, y: 192 } },
  }),
  peek_side_r: oneShot("peek_side_r", 4, [80, 100, 120, 120], {
    canvas: "B",
    flip: true,
    stopAt: 3,
    anchor: { head_center: { x: 192, y: 192 } },
  }),
  // ---- P1 ----
  perch_side_r: a("perch_side_r", 2, [1000, 1000], true, {
    flip: true,
    anchor: {
      foot: { x: 256, y: 768 - 48 },
      hand_grip: { x: 400, y: 500 },
    },
  }),
  peek_under: oneShot("peek_under", 4, [80, 100, 120, 120], {
    canvas: "B",
    stopAt: 3,
    anchor: { head_center: { x: 192, y: 192 } },
  }),
  hide_corner: a("hide_corner", 1, [60000], false, {
    anchor: { foot: { x: 256, y: 768 - 48 } },
  }),
  slip_r: oneShot("slip_r", 4, [80, 100, 120, 100], {
    flip: true,
    anchor: { foot: { x: 256, y: 768 - 48 } },
  }),
  react_fluster: oneShot("react_fluster", 4, [80, 140, 160, 160]),
  react_cheer: oneShot("react_cheer", 4, [100, 160, 160, 160]),
  // ---- P2 ----
  // 睡眠时长由组件控制（3min 无交互触发、随机睡 45~120s）；末帧停很久，
  // 避免帧动画抢先唤醒
  fall_asleep: a("fall_asleep", 5, [300, 300, 400, 250, 180000], false, {
    anchor: { sit_contact: { x: 256, y: 384 } },
  }),
  drag_held: a("drag_held", 2, [220, 220], true),
  drop_land: oneShot("drop_land", 3, [80, 120, 120]),
  read_over_shoulder: a("read_over_shoulder", 3, [800, 800, 800], true),
};

export const PET_ACTIONS = Object.keys(PET_ANIMATIONS) as PetActionId[];

/** 待机池：桌宠会不规律地在这些动作之间切换（dock=趴在编辑器旁） */
export const IDLE_POOL_DOCK: PetActionId[] = [
  "breath_idle", // 呼吸
  "perch_top", // 趴在文本框顶
  "peek_over", // 从框顶探头
  "read_over_shoulder", // 侧身偷看文稿
];

/** 角落待机池：缩在角落时的姿态 */
export const IDLE_POOL_CORNER: PetActionId[] = [
  "breath_idle",
  "hide_corner", // 蜷坐
];

/** 单帧 URL（按文档命名规则；base 已含方向后缀如 `_r`，此处不再追加） */
export function petFrameUrl(spec: PetAnimationSpec, frameIndex: number): string {
  const dir = spec.canvas === "A" ? "A_body" : "B_peek";
  const nn = String(frameIndex + 1).padStart(2, "0");
  return `/pet/${dir}/pet_${spec.base}_${nn}.png`;
}
