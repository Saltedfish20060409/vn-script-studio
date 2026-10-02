/**
 * P5-B：自动 generate_rpy 的 in-flight 锁。
 * 新任务 begin 时 abort 旧任务；旧任务结果不得写回 blocks。
 */

export type AutoRpyJob = {
  id: number;
  chapterId: string;
  prose: string;
  signal: AbortSignal;
};

export type AutoRpyInflight = {
  begin: (chapterId: string, prose: string) => AutoRpyJob;
  isCurrent: (id: number) => boolean;
  hasActive: () => boolean;
  end: (id: number) => void;
  abort: () => void;
};

export function createAutoRpyInflight(): AutoRpyInflight {
  let seq = 0;
  let current: AbortController | null = null;
  let currentId = 0;

  return {
    begin(chapterId: string, prose: string): AutoRpyJob {
      if (current) current.abort();
      const ac = new AbortController();
      current = ac;
      currentId = ++seq;
      return {
        id: currentId,
        chapterId,
        prose,
        signal: ac.signal,
      };
    },
    isCurrent(id: number): boolean {
      return id === currentId && current != null && !current.signal.aborted;
    },
    hasActive(): boolean {
      return current != null && !current.signal.aborted;
    },
    end(id: number): void {
      if (id === currentId) {
        current = null;
      }
    },
    abort(): void {
      if (current) current.abort();
      current = null;
      currentId = 0;
    },
  };
}

/** 区分用户 abort / 超时；abort 不应当成「脚本更新失败」。 */
export function isAutoRpyAbortError(e: unknown): boolean {
  if (!e || typeof e !== "object") return false;
  const name = (e as { name?: string }).name;
  if (name === "AbortError") return true;
  const msg = String((e as { message?: string }).message || "");
  return /aborted|abort/i.test(msg) && !/超时|timeout/i.test(msg);
}
