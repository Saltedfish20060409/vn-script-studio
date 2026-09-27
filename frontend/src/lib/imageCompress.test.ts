/**
 * 背景图自动压缩：**纯逻辑**那一半（canvas 那段挡在浏览器 API 后面，见 vitest.config.ts）。
 *
 * 钉的是线上那个事故的判据：11.8 MB 的图 → data URL 15.7 MB → nginx 3m 直接 413，
 * 而且因为每次保存设置都会重发整张图，本地挂着巨图时**每次**改设置都失败。
 * 所以"多大需要压""压到哪一档""压完还是太大怎么说"这三件事必须可测。
 */
import { describe, expect, it } from "vitest";

import {
  ATTEMPTS,
  BUDGET_BYTES,
  MAX_EDGE,
  autoCompressedNote,
  bgImageNote,
  dataUrlBytes,
  estimateDataUrlBytes,
  formatBytes,
  scaledSize,
  shouldCompress,
  stillTooLargeNote,
  unreadableImageNote,
} from "./imageCompress";

describe("体积估算", () => {
  it("base64 膨胀按 4/3 算，再加前缀开销", () => {
    // 1 MB 的图 → data URL 约 1.33 MB
    const est = estimateDataUrlBytes(1_048_576);
    expect(est).toBeGreaterThan(1_300_000);
    expect(est).toBeLessThan(1_400_000);
  });

  it("异常输入不炸：0 / 负数 / NaN 都算 0", () => {
    expect(estimateDataUrlBytes(0)).toBe(48);
    expect(estimateDataUrlBytes(-5)).toBe(48);
    expect(estimateDataUrlBytes(Number.NaN)).toBe(48);
  });

  it("dataUrlBytes 数的是字节：ASCII 一字节、中文三字节、代理对四字节", () => {
    expect(dataUrlBytes("abc")).toBe(3);
    expect(dataUrlBytes("背")).toBe(3);
    expect(dataUrlBytes("🎨")).toBe(4); // 代理对
  });
});

describe("shouldCompress：只在预计塞不下时才压", () => {
  it("线上那张 11.8 MB 的图必须被判为需要压缩", () => {
    const elevenMb = 11_800_000;
    expect(estimateDataUrlBytes(elevenMb)).toBeGreaterThan(15_000_000); // 与 nginx 日志的 15,722,643 同量级
    expect(shouldCompress(elevenMb)).toBe(true);
  });

  it("小图不压：免得为一次没必要的转码把 SVG 变位图、把动图压成静帧", () => {
    expect(shouldCompress(120_000)).toBe(false); // 约 120 KB
    expect(shouldCompress(300_000)).toBe(false);
  });

  it("预算边界：刚好超过才压", () => {
    const budget = BUDGET_BYTES;
    // 反推：budget 对应的文件原大小
    const fileAtBudget = Math.floor(((budget - 48) * 3) / 4);
    expect(shouldCompress(fileAtBudget, budget)).toBe(false);
    expect(shouldCompress(fileAtBudget + 4096, budget)).toBe(true);
  });

  it("预算留出了 nginx 3m 的余量（否则压完还是会被 413）", () => {
    expect(BUDGET_BYTES).toBeLessThan(3 * 1024 * 1024);
    expect(BUDGET_BYTES).toBeGreaterThan(1_000_000);
  });
});

describe("scaledSize：只缩不放", () => {
  it("长边超限时等比缩到上限", () => {
    expect(scaledSize(8000, 6000, 3200)).toEqual({ width: 3200, height: 2400 });
    expect(scaledSize(6000, 8000, 3200)).toEqual({ width: 2400, height: 3200 });
  });

  it("本来就在限内 → 原样", () => {
    expect(scaledSize(1920, 1080, MAX_EDGE)).toEqual({ width: 1920, height: 1080 });
    expect(scaledSize(3200, 2000, MAX_EDGE)).toEqual({ width: 3200, height: 2000 });
  });

  it("不放大小图", () => {
    expect(scaledSize(100, 80, 3200)).toEqual({ width: 100, height: 80 });
  });

  it("极端长条不会缩成 0 高（canvas 会报错）", () => {
    const out = scaledSize(10000, 3, 3200);
    expect(out.width).toBe(3200);
    expect(out.height).toBeGreaterThanOrEqual(1);
  });

  it("0 尺寸不炸", () => {
    expect(scaledSize(0, 0, 3200)).toEqual({ width: 0, height: 0 });
  });
});

describe("压缩阶梯", () => {
  it("先降质量再降尺寸：壁纸最怕糊，其次才是压缩伪影", () => {
    const firstEdge = ATTEMPTS[0].maxEdge;
    const edgeDropIndex = ATTEMPTS.findIndex((a) => a.maxEdge < firstEdge);
    expect(edgeDropIndex).toBeGreaterThan(0);
    // 降尺寸之前必须先试过更低的 quality
    const beforeEdgeDrop = ATTEMPTS.slice(0, edgeDropIndex);
    expect(beforeEdgeDrop.length).toBeGreaterThanOrEqual(2);
    expect(beforeEdgeDrop[0].quality).toBeGreaterThan(
      beforeEdgeDrop[beforeEdgeDrop.length - 1].quality
    );
  });

  it("质量与尺寸都单调不增（否则会出现「试了更差的一档却更大」的白跑）", () => {
    for (let i = 1; i < ATTEMPTS.length; i += 1) {
      expect(ATTEMPTS[i].maxEdge).toBeLessThanOrEqual(ATTEMPTS[i - 1].maxEdge);
      expect(ATTEMPTS[i].quality).toBeLessThanOrEqual(ATTEMPTS[i - 1].quality);
    }
  });

  it("最后一档要足够小，保证一定塞得下的余地", () => {
    expect(ATTEMPTS[ATTEMPTS.length - 1].maxEdge).toBeLessThanOrEqual(1280);
  });
});

describe("提示文案", () => {
  it("formatBytes 用人能读的单位", () => {
    expect(formatBytes(0)).toBe("0 KB");
    expect(formatBytes(1536)).toBe("2 KB");
    expect(formatBytes(11_800_000)).toBe("11.3 MB");
    expect(formatBytes(480_000)).toBe("469 KB");
  });

  it("压缩过就要说：静默压缩会让人以为图被弄糊了", () => {
    const note = autoCompressedNote(11_800_000, 700_000);
    expect(note).toContain("11.3 MB");
    expect(note).toContain("自动压缩");
  });

  it("压到底还是太大 → 如实说，不假装成功", () => {
    const note = stillTooLargeNote(3_000_000, BUDGET_BYTES);
    expect(note).toContain("压缩后仍有");
    expect(note).toContain("2.4 MB"); // 预算
  });

  it("解码失败给一句人话，不是把 HTML/异常原文甩出去", () => {
    expect(unreadableImageNote()).toContain("换一张");
  });

  it("bgImageNote 空值不显示", () => {
    expect(bgImageNote("")).toBe("");
    expect(bgImageNote("data:image/webp;base64,AAAA")).toContain("当前背景约");
  });
});
