/**
 * 音乐播放条开关（localStorage）——与 MusicPlayerBar 组件分离，供设置页复用。
 * 默认开启；关闭后播放条整体隐藏（正在播放的音频会暂停）。
 */

const KEY = "vnss-music-bar";
const EVENT = "vnss:musicbar";

export function loadMusicBar(): boolean {
  try {
    const v = localStorage.getItem(KEY);
    if (v === null) return true; // 默认开
    return v === "1";
  } catch {
    return true;
  }
}

export function setMusicBar(on: boolean): void {
  try {
    localStorage.setItem(KEY, on ? "1" : "0");
  } catch {
    /* ignore */
  }
}

export function subscribeMusicBar(fn: () => void): () => void {
  window.addEventListener(EVENT, fn);
  return () => window.removeEventListener(EVENT, fn);
}

export function notifyMusicBar(): void {
  window.dispatchEvent(new Event(EVENT));
}
