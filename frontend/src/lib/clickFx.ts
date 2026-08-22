/**
 * 点击特效开关（localStorage）——与 ClickFx 组件分离，供设置页复用。
 */

const FX_KEY = "vnss-click-fx";
const FX_EVENT = "vnss:clickfx";

export function loadClickFx(): boolean {
  try {
    const v = localStorage.getItem(FX_KEY);
    if (v === null) return true; // 默认开
    return v === "1";
  } catch {
    return true;
  }
}

export function setClickFx(on: boolean): void {
  try {
    localStorage.setItem(FX_KEY, on ? "1" : "0");
  } catch {
    /* ignore */
  }
}

export function subscribeClickFx(fn: () => void): () => void {
  window.addEventListener(FX_EVENT, fn);
  return () => window.removeEventListener(FX_EVENT, fn);
}

export function notifyClickFx(): void {
  window.dispatchEvent(new Event(FX_EVENT));
}
