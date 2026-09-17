/**
 * AI 责编浮窗的几何：面板尺寸、拖动夹取、以及"什么时候收起成侧边标签"。
 *
 * 单独成模块是为了能测 —— 贴边收起的判定范围调过好几次（用户反馈过"还没碰到边
 * 就缩成标签"），这种手感问题只能靠纯函数 + 边界用例锁住。
 */

export type Edge = "left" | "right" | "top" | "bottom";

export const PANEL_W = 560;
export const PANEL_H = 560;
export const MIN_W = 420;
export const MIN_H = 360;

/**
 * 收起成侧边标签的判定：面板**必须真的被拖出视口一部分**才算。
 *
 * 以前是"离边 56px 以内就收起"，于是从中间往边上拖、手还没碰到边，面板就突然缩成标签了。
 * 现在看的是"越界多少"：四个方向里出界最多的那个超过 DOCK_OVERSHOOT 才算贴边收起；
 * 留 20px 余量是防止手抖越过 1px 就收起。
 */
export const DOCK_OVERSHOOT = 20;

export function clamp(n: number, min: number, max: number) {
  return Math.min(Math.max(min, n), max);
}

/** 静止时的位置：保证面板还留在屏幕里（至少露出 120px 宽 / 56px 高）。 */
export function clampFree(x: number, y: number, w: number, _h: number) {
  return {
    x: clamp(x, 8, Math.max(8, window.innerWidth - Math.min(w, 120))),
    y: clamp(y, 8, Math.max(8, window.innerHeight - 56)),
  };
}

/** 拖动中允许越出屏幕，否则永远拖不到"出界"、也就永远收不起来。 */
export function clampDrag(x: number, y: number, w: number, h: number) {
  return {
    x: clamp(x, -w + 40, window.innerWidth - 40),
    y: clamp(y, -h + 40, window.innerHeight - 40),
  };
}

/** 面板是否已经被拖出视口、该收起成侧边标签了（出界最多的那条边）。 */
export function detectEdge(x: number, y: number, w: number, h: number): Edge | null {
  const vw = window.innerWidth;
  const vh = window.innerHeight;
  const overR = x + w - vw; // >0：右边已经出界
  const overL = -x;
  const overT = -y;
  const overB = y + h - vh;
  const most = Math.max(overR, overL, overT, overB);
  if (most < DOCK_OVERSHOOT) return null;
  if (most === overR) return "right";
  if (most === overL) return "left";
  if (most === overT) return "top";
  return "bottom";
}

/** 收起成标签后，标签沿着那条边放在哪儿（跟随拖动位置，且不跑出屏幕）。 */
export function alongForEdge(edge: Edge, x: number, y: number, _w: number, _h: number) {
  if (edge === "left" || edge === "right") {
    return clamp(y, 8, Math.max(8, window.innerHeight - 140));
  }
  return clamp(x, 8, Math.max(8, window.innerWidth - 140));
}

/** 拖到哪儿、出界多少 —— 给测试和调试看的一步到位版本。 */
export function overflowOf(x: number, y: number, w: number, h: number) {
  return {
    right: x + w - window.innerWidth,
    left: -x,
    top: -y,
    bottom: y + h - window.innerHeight,
  };
}
