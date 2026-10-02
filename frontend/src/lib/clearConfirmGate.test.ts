import { describe, expect, it, vi } from "vitest";
import {
  createClearConfirmLock,
  resolveClearCancelRestoreText,
} from "./clearConfirmGate";

describe("clearConfirmGate 防连弹锁", () => {
  it("连弹：第二次 join 同一 in-flight，不新开一轮", async () => {
    const lock = createClearConfirmLock();
    let starts = 0;
    const first = lock.joinOrStart(async () => {
      starts += 1;
      await new Promise((r) => setTimeout(r, 30));
      return "ok";
    });
    expect(lock.isInFlight()).toBe(true);
    const second = lock.joinOrStart(async () => {
      starts += 1;
      return "other";
    });
    expect(starts).toBe(1);
    await expect(Promise.all([first, second])).resolves.toEqual(["ok", "ok"]);
    expect(lock.isInFlight()).toBe(false);
  });

  it("第二次真实操作：上一轮结束后可再开新确认", async () => {
    const lock = createClearConfirmLock();
    await lock.joinOrStart(async () => "a");
    expect(lock.isInFlight()).toBe(false);
    const spy = vi.fn(async () => "b");
    await expect(lock.joinOrStart(spy)).resolves.toBe("b");
    expect(spy).toHaveBeenCalledTimes(1);
  });
});

describe("clearConfirmGate 取消恢复语义", () => {
  it("优先恢复清空前编辑器非空缓冲（含未落盘改动）", () => {
    expect(
      resolveClearCancelRestoreText({
        lastNonEmptyEditor: "编辑器里刚改的稿",
        savedSurfaceText: "存盘旧稿",
      })
    ).toBe("编辑器里刚改的稿");
  });

  it("没有非空缓冲时回落存盘当前面", () => {
    expect(
      resolveClearCancelRestoreText({
        lastNonEmptyEditor: "   ",
        savedSurfaceText: "存盘旧稿",
      })
    ).toBe("存盘旧稿");
  });
});
