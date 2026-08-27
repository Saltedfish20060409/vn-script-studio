import { useEffect, useRef } from "react";

import styles from "./GlowCursor.module.css";

/** 鼠标跟随光晕（react-bits GlowCursor 风格，轻量版）：
 * 固定定位圆斑缓动跟随指针，pointer-events:none 不挡交互。
 * 触屏 / reduced-motion 下不渲染。只在登录/公开页使用，编辑器不开。 */
export function GlowCursor() {
  const ref = useRef<HTMLDivElement>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el) return;
    if (window.matchMedia("(pointer: coarse)").matches) return;
    if (window.matchMedia("(prefers-reduced-motion: reduce)").matches) return;
    let raf = 0;
    let x = -300;
    let y = -300;
    let tx = -300;
    let ty = -300;
    const onMove = (e: MouseEvent) => {
      tx = e.clientX;
      ty = e.clientY;
    };
    const tick = () => {
      x += (tx - x) * 0.12;
      y += (ty - y) * 0.12;
      el.style.transform = `translate(${x - 110}px, ${y - 110}px)`;
      raf = requestAnimationFrame(tick);
    };
    window.addEventListener("mousemove", onMove);
    raf = requestAnimationFrame(tick);
    return () => {
      window.removeEventListener("mousemove", onMove);
      cancelAnimationFrame(raf);
    };
  }, []);

  return <div ref={ref} className={styles.cursor} aria-hidden />;
}
