/**
 * 「模型上下文窗口」设置项的输入口径。
 *
 * 要钉住的三件事：
 * 1. **留空 = 自动**（0），不合法输入要报错而不是悄悄变成 0——否则用户以为填上了；
 * 2. 已知模型时声明**只能调低**，提示文案必须说清（不然用户会以为能超过厂商窗口）；
 * 3. 本机存储模式下这项不生效，要如实说明（它是账号级设置）。
 */
import { describe, expect, it } from "vitest";

import { parseWindowK, readDeclaredK, windowHintText } from "./modelWindow";

describe("parseWindowK", () => {
  it("留空或 0 都表示自动", () => {
    expect(parseWindowK("")).toEqual({ value: 0, error: "" });
    expect(parseWindowK("   ")).toEqual({ value: 0, error: "" });
    expect(parseWindowK("0")).toEqual({ value: 0, error: "" });
  });

  it("正整数按千 token 解析", () => {
    expect(parseWindowK("128")).toEqual({ value: 128, error: "" });
    expect(parseWindowK(" 32 ")).toEqual({ value: 32, error: "" });
  });

  it("含糊输入直接报错，不替用户猜", () => {
    expect(parseWindowK("32k").error).toContain("只填数字");
    expect(parseWindowK("3.2万").error).toContain("只填数字");
    expect(parseWindowK("-1").error).toContain("只填数字");
    expect(parseWindowK("abc").error).not.toBe("");
  });

  it("超大值夹到上限并说明", () => {
    const out = parseWindowK("999999");
    expect(out.value).toBe(10000);
    expect(out.error).toContain("上限");
  });
});

describe("windowHintText", () => {
  it("本机存储模式下如实说这项不生效", () => {
    expect(windowHintText({ declaredK: 128, localStorage: true })).toContain("只在");
  });

  it("已知模型 + 声明更小：按声明夹", () => {
    const hint = windowHintText({ declaredK: 32, presetK: 1000 });
    expect(hint).toContain("32k");
    expect(hint).toContain("更小");
  });

  it("已知模型 + 声明更大：说明只能调低", () => {
    const hint = windowHintText({ declaredK: 2000, presetK: 1000 });
    expect(hint).toContain("只能调低");
    expect(hint).toContain("1000k");
  });

  it("未知模型填了就以它为准", () => {
    const hint = windowHintText({ declaredK: 64, presetK: null });
    expect(hint).toContain("64k");
    expect(hint).toContain("自定义模型");
  });

  it("留空时给出自动规则（有预设 / 无预设两种说法）", () => {
    expect(windowHintText({ declaredK: 0, presetK: 200 })).toContain("预设 200k");
    expect(windowHintText({ declaredK: 0, presetK: null })).toContain("保守假设");
  });
});

describe("readDeclaredK", () => {
  it("缺字段/非法一律当没声明", () => {
    expect(readDeclaredK(undefined)).toBe(0);
    expect(readDeclaredK(null)).toBe(0);
    expect(readDeclaredK("abc")).toBe(0);
    expect(readDeclaredK(-5)).toBe(0);
    expect(readDeclaredK(0)).toBe(0);
  });

  it("合法值取整并夹上限", () => {
    expect(readDeclaredK(128)).toBe(128);
    expect(readDeclaredK("64")).toBe(64);
    expect(readDeclaredK(999999)).toBe(10000);
  });
});
