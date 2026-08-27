import {
  useEffect,
  useRef,
  useState,
  type ButtonHTMLAttributes,
  type CSSProperties,
  type PointerEvent as ReactPointerEvent,
} from "react";

import styles from "./GlowButton.module.css";

type Props = ButtonHTMLAttributes<HTMLButtonElement> & {
  /** 磁吸强度 0-1（鼠标靠近时按钮轻微跟随） */
  magnet?: number;
};

/** 主按钮：磁吸跟随（Magnet）+ 光标发光（Glow），二合一，零依赖。 */
export function GlowButton({ magnet = 0.3, className, children, ...rest }: Props) {
  const ref = useRef<HTMLButtonElement>(null);
  const [glow, setGlow] = useState<{ x: number; y: number } | null>(null);

  useEffect(() => {
    const el = ref.current;
    if (!el || !magnet) return;
    let raf = 0;
    let tx = 0;
    let ty = 0;
    let cx = 0;
    let cy = 0;
    const onMove = (e: MouseEvent) => {
      const r = el.getBoundingClientRect();
      tx = (e.clientX - (r.left + r.width / 2)) * magnet;
      ty = (e.clientY - (r.top + r.height / 2)) * magnet;
    };
    const onLeave = () => {
      tx = 0;
      ty = 0;
    };
    const tick = () => {
      cx += (tx - cx) * 0.16;
      cy += (ty - cy) * 0.16;
      el.style.transform = `translate(${cx.toFixed(2)}px, ${cy.toFixed(2)}px)`;
      raf = requestAnimationFrame(tick);
    };
    el.addEventListener("mousemove", onMove);
    el.addEventListener("mouseleave", onLeave);
    raf = requestAnimationFrame(tick);
    return () => {
      cancelAnimationFrame(raf);
      el.removeEventListener("mousemove", onMove);
      el.removeEventListener("mouseleave", onLeave);
      el.style.transform = "";
    };
  }, [magnet]);

  const onPointerMove = (e: ReactPointerEvent<HTMLButtonElement>) => {
    const r = e.currentTarget.getBoundingClientRect();
    setGlow({ x: e.clientX - r.left, y: e.clientY - r.top });
    rest.onPointerMove?.(e);
  };

  return (
    <button
      ref={ref}
      className={`${styles.glow} ${className ?? ""}`}
      style={
        glow
          ? ({ "--gx": `${glow.x}px`, "--gy": `${glow.y}px` } as CSSProperties)
          : undefined
      }
      data-on={glow ? "1" : "0"}
      onPointerMove={onPointerMove}
      onPointerLeave={(e) => {
        setGlow(null);
        rest.onPointerLeave?.(e);
      }}
      {...rest}
    >
      <span className={styles.inner}>{children}</span>
    </button>
  );
}
