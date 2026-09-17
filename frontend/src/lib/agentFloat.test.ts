import { beforeEach, describe, expect, it, vi } from "vitest";
import {
  DOCK_OVERSHOOT,
  alongForEdge,
  clampDrag,
  clampFree,
  detectEdge,
  overflowOf,
} from "./agentFloat";

/**
 * AI 责编浮窗的贴边判定。
 *
 * 用户反馈过："把边框拉到比较接近侧边、但还没碰到，面板就缩成标签了"。
 * 所以这里的核心断言是：**只是靠近边缘 → 不收起；真的拖出视口 → 才收起**。
 */

const VW = 1280;
const VH = 800;
const W = 560;
const H = 560;

beforeEach(() => {
  vi.stubGlobal("window", { innerWidth: VW, innerHeight: VH });
});

describe("detectEdge：什么时候收起成侧边标签", () => {
  it("面板完全在屏幕里 → 不收起（不管离边多近）", () => {
    // 贴着右边但没出界：右边缘正好在 vw - 1
    expect(detectEdge(VW - W - 1, 100, W, H)).toBeNull();
    // 只差 8px 就出界，仍然不收起（以前 EDGE_SNAP=56 时这里就会缩成标签）
    expect(detectEdge(VW - W - 8, 100, W, H)).toBeNull();
    expect(detectEdge(8, 8, W, H)).toBeNull();
    expect(detectEdge(300, 100, W, H)).toBeNull();
  });

  it("越过边界一点点（小于余量）→ 还不收起，避免手抖就缩起来", () => {
    expect(detectEdge(VW - W + (DOCK_OVERSHOOT - 1), 100, W, H)).toBeNull();
    expect(detectEdge(-(DOCK_OVERSHOOT - 1), 100, W, H)).toBeNull();
  });

  it("真的拖出视口 → 按出界最多的那条边收起", () => {
    expect(detectEdge(VW - W + DOCK_OVERSHOOT, 100, W, H)).toBe("right");
    expect(detectEdge(-DOCK_OVERSHOOT, 100, W, H)).toBe("left");
    expect(detectEdge(100, -DOCK_OVERSHOOT, W, H)).toBe("top");
    expect(detectEdge(100, VH - H + DOCK_OVERSHOOT, W, H)).toBe("bottom");
  });

  it("两条边都出界时，取出界更多的那条（用户拖向的那个角）", () => {
    // 右边出界 400，下边出界 20 → 判为右边
    expect(detectEdge(VW - W + 400, VH - H + 20, W, H)).toBe("right");
    // 下边出界更多 → 判为下边
    expect(detectEdge(VW - W + 20, VH - H + 400, W, H)).toBe("bottom");
  });

  it("拖到几乎全出屏幕也能判出来（clampDrag 允许的最远位置）", () => {
    const far = clampDrag(VW + 9999, 100, W, H);
    expect(detectEdge(far.x, far.y, W, H)).toBe("right");
    const farLeft = clampDrag(-9999, 100, W, H);
    expect(detectEdge(farLeft.x, farLeft.y, W, H)).toBe("left");
  });

  it("overflowOf 与 detectEdge 的判定一致（出界数值对得上）", () => {
    const over = overflowOf(VW - W + 30, 100, W, H);
    expect(over.right).toBe(30);
    expect(Math.max(over.right, over.left, over.top, over.bottom)).toBe(30);
  });
});

describe("拖动夹取", () => {
  it("拖动中允许拖出屏幕（否则永远收不起来）", () => {
    expect(clampDrag(VW + 500, -500, W, H)).toEqual({ x: VW - 40, y: -500 });
    // 往上拖到底：y 最多到 -(H - 40)，也就是留 40px 在屏幕里
    expect(clampDrag(0, -9999, W, H).y).toBe(-H + 40);
  });

  it("静止位置仍留在屏幕里（至少露出 120px 宽）", () => {
    const p = clampFree(VW + 500, VH + 500, W, H);
    expect(p.x).toBe(VW - 120);
    expect(p.y).toBe(VH - 56);
  });
});

describe("收起后标签的位置", () => {
  it("左右边：标签跟着纵向拖到哪就停在哪，且不跑出屏幕", () => {
    expect(alongForEdge("right", 100, 320, W, H)).toBe(320);
    expect(alongForEdge("right", 100, -50, W, H)).toBe(8);
    expect(alongForEdge("left", 100, VH + 50, W, H)).toBe(VH - 140);
  });

  it("上下边：标签跟着横向位置", () => {
    expect(alongForEdge("bottom", 240, 100, W, H)).toBe(240);
    expect(alongForEdge("top", VW + 90, 100, W, H)).toBe(VW - 140);
  });
});
