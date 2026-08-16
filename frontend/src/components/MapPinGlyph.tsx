import type { MapElementKind } from "../types/vn";
import styles from "./MapPinGlyph.module.css";

type Props = {
  kind: MapElementKind | string;
  color?: string;
  size?: "sm" | "md" | "lg";
  active?: boolean;
  className?: string;
};

/** Geometric stamp for a map place kind — no emoji. */
export function MapPinGlyph({
  kind,
  color,
  size = "md",
  active = false,
  className = "",
}: Props) {
  const k = (kind || "landmark").toLowerCase();
  return (
    <span
      className={`${styles.stamp} ${styles[size]} ${active ? styles.active : ""} ${className}`}
      style={{ ["--stamp-color" as string]: color || "var(--accent)" }}
      aria-hidden
    >
      <svg viewBox="0 0 48 48" className={styles.svg} focusable="false">
        <path className={styles.plate} d="M4 4 H40 L44 8 V44 H4 Z" />
        <path className={styles.shard} d="M40 4 L44 8 H40 Z" />
        <g
          className={styles.mark}
          fill="none"
          stroke="currentColor"
          strokeWidth="2.2"
          strokeLinejoin="miter"
        >
          {glyphPaths(k)}
        </g>
      </svg>
    </span>
  );
}

function glyphPaths(kind: string) {
  switch (kind) {
    case "station":
      return (
        <>
          <rect x="12" y="14" width="24" height="18" />
          <path d="M12 20 H36 M18 14 V32 M30 14 V32" />
        </>
      );
    case "plaza":
      return (
        <>
          <path d="M24 10 L36 34 H12 Z" />
          <path d="M18 34 H30" />
        </>
      );
    case "park":
      return (
        <>
          <circle cx="24" cy="18" r="9" />
          <path d="M24 26 V36 M18 36 H30" />
        </>
      );
    case "hospital":
      return (
        <>
          <rect x="14" y="12" width="20" height="24" />
          <path d="M24 16 V32 M16 24 H32" />
        </>
      );
    case "school":
      return (
        <>
          <path d="M8 22 L24 12 L40 22" />
          <rect x="14" y="22" width="20" height="14" />
          <path d="M24 22 V36" />
        </>
      );
    case "cafe":
      return (
        <>
          <path d="M14 16 H30 V30 H14 Z" />
          <path d="M30 18 H34 A4 4 0 0 1 34 28 H30" />
          <path d="M16 34 H28" />
        </>
      );
    case "home":
      return (
        <>
          <path d="M10 24 L24 12 L38 24" />
          <rect x="16" y="24" width="16" height="14" />
        </>
      );
    case "shop":
      return (
        <>
          <path d="M12 18 H36 L34 34 H14 Z" />
          <path d="M12 18 L16 12 H32 L36 18" />
          <rect x="20" y="24" width="8" height="10" />
        </>
      );
    case "office":
      return (
        <>
          <rect x="14" y="10" width="20" height="28" />
          <path d="M18 16 H30 M18 22 H30 M18 28 H30" />
        </>
      );
    case "apartment":
      return (
        <>
          <rect x="12" y="12" width="24" height="26" />
          <path d="M18 18 H22 V22 H18 Z M26 18 H30 V22 H26 Z M18 28 H22 V32 H18 Z M26 28 H30 V32 H26 Z" />
        </>
      );
    case "temple":
      return (
        <>
          <path d="M10 28 L24 12 L38 28" />
          <path d="M14 28 H34 V36 H14 Z" />
          <path d="M8 28 H40" />
        </>
      );
    case "forest":
      return (
        <>
          <path d="M16 34 L24 14 L32 34 Z" />
          <path d="M22 34 L30 18 L38 34 Z" />
        </>
      );
    case "beach":
      return (
        <>
          <path d="M8 28 Q16 20 24 28 Q32 36 40 28" />
          <circle cx="34" cy="16" r="5" />
        </>
      );
    case "bridge":
      return (
        <>
          <path d="M8 30 H40" />
          <path d="M12 30 Q24 14 36 30" />
          <path d="M16 30 V36 M32 30 V36" />
        </>
      );
    case "custom":
      return (
        <>
          <path d="M24 12 L28 22 L38 24 L30 32 L32 42 L24 36 L16 42 L18 32 L10 24 L20 22 Z" />
        </>
      );
    case "landmark":
    default:
      return (
        <>
          <path d="M24 10 L30 22 H18 Z" />
          <rect x="20" y="22" width="8" height="16" />
        </>
      );
  }
}
