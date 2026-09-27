import { describe, expect, it } from "vitest";
import {
  GENRE_MAX,
  TITLE_MAX,
  isOverLimit,
  overLimitHint,
} from "./fieldLimits";

describe("字段长度上限（前端的门）", () => {
  it("数字与后端一致：1 个字都不许松（松了用户就白打一遍再吃 400）", () => {
    // 与 backend/app/core/field_limits.py 对应；后端另有一条测试核对两边
    expect(TITLE_MAX).toBe(255);
    expect(GENRE_MAX).toBe(128);
  });

  it("边界：正好到上限算通过", () => {
    expect(isOverLimit("字".repeat(GENRE_MAX), GENRE_MAX)).toBe(false);
    expect(isOverLimit("字".repeat(GENRE_MAX + 1), GENRE_MAX)).toBe(true);
    expect(isOverLimit("", GENRE_MAX)).toBe(false);
  });

  it("提醒里要说清三个数：现在多少、上限多少、要删多少", () => {
    const value = "长".repeat(GENRE_MAX + 7);
    const hint = overLimitHint("类型 / 题材", value, GENRE_MAX);
    expect(hint).toContain(String(GENRE_MAX + 7));
    expect(hint).toContain(String(GENRE_MAX));
    expect(hint).toContain("7");
    // 必须告诉用户"保存会被拒绝"，否则他不知道为什么保存没成功
    expect(hint).toContain("拒绝");
  });
});
