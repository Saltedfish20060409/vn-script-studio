/**
 * 渠道归因测试：首次归因 + 90 天过期 + 非法值忽略。
 */
import { beforeEach, describe, expect, it, vi } from "vitest";

import { __resetRefForTest, captureRef, getRef } from "./refSource";

function mockLocation(search: string) {
  vi.stubGlobal("window", { location: { search } });
}

const store = new Map<string, string>();

beforeEach(() => {
  store.clear();
  __resetRefForTest();
  vi.stubGlobal("window", { location: { search: "" } });
  vi.stubGlobal("localStorage", {
    getItem: (k: string) => (store.has(k) ? (store.get(k) as string) : null),
    setItem: (k: string, v: string) => void store.set(k, String(v)),
    removeItem: (k: string) => void store.delete(k),
  });
});

describe("refSource", () => {
  it("记录首次来源", () => {
    mockLocation("?ref=bili");
    captureRef();
    expect(getRef()).toBe("bili");
  });

  it("已有来源时不被后来的链接覆盖（首次归因）", () => {
    mockLocation("?ref=bili");
    captureRef();
    mockLocation("?ref=douyin");
    captureRef();
    expect(getRef()).toBe("bili");
  });

  it("忽略非法 ref（空格 / 中文 / 特殊符号）", () => {
    mockLocation("?ref=has%20space");
    captureRef();
    expect(getRef()).toBeUndefined();

    mockLocation("?ref=%E4%B8%AD%E6%96%87");
    captureRef();
    expect(getRef()).toBeUndefined();

    mockLocation("?ref=a%3Bb");
    captureRef();
    expect(getRef()).toBeUndefined();
  });

  it("没有 ref 参数时保持空", () => {
    mockLocation("?foo=1");
    captureRef();
    expect(getRef()).toBeUndefined();
  });

  it("大于 90 天视为过期", () => {
    mockLocation("?ref=bili");
    captureRef();
    const old = Date.now() - 91 * 24 * 3600 * 1000;
    store.set("vnss-ref-at", String(old));
    expect(getRef()).toBeUndefined();
  });

  it("大小写归一化为小写", () => {
    mockLocation("?ref=DouYin");
    captureRef();
    expect(getRef()).toBe("douyin");
  });
});
