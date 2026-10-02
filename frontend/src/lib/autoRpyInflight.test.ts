import { describe, expect, it } from "vitest";
import {
  createAutoRpyInflight,
  isAutoRpyAbortError,
} from "./autoRpyInflight";

describe("createAutoRpyInflight", () => {
  it("连续两次 begin：旧 signal abort，只有新任务存活", () => {
    const lock = createAutoRpyInflight();
    const a = lock.begin("ch1", "正文甲");
    expect(lock.isCurrent(a.id)).toBe(true);
    expect(a.signal.aborted).toBe(false);

    const b = lock.begin("ch1", "正文乙");
    expect(a.signal.aborted).toBe(true);
    expect(lock.isCurrent(a.id)).toBe(false);
    expect(lock.isCurrent(b.id)).toBe(true);
    expect(b.signal.aborted).toBe(false);
    expect(lock.hasActive()).toBe(true);
  });

  it("旧任务 end 不影响新任务", () => {
    const lock = createAutoRpyInflight();
    const a = lock.begin("ch1", "a");
    const b = lock.begin("ch1", "b");
    lock.end(a.id);
    expect(lock.isCurrent(b.id)).toBe(true);
    expect(lock.hasActive()).toBe(true);
    lock.end(b.id);
    expect(lock.hasActive()).toBe(false);
    expect(lock.isCurrent(b.id)).toBe(false);
  });

  it("abort 清空 in-flight", () => {
    const lock = createAutoRpyInflight();
    const a = lock.begin("ch1", "a");
    lock.abort();
    expect(a.signal.aborted).toBe(true);
    expect(lock.hasActive()).toBe(false);
  });

  it("被 abort 的任务若仍写回会被 isCurrent 拦住", () => {
    const lock = createAutoRpyInflight();
    const a = lock.begin("ch1", "旧");
    const writes: string[] = [];
    const b = lock.begin("ch1", "新");
    // 模拟旧任务晚到
    if (lock.isCurrent(a.id)) writes.push("a");
    if (lock.isCurrent(b.id)) writes.push("b");
    expect(writes).toEqual(["b"]);
  });
});

describe("isAutoRpyAbortError", () => {
  it("识别 AbortError", () => {
    expect(isAutoRpyAbortError(new DOMException("Aborted", "AbortError"))).toBe(
      true
    );
    expect(isAutoRpyAbortError(new Error("请求超时"))).toBe(false);
  });
});
