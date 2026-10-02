/**
 * 清空两面确认闸的可测辅助：防连弹锁 + 取消时恢复文案。
 *
 * 锁不是定时器窗口：从弹出确认到用户点确认/取消（或 finally）整段持有；
 * 并发调用应 join 同一 in-flight Promise，而不是再弹一次或静默 return null。
 */

export type ClearConfirmLock = {
  /** 若已有进行中的确认，返回该 Promise；否则用 `start` 开新一轮。 */
  joinOrStart: <T>(start: () => Promise<T>) => Promise<T>;
  /** 当前是否有确认在飞（测试用）。 */
  isInFlight: () => boolean;
};

/** 创建确认锁：窗口期 = 单次弹窗生命周期（无固定毫秒）。 */
export function createClearConfirmLock(): ClearConfirmLock {
  let inFlight: Promise<unknown> | null = null;
  return {
    joinOrStart<T>(start: () => Promise<T>): Promise<T> {
      if (inFlight) return inFlight as Promise<T>;
      const p = start().finally(() => {
        if (inFlight === p) inFlight = null;
      });
      inFlight = p;
      return p;
    },
    isInFlight: () => inFlight !== null,
  };
}

/**
 * 取消「清两面」时写回编辑器的文本：
 * 优先「清空前编辑器里最后一次非空缓冲」（含未落盘改动）；
 * 若没有，再回落到存盘当前面（`inspectClearImpact.restoreText`）。
 *
 * 含义 = **放弃本次清空，恢复到清空前的编辑内容**（不是保留空编辑器）。
 */
export function resolveClearCancelRestoreText(opts: {
  lastNonEmptyEditor: string;
  savedSurfaceText: string;
}): string {
  const live = opts.lastNonEmptyEditor;
  if (live.trim()) return live;
  return opts.savedSurfaceText;
}
