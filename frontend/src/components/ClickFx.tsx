import { useEffect, useRef } from "react";
import { loadClickFx, subscribeClickFx } from "../lib/clickFx";

/**
 * 轻量点击特效（赛璐璐风格）：点击处扩散圆环 + 粒子。
 *
 * - 纯 CSS 动画、无第三方依赖（不引入 ba-click-fx 包：体积/网络/风格可控）
 * - pointer-events: none —— 绝不干扰真实点击
 * - 开关在设置页（lib/clickFx），输入框内不触发
 */

/** 在视口坐标处生成一个特效节点（扩散圆环 + 3 颗小粒子）。 */
function spawnFx(x: number, y: number) {
  const host = document.createElement("div");
  host.className = "vnss-clickfx-host";
  host.style.left = `${x}px`;
  host.style.top = `${y}px`;

  const ring = document.createElement("span");
  ring.className = "vnss-clickfx-ring";
  host.appendChild(ring);

  const COLORS = ["var(--accent)", "#ffffff", "var(--anime-pink, #ff9ec4)"];
  for (let i = 0; i < 3; i++) {
    const dot = document.createElement("i");
    dot.className = "vnss-clickfx-dot";
    dot.style.background = COLORS[i % COLORS.length];
    // 每颗粒子朝不同方向飞
    const angle = (i / 3) * Math.PI * 2 + Math.random() * 0.6;
    dot.style.setProperty("--fx-angle", `${angle}rad`);
    host.appendChild(dot);
  }

  (document.body || document.documentElement).appendChild(host);
  // 动画结束后移除，避免节点堆积
  window.setTimeout(() => host.remove(), 700);
}

export function ClickFx() {
  const enabledRef = useRef(loadClickFx());

  useEffect(() => {
    enabledRef.current = loadClickFx();
    const onToggle = () => {
      enabledRef.current = loadClickFx();
    };
    const unsub = subscribeClickFx(onToggle);

    const onPointerDown = (e: PointerEvent) => {
      if (!enabledRef.current) return;
      // 文本输入/选择区域不触发，避免写作时干扰
      const t = e.target as HTMLElement | null;
      if (t && (t.closest("input, textarea, select") || t.isContentEditable)) return;
      spawnFx(e.clientX, e.clientY);
    };
    window.addEventListener("pointerdown", onPointerDown);
    return () => {
      unsub();
      window.removeEventListener("pointerdown", onPointerDown);
    };
  }, []);

  return null;
}
