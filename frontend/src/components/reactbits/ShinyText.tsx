import { useEffect, useRef } from "react";

import styles from "./ShinyText.module.css";

type Props = {
  text: string;
  className?: string;
};

/**
 * 流光文字（react-bits ShinyText 风格）：高光带周期扫过。
 * 用 rAF 内联更新 background-position + 强制重绘：
 * Chromium 对 background-clip:text 的 background-position 变化可能不重绘，
 * 每帧重赋 backgroundImage 触发重新栅格化。
 */
export function ShinyText({ text, className }: Props) {
  const ref = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    let raf = 0;
    let start: number | null = null;
    const DURATION = 4000;
    const tick = (t: number) => {
      if (start === null) start = t;
      const p = ((t - start) % DURATION) / DURATION; // 0..1 循环
      // 只改 background-position；需要重栅格化时用 transform 触发，别自赋值。
      el.style.backgroundPosition = `${(100 - p * 200).toFixed(2)}% 50%`;
      el.style.transform = "translateZ(0)";
      raf = requestAnimationFrame(tick);
    };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, []);

  return (
    <span ref={ref} className={`${styles.shiny} ${className ?? ""}`}>
      {text}
    </span>
  );
}
