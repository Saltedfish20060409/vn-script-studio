import { useEffect, useRef } from "react";

import styles from "./ShinyText.module.css";

type Props = {
  text: string;
  className?: string;
};

/**
 * 流光文字（react-bits ShinyText 风格）：强调色高光带周期扫过。
 * 用 rAF 驱动 background-position：Chromium 下 CSS 动画
 * background-position 在 background-clip:text 上不重绘（渐变不动），
 * 内联样式更新必定重绘。
 */
export function ShinyText({ text, className }: Props) {
  const ref = useRef<HTMLSpanElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    let raf = 0;
    let start: number | null = null;
    const DURATION = 4200;
    const tick = (t: number) => {
      if (start === null) start = t;
      const p = ((t - start) % DURATION) / DURATION; // 0..1 循环
      // background-position 100% → -100%（背景宽 240%，扫带穿过可视窗）
      el.style.backgroundPosition = `${(100 - p * 200).toFixed(2)}% 50%`;
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
