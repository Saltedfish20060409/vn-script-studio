/**
 * 桌宠状态：开关 + 屏幕位置（像素，视口坐标）持久化。
 * 与设置页共享；位置变化不触发设置同步，仅本地。
 */

export interface DeskPetPos {
  x: number; // px from left
  y: number; // px from top
}

const KEY = "vnss-deskpet-v1";
const DEFAULT_POS: DeskPetPos = { x: 0, y: 0 }; // 0,0 → 右下角默认停靠

export function loadDeskPet(): { enabled: boolean; pos: DeskPetPos } {
  try {
    const raw = localStorage.getItem(KEY);
    if (!raw) return { enabled: false, pos: DEFAULT_POS };
    const p = JSON.parse(raw) as Partial<{ enabled: boolean; x: number; y: number }>;
    return {
      enabled: p.enabled === true,
      pos: {
        x: Number.isFinite(p.x) ? (p.x as number) : 0,
        y: Number.isFinite(p.y) ? (p.y as number) : 0,
      },
    };
  } catch {
    return { enabled: false, pos: DEFAULT_POS };
  }
}

function save(state: { enabled: boolean; pos: DeskPetPos }): void {
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

export function getDeskPetState(): { enabled: boolean; pos: DeskPetPos } {
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
