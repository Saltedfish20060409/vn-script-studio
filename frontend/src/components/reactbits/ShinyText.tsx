import styles from "./ShinyText.module.css";

type Props = {
  text: string;
  className?: string;
  disabled?: boolean;
};

/** 流光文字（react-bits ShinyText 风格）：金属高光周期性扫过。 */
export function ShinyText({ text, className, disabled = false }: Props) {
  return (
    <span
      className={`${styles.shiny} ${disabled ? styles.disabled : ""} ${className ?? ""}`}
    >
      {text}
    </span>
  );
}
