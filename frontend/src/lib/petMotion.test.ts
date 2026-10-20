import { describe, expect, it } from "vitest";
import {
  CELEBRATE_MS,
  FEED_CELEBRATE_MS,
  celebrateAt,
  createPendulum,
  idleBreathScaleY,
  JUMP_RUNTIME,
  masterPxPerSec,
  stepPendulum,
  swingCssDeg,
} from "./petMotion";

function simulate(speed: number, holdSec: number, afterSec: number) {
  let p = createPendulum();
  const dt = 1 / 120;
  let t = 0;
  let peak = 0;
  while (t < holdSec) {
    p = stepPendulum(p, speed, dt);
    peak = Math.max(peak, Math.abs(swingCssDeg(p)));
    t += dt;
  }
  const stopped = t;
  const tail: Array<{ t: number; a: number }> = [];
  while (t < holdSec + afterSec) {
    p = stepPendulum(p, 0, dt);
    tail.push({ t: t - stopped, a: swingCssDeg(p) });
    t += dt;
  }
  // 和定稿脚本一样：从此刻起一直待在 0.5° 以内，不算中途掠过
  const back = tail.find((_, i) => tail.slice(i).every((s) => Math.abs(s.a) < 0.5))?.t ?? null;
  return { peak, back, angle: swingCssDeg(p) };
}

describe("庆祝时间轴", () => {
  it("总长 2240ms，跳起 60 运行时像素，落地先压扁再回到站立", () => {
    expect(JUMP_RUNTIME).toBe(60);
    expect(celebrateAt(0).body).toBe("idle");
    expect(celebrateAt(399).y).toBe(0);
    const apex = celebrateAt(600);
    expect(apex.body).toBe("happy_jump");
    expect(apex.y).toBeCloseTo(-60, 5);
    const squash = celebrateAt(840);
    expect(squash.body).toBe("happy_land");
    expect(squash.scaleY).toBeCloseTo(0.92, 5);
    expect(celebrateAt(1000).scaleY).toBeCloseTo(1, 5);
    expect(celebrateAt(1480).body).toBe("idle");
    expect(celebrateAt(CELEBRATE_MS).body).toBe("idle");
    expect(celebrateAt(CELEBRATE_MS).scaleY).toBe(1);
  });

  it("喂食短庆祝在 land 静止段截断后回到 idle", () => {
    expect(celebrateAt(FEED_CELEBRATE_MS - 1, FEED_CELEBRATE_MS).body).toBe("happy_land");
    expect(celebrateAt(FEED_CELEBRATE_MS, FEED_CELEBRATE_MS).body).toBe("idle");
    expect(celebrateAt(FEED_CELEBRATE_MS, FEED_CELEBRATE_MS).y).toBe(0);
    expect(celebrateAt(FEED_CELEBRATE_MS, FEED_CELEBRATE_MS).scaleY).toBe(1);
  });
});

describe("拖拽钟摆", () => {
  it("快拖到 12°，停下后约 0.56s 回到 0.5° 以内", () => {
    const fast = simulate(4000, 0.8, 1.2);
    expect(fast.peak).toBeCloseTo(12, 5);
    expect(fast.back).not.toBeNull();
    expect(fast.back!).toBeGreaterThan(0.4);
    expect(fast.back!).toBeLessThan(0.75);
  });

  it("慢拖稳定在 4.5°，停下后约 0.28s 回正", () => {
    let p = createPendulum();
    for (let i = 0; i < 240; i++) p = stepPendulum(p, 500, 1 / 120);
    expect(Math.abs(swingCssDeg(p))).toBeGreaterThan(4);
    expect(Math.abs(swingCssDeg(p))).toBeLessThan(5);
    const slow = simulate(500, 2, 1);
    expect(slow.back).not.toBeNull();
    expect(slow.back!).toBeGreaterThan(0.15);
    expect(slow.back!).toBeLessThan(0.45);
  });

  it("往右拖时角度为正（脚往左甩）", () => {
    let p = createPendulum();
    for (let i = 0; i < 30; i++) p = stepPendulum(p, 800, 1 / 60);
    expect(swingCssDeg(p)).toBeGreaterThan(0);
  });
});

describe("速度换算", () => {
  it("显示缩放 0.4 时，1 CSS 像素对应 6 母版像素", () => {
    expect(masterPxPerSec(1, 1000, 0.4)).toBeCloseTo(6, 5);
  });
});

describe("待机呼吸", () => {
  it("约 3.2s 一周期，幅度 ±1.8%", () => {
    expect(idleBreathScaleY(0)).toBeCloseTo(1, 5);
    expect(idleBreathScaleY(800)).toBeCloseTo(1.018, 5);
    expect(idleBreathScaleY(1600)).toBeCloseTo(1, 5);
    expect(idleBreathScaleY(2400)).toBeCloseTo(0.982, 5);
    expect(idleBreathScaleY(3200)).toBeCloseTo(1, 5);
  });
});
