import { describe, expect, it } from "vitest";
import { tzOffsetMinutes } from "./http";

/**
 * 时区偏移头（X-TZ-Offset）。
 *
 * 这个值决定"今天写的字算哪一天"：后端按作者当地日期写 `writing_activity`，
 * 而连载页用本地日期查。符号搞反或范围离谱，表现都是"今天写的字不见了"——
 * 那种 bug 在界面上极难自查，所以这里把符号约定钉住。
 */
describe("tzOffsetMinutes", () => {
  it("符号与 ISO 一致：UTC+8 是 +480（不是 -480）", () => {
    // 构造一个"本地时区是 UTC+8"的等价断言：getTimezoneOffset 返回 -480 时
    // tzOffsetMinutes 必须是 +480。直接伪造 Date 的子类来固定这个行为。
    class FakeDate extends Date {
      getTimezoneOffset(): number {
        return -480;
      }
    }
    expect(tzOffsetMinutes(new FakeDate())).toBe(480);
  });

  it("西五区得到 -300", () => {
    class FakeDate extends Date {
      getTimezoneOffset(): number {
        return 300;
      }
    }
    expect(tzOffsetMinutes(new FakeDate())).toBe(-300);
  });

  it("真实环境下是整数且在现实范围内（-12h..+14h）", () => {
    const value = tzOffsetMinutes();
    expect(Number.isInteger(value)).toBe(true);
    expect(value).toBeGreaterThanOrEqual(-12 * 60);
    expect(value).toBeLessThanOrEqual(14 * 60);
    // 与浏览器自身的约定一致
    expect(value).toBe(-new Date().getTimezoneOffset());
  });

  it("45 分钟制时区（尼泊尔 +5:45）也是整数分钟", () => {
    class FakeDate extends Date {
      getTimezoneOffset(): number {
        return -345;
      }
    }
    expect(tzOffsetMinutes(new FakeDate())).toBe(345);
  });
});
