import {
  useRef,
  useState,
  type CSSProperties,
  type MouseEvent,
  type ReactNode,
} from "react";

import styles from "./SpotlightCard.module.css";

type Props = {
  children: ReactNode;
  className?: string;
  /** 光斑颜色（rgba） */
  spotlightColor?: string;
};

/** 鼠标跟随光斑卡片（react-bits SpotlightCard 风格）：hover 时光斑照亮卡片。 */
export function SpotlightCard({
  children,
  className,
  spotlightColor = "rgba(255, 255, 255, 0.14)",
}: Props) {
  const ref = useRef<HTMLDivElement>(null);
  const [pos, setPos] = useState<{ x: number; y: number } | null>(null);

  const onMove = (e: MouseEvent<HTMLDivElement>) => {
    const el = ref.current;
    if (!el) return;
    const r = el.getBoundingClientRect();
    setPos({ x: e.clientX - r.left, y: e.clientY - r.top });
  };

  return (
    <div
      ref={ref}
      className={`${styles.card} ${className ?? ""}`}
      onMouseMove={onMove}
      onMouseLeave={() => setPos(null)}
      style={
        pos
          ? ({
              "--sx": `${pos.x}px`,
              "--sy": `${pos.y}px`,
              "--sc": spotlightColor,
            } as CSSProperties)
          : undefined
      }
    >
      {children}
    </div>
  );
}
