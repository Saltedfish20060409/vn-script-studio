import { useRef, useState, type CSSProperties, type MouseEvent, type ReactNode } from "react";

import styles from "./TiltedCard.module.css";

type Props = {
  children: ReactNode;
  className?: string;
  /** 最大倾斜角度（度） */
  maxTilt?: number;
};

/** 3D 倾斜卡片（react-bits TiltedCard 风格）：跟随鼠标透视倾斜。 */
export function TiltedCard({ children, className, maxTilt = 6 }: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const [style, setStyle] = useState<CSSProperties>({ transform: "perspective(900px)" });

  const onMove = (e: MouseEvent<HTMLDivElement>) => {
    const el = ref.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    const px = (e.clientX - r.left) / r.width - 0.5;
    const py = (e.clientY - r.top) / r.height - 0.5;
    setStyle({
      transform: `perspective(900px) rotateX(${(-py * maxTilt).toFixed(2)}deg) rotateY(${(px * maxTilt).toFixed(2)}deg)`,
    });
  };

  const reset = () => setStyle({ transform: "perspective(900px)" });

  return (
    <div
      ref={ref}
      className={`${styles.tilt} ${className ?? ""}`}
      style={style}
      onMouseMove={onMove}
      onMouseLeave={reset}
    >
      {children}
    </div>
  );
}
