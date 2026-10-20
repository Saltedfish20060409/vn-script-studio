/**
 * 平台宿主接口：Web 浮层 / Tauri / Capacitor 各自实现。
 * 纯逻辑（状态机、台词）不依赖本接口；只有渲染与副作用层注入。
 */

export type PetStorageScope = "settings" | "memory" | "affinity";

export interface PetHostViewport {
  width: number;
  height: number;
  /** 刘海 / 手势条等，CSS px */
  safe: { top: number; right: number; bottom: number; left: number };
  /** 是否允许点击穿透到下层桌面/应用 */
  canClickThrough: boolean;
}

export interface PetHostLlmRequest {
  system: string;
  user: string;
  /** 已勾选可注入的记忆摘要 */
  memorySnippets?: string[];
  signal?: AbortSignal;
}

export interface PetHost {
  viewport(): PetHostViewport;
  /** 透明窗：宿主应使用可镂空表面；Web 上至少保证 canvas/img 不铺不透明底 */
  setClickThrough?(enabled: boolean): void;
  storageGet(scope: PetStorageScope, key: string): Promise<string | null>;
  storageSet(scope: PetStorageScope, key: string, value: string): Promise<void>;
  storageClear?(scope: PetStorageScope): Promise<void>;
  /** 未配置 key 时返回 null，调用方走固定台词池 */
  llmComplete?(req: PetHostLlmRequest): Promise<string | null>;
  /** 省电：进入后台时宿主应停止 RAF / 游戏循环 */
  onVisibility?(cb: (visible: boolean) => void): () => void;
}

/** 浏览器最小实现：供独立壳 Phase 1 使用 */
export function createWebPetHost(): PetHost {
  const prefix = "desk-pet:";
  return {
    viewport() {
      const w = window.innerWidth;
      const h = window.innerHeight;
      return {
        width: w,
        height: h,
        safe: { top: 0, right: 0, bottom: 0, left: 0 },
        canClickThrough: false,
      };
    },
    async storageGet(scope, key) {
      try {
        return localStorage.getItem(`${prefix}${scope}:${key}`);
      } catch {
        return null;
      }
    },
    async storageSet(scope, key, value) {
      try {
        localStorage.setItem(`${prefix}${scope}:${key}`, value);
      } catch {
        /* quota */
      }
    },
    async storageClear(scope) {
      const head = `${prefix}${scope}:`;
      const keys: string[] = [];
      for (let i = 0; i < localStorage.length; i++) {
        const k = localStorage.key(i);
        if (k?.startsWith(head)) keys.push(k);
      }
      for (const k of keys) localStorage.removeItem(k);
    },
    onVisibility(cb) {
      const fn = () => cb(!document.hidden);
      document.addEventListener("visibilitychange", fn);
      return () => document.removeEventListener("visibilitychange", fn);
    },
  };
}
