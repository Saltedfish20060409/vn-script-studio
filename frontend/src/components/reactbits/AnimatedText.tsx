import { useEffect, useState, type CSSProperties } from "react";

import styles from "./AnimatedText.module.css";

type Props = {
  text: string;
  className?: string;
  /** 首字延迟（ms），用于多行错开 */
  delay?: number;
  /** 每字间隔（ms） */
  stagger?: number;
  as?: "span" | "h1" | "h2" | "p" | "div";
  style?: CSSProperties;
};

/** 逐字淡入上浮（react-bits AnimatedText 风格，零依赖）。 */
export function AnimatedText({
  text,
  className,
  delay = 0,
  stagger = 45,
  as: Tag = "span",
  style,
}: Props) {
  const [show, setShow] = useState(false);
  useEffect(() => {
    const t = window.setTimeout(() => setShow(true), delay);
    return () => window.clearTimeout(t);
  }, [delay]);

  const chars = Array.from(text);
  return (
    <Tag className={`${styles.root} ${className ?? ""}`} style={style} aria-label={text}>
      {chars.map((c, i) => (
        <span
          key={`${i}-${c}`}
          className={`${styles.char} ${show ? styles.visible : ""}`}
          style={{ transitionDelay: show ? `${i * stagger}ms` : "0ms" }}
          aria-hidden
        >
          {c === " " ? "\u00A0" : c}
        </span>
      ))}
    </Tag>
  );
}
