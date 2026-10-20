/**
 * 桌宠状态：开关 + 屏幕位置 + 自主间隔（像素，视口坐标）持久化。
 * 与设置页共享；位置变化不触发设置同步，仅本地。
 */

export interface DeskPetPos {
  x: number; // px from left
  y: number; // px from top
}

/** normal 8–20s；calm 20–45s；off 不游走不蜷不闲聊 */
export type PetWanderInterval = "normal" | "calm" | "off";

const KEY = "vnss-deskpet-v1";
const DEFAULT_POS: DeskPetPos = { x: 0, y: 0 }; // 0,0 → 右下角默认停靠

function defaultEnabled(): boolean {
  if (typeof window === "undefined") return false;
  return window.innerWidth >= 768;
}

function loadDeskPet(): {
  enabled: boolean;
  pos: DeskPetPos;
  wanderInterval: PetWanderInterval;
} {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) {
      return { enabled: defaultEnabled(), pos: DEFAULT_POS, wanderInterval: "normal" };
    }
    const p = JSON.parse(raw) as Partial<{
      enabled: boolean;
      x: number;
      y: number;
      wanderInterval: PetWanderInterval;
    }>;
    const wander =
      p.wanderInterval === "calm" || p.wanderInterval === "off" || p.wanderInterval === "normal"
        ? p.wanderInterval
        : "normal";
    return {
      // 有旧记录：尊重用户勾选；没有 enabled 字段的脏数据按桌面默认
      enabled: typeof p.enabled === "boolean" ? p.enabled : defaultEnabled(),
      pos: {
        x: Number.isFinite(p.x) ? (p.x as number) : 0,
        y: Number.isFinite(p.y) ? (p.y as number) : 0,
      },
      wanderInterval: wander,
    };
  } catch {
    return { enabled: defaultEnabled(), pos: DEFAULT_POS, wanderInterval: "normal" };
  }
}

function save(state: {
  enabled: boolean;
  pos: DeskPetPos;
  wanderInterval: PetWanderInterval;
}): void {
  try {
    localStorage.setItem(KEY, JSON.stringify(state));
  } catch {
    /* ignore quota */
  }
}

const listeners = new Set<() => void>();
let state = loadDeskPet();

function emit(): void {
  listeners.forEach((fn) => fn());
}

export function getDeskPetState(): {
  enabled: boolean;
  pos: DeskPetPos;
  wanderInterval: PetWanderInterval;
} {
  return state;
}

export function subscribeDeskPet(fn: () => void): () => void {
  listeners.add(fn);
  return () => listeners.delete(fn);
}

export function setDeskPetEnabled(enabled: boolean): void {
  state = { ...state, enabled };
  save(state);
  emit();
}

export function setDeskPetPos(pos: DeskPetPos): void {
  state = { ...state, pos };
  save(state);
  emit();
}

export function setPetWanderInterval(wanderInterval: PetWanderInterval): void {
  state = { ...state, wanderInterval };
  save(state);
  emit();
}
