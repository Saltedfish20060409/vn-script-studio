import { describe, expect, it } from "vitest";
import {
  LN_FEATURES,
  LN_QUICK_START_FAQ,
  LN_QUICK_START_INTRO,
  LN_QUICK_START_STEPS,
  LN_QUICK_START_TITLE,
  LN_SURFACES,
  LN_VN_JARGON,
  type LnQuickStartStep,
} from "./lnQuickStart";

/** 命中这些词的文案要改（大小写不敏感）——轻小说上手指引不该先教另一套术语。 */
function jargonHits(text: string): string[] {
  const lower = text.toLowerCase();
  return LN_VN_JARGON.filter((word) => lower.includes(word.toLowerCase()));
}

/** 一步里所有给作者看的文案（id 是程序用的，不参与文案检查）。 */
function stepCopy(step: LnQuickStartStep): string {
  return [step.title, step.where, step.what, step.why, step.pitfall ?? ""].join("\n");
}

function hitSurfaces(text: string): string[] {
  return LN_SURFACES.filter((surface) => text.includes(surface));
}

function hitFeatures(text: string): string[] {
  return LN_FEATURES.filter((feature) => text.includes(feature));
}

describe("轻小说上手指引：步骤结构", () => {
  it("是 6–9 步，id 唯一且是 kebab-case", () => {
    expect(LN_QUICK_START_STEPS.length).toBeGreaterThanOrEqual(6);
    expect(LN_QUICK_START_STEPS.length).toBeLessThanOrEqual(9);

    const ids = LN_QUICK_START_STEPS.map((s) => s.id);
    expect(new Set(ids).size).toBe(ids.length);
    for (const id of ids) {
      expect(id).toMatch(/^[a-z][a-z0-9-]*$/);
    }
  });

  it("每一步都有标题、面板指向、会发生什么、为什么", () => {
    for (const step of LN_QUICK_START_STEPS) {
      expect(step.title.trim().length, step.id).toBeGreaterThan(0);
      expect(step.where.trim().length, step.id).toBeGreaterThan(0);
      expect(step.what.trim().length, step.id).toBeGreaterThan(0);
      expect(step.why.trim().length, step.id).toBeGreaterThan(0);
    }
  });

  it("why 是「一句话」，不是一小段", () => {
    for (const step of LN_QUICK_START_STEPS) {
      expect(step.why.length, step.id).toBeLessThanOrEqual(70);
      expect(step.why.endsWith("。"), step.id).toBe(true);
    }
  });

  it("标题各不相同，且没有一个标题是重复的占位符", () => {
    const titles = LN_QUICK_START_STEPS.map((s) => s.title);
    expect(new Set(titles).size).toBe(titles.length);
    for (const title of titles) {
      expect(title).not.toMatch(/^(待定|TODO|步骤\d*)$/);
    }
  });

  it("大部分步骤都写了常见误区（写了就不能是空话）", () => {
    const withPitfall = LN_QUICK_START_STEPS.filter((s) => (s.pitfall ?? "").trim());
    expect(withPitfall.length).toBeGreaterThanOrEqual(6);
    for (const step of withPitfall) {
      expect((step.pitfall ?? "").length, step.id).toBeGreaterThanOrEqual(10);
    }
  });
});

describe("轻小说上手指引：每一步都指得到真实界面", () => {
  it("每一步的 where 至少命中一个真实界面位置", () => {
    for (const step of LN_QUICK_START_STEPS) {
      expect(hitSurfaces(step.where), step.id).not.toHaveLength(0);
    }
  });

  it("九步合起来覆盖了足够多的界面位置（不是九步都指向同一个页面）", () => {
    const covered = new Set(LN_QUICK_START_STEPS.flatMap((s) => hitSurfaces(s.where)));
    expect(covered.size).toBeGreaterThanOrEqual(6);
  });

  it("界面位置清单本身要像话（否则上面两条等于没查）", () => {
    expect(LN_SURFACES.length).toBeGreaterThanOrEqual(6);
    for (const surface of LN_SURFACES) {
      expect(surface.trim().length).toBeGreaterThan(2);
      expect(jargonHits(surface)).toHaveLength(0);
    }
    // 稿纸与文件菜单是轻小说作者最常待的两处，必须都在清单里
    expect(LN_SURFACES.some((s) => s.includes("左侧大纲") || s.includes("「开始」"))).toBe(
      true
    );
    expect(LN_SURFACES.some((s) => s.includes("「文件」"))).toBe(true);
  });

  it("每一步都说了点完会发生什么（不能只写去哪点）", () => {
    for (const step of LN_QUICK_START_STEPS) {
      expect(step.what.length, step.id).toBeGreaterThanOrEqual(20);
      expect(step.what, step.id).not.toBe(step.where);
    }
  });
});

describe("轻小说上手指引：文案里不出现视觉小说专有词", () => {
  it("专有词清单本身不能是空的（否则这条守卫形同虚设）", () => {
    expect(LN_VN_JARGON.length).toBeGreaterThanOrEqual(5);
    const words = LN_VN_JARGON.map((w) => w.toLowerCase());
    expect(words).toContain("rpy");
    expect(words).toContain("menu");
  });

  it("九步的文案里一个专有词都没有", () => {
    for (const step of LN_QUICK_START_STEPS) {
      expect(jargonHits(stepCopy(step)), step.id).toHaveLength(0);
    }
  });

  it("FAQ、标题与开场白里也没有", () => {
    expect(jargonHits(LN_QUICK_START_TITLE)).toHaveLength(0);
    expect(jargonHits(LN_QUICK_START_INTRO)).toHaveLength(0);
    for (const item of LN_QUICK_START_FAQ) {
      expect(jargonHits(item.q), item.q).toHaveLength(0);
      expect(jargonHits(item.a), item.q).toHaveLength(0);
    }
  });
});

describe("轻小说上手指引：FAQ 基于真实能力", () => {
  it("是 3–5 条，问答都不空", () => {
    expect(LN_QUICK_START_FAQ.length).toBeGreaterThanOrEqual(3);
    expect(LN_QUICK_START_FAQ.length).toBeLessThanOrEqual(5);
    for (const item of LN_QUICK_START_FAQ) {
      expect(item.q.trim().length).toBeGreaterThan(0);
      expect(item.a.trim().length).toBeGreaterThan(0);
    }
  });

  it("答案是真的答案（不是「敬请期待」这类占位）", () => {
    for (const item of LN_QUICK_START_FAQ) {
      expect(item.a.length, item.q).toBeGreaterThanOrEqual(40);
      expect(item.a, item.q).not.toMatch(/敬请期待|即将上线|暂不支持|以后再说/);
    }
  });

  it("每条答案都点到本工具真有的能力（不许承诺没有的功能）", () => {
    for (const item of LN_QUICK_START_FAQ) {
      expect(hitFeatures(item.a), item.q).not.toHaveLength(0);
    }
  });

  it("能力清单本身要像话", () => {
    expect(LN_FEATURES.length).toBeGreaterThanOrEqual(5);
    for (const feature of LN_FEATURES) {
      expect(feature.trim().length).toBeGreaterThan(1);
      expect(jargonHits(feature)).toHaveLength(0);
    }
  });

  it("问题不重复", () => {
    const qs = LN_QUICK_START_FAQ.map((f) => f.q);
    expect(new Set(qs).size).toBe(qs.length);
  });
});
