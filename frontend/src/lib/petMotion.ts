/**
 * 程序补间。变换画在精灵内层，不改挂点换算。
 * 减少动态效果时调用方不使用这些位移。
 *
 * 庆祝时间轴来自简报（脚底为锚）。表内各段相加是 2280ms，定稿总长 2240ms，
 * 多出来的 40ms 从最后一段静止里扣掉（800 → 760）。
 */

export const CELEBRATE_MS = 2240;
/** 喂食短庆祝截断（存档庆祝等仍用完整 CELEBRATE_MS；菜单喂食已改图集） */
export const FEED_CELEBRATE_MS = 1200;
/** 菜单喂食图集：4 帧 × 380ms（饼干渐消） */
export const FEED_FRAME_MS = 380;
export const FEED_FRAMES = 4;
export const FEED_TOTAL_MS = FEED_FRAME_MS * FEED_FRAMES;
/** 菜单玩耍图集：hold→toss→catch→settle，4 × 400ms */
export const PLAY_FRAME_MS = 400;
export const PLAY_FRAMES = 4;
export const PLAY_MS = PLAY_FRAME_MS * PLAY_FRAMES;
/** 改脚版抓点，母版像素。沿用定稿，不重测。 */
export const GRAB_MASTER = { x: 386, y: 48 } as const;
export const MASTER_W = 768;
export const RUNTIME_A_W = 320;

const JUMP_MASTER = 144;
export const JUMP_RUNTIME = (JUMP_MASTER * RUNTIME_A_W) / MASTER_W;

export type CelebrateBody = "idle" | "happy_jump" | "happy_land";

export interface CelebratePose {
  body: CelebrateBody;
  /** 运行时像素，向上为负 */
  y: number;
  scaleY: number;
}

function clamp01(u: number): number {
  return Math.min(1, Math.max(0, u));
}

function easeOut(u: number): number {
  const t = clamp01(u);
  return 1 - (1 - t) * (1 - t);
}

function easeIn(u: number): number {
  const t = clamp01(u);
  return t * t;
}

function smoothstep(u: number): number {
  const t = clamp01(u);
  return t * t * (3 - 2 * t);
}

/**
 * t 为毫秒。`endMs` 截断短庆祝（喂食）：到点后停在 idle，不再跑发顶回弹。
 * 省略或 ≥ CELEBRATE_MS 时走完整轴。
 */
export function celebrateAt(t: number, endMs: number = CELEBRATE_MS): CelebratePose {
  const ms = Math.max(0, t);
  const cap = Math.min(Math.max(0, endMs), CELEBRATE_MS);
  if (ms >= cap) return { body: "idle", y: 0, scaleY: 1 };
  if (ms < 400) return { body: "idle", y: 0, scaleY: 1 };
  if (ms < 560) {
    return { body: "happy_jump", y: -JUMP_RUNTIME * easeOut((ms - 400) / 160), scaleY: 1 };
  }
  if (ms < 680) return { body: "happy_jump", y: -JUMP_RUNTIME, scaleY: 1 };
  if (ms < 840) {
    return { body: "happy_jump", y: -JUMP_RUNTIME * (1 - easeIn((ms - 680) / 160)), scaleY: 1 };
  }
  if (ms < 1000) {
    return { body: "happy_land", y: 0, scaleY: 0.92 + 0.08 * easeOut((ms - 840) / 160) };
  }
  if (ms < 1400) return { body: "happy_land", y: 0, scaleY: 1 };
  if (ms < 1480) {
    return { body: "happy_land", y: 0, scaleY: 1 + 0.031 * smoothstep((ms - 1400) / 80) };
  }
  return { body: "idle", y: 0, scaleY: 1 };
}

/** 走路一拍 320ms，两拍一个起伏。幅度是运行时像素。 */
export function walkBobY(t: number): number {
  return Math.sin((t / 640) * Math.PI * 2) * 14;
}

/** 待机呼吸：约 3.2s 一周期，脚底为锚轻微拉高（±1.8%）。 */
export function idleBreathScaleY(t: number): number {
  return 1 + Math.sin((t / 3200) * Math.PI * 2) * 0.018;
}

/** 坐框顶 ±2° / 2.4s，绕坐点转 */
export function perchSwayDeg(t: number): number {
  return Math.sin((t / 2400) * Math.PI * 2) * 2;
}

/** 坐睡点头，绕胸口 */
export function sleepNodDeg(t: number): number {
  return Math.sin((t / 2800) * Math.PI * 2) * 3;
}

export const PEEK_SLIDE_MS = 480;

/** 探头从框后滑出的剩余下移（运行时像素） */
export function peekSlideY(t: number, height: number): number {
  if (t >= PEEK_SLIDE_MS) return 0;
  const u = clamp01(t / PEEK_SLIDE_MS);
  const eased = 1 - (1 - u) * (1 - u) * (1 - u);
  return (1 - eased) * height * 0.72;
}

export const PENDULUM = {
  gain: 0.009,
  maxDeg: 12,
  omega: 12,
  zeta: 0.6,
  speedSmoothSec: 0.06,
} as const;

export interface Pendulum {
  /** 简报里的 θ，度。往右拖时为负。 */
  angle: number;
  /** 角速度，度/秒 */
  omega: number;
  /** 平滑后的横向速度，母版 px/s */
  speed: number;
}

export function createPendulum(): Pendulum {
  return { angle: 0, omega: 0, speed: 0 };
}

function clamp(n: number, lo: number, hi: number): number {
  return Math.min(hi, Math.max(lo, n));
}

export function stepPendulum(p: Pendulum, speedMaster: number, dt: number): Pendulum {
  // 与 drag_pendulum.py 相同的一阶欧拉平滑（不是指数形式）
  const speed = p.speed + (speedMaster - p.speed) * (dt / PENDULUM.speedSmoothSec);
  const target = clamp(-PENDULUM.gain * speed, -PENDULUM.maxDeg, PENDULUM.maxDeg);
  const w = PENDULUM.omega;
  const acc = -w * w * (p.angle - target) - 2 * PENDULUM.zeta * w * p.omega;
  let omega = p.omega + acc * dt;
  let angle = p.angle + omega * dt;
  if (angle >= PENDULUM.maxDeg || angle <= -PENDULUM.maxDeg) {
    angle = clamp(angle, -PENDULUM.maxDeg, PENDULUM.maxDeg);
    omega = 0;
  }
  return { angle, omega, speed };
}

/** 屏幕上顺时针为正。往右拖时脚往左甩。 */
export function swingCssDeg(p: Pendulum): number {
  return -p.angle;
}

/** 指针位移（CSS px）换成母版 px/s */
export function masterPxPerSec(dxCss: number, dtMs: number, scale: number): number {
  if (dtMs <= 0 || scale <= 0) return 0;
  return ((dxCss / scale) * (MASTER_W / RUNTIME_A_W)) / (dtMs / 1000);
}
