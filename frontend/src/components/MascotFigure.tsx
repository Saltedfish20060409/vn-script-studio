import { mascotArtSrc, type MascotMood } from "../lib/mascotArt";
import styles from "./MascotFigure.module.css";

export type { MascotMood };
export type MascotSize = "xs" | "sm" | "md" | "lg" | "xl" | "fill";

type Props = {
  mood?: MascotMood;
  size?: MascotSize;
  /** Occasional short caption under the figure */
  line?: string | null;
  /** Focus / quiet chrome: fade figure, hide line */
  quiet?: boolean;
  className?: string;
  /**
   * Override art. Default: mood-mapped 雾岛雪菜 stand-in PNGs.
   * Pass empty string to force SVG silhouette fallback.
   */
  artSrc?: string | null;
  /** Writer pack id → hue / hair hint for silhouette variants */
  variant?: string | null;
  kind?: "mascot" | "writer";
  label?: string;
};

/** Stable hue from string (writer id). */
export function variantHue(id: string | null | undefined): number {
  if (!id) return 210;
  let h = 0;
  for (let i = 0; i < id.length; i++) h = (h * 31 + id.charCodeAt(i)) >>> 0;
  return h % 360;
}

function hairPath(variant: string | null | undefined): string {
  const hue = variantHue(variant);
  const style = hue % 3;
  if (style === 0) {
    return "M34 28 C22 30 18 48 20 62 L28 58 C30 44 38 40 48 42 C58 40 66 44 68 58 L76 62 C78 48 74 30 62 28 C56 18 40 18 34 28 Z";
  }
  if (style === 1) {
    return "M36 26 C24 28 20 50 22 64 L30 60 C32 46 40 40 50 42 C60 40 68 48 70 62 L78 66 C82 52 76 28 62 24 C54 14 42 16 36 26 Z M70 48 C78 52 86 58 88 70 L82 72 C80 62 74 56 70 52 Z";
  }
  return "M32 30 C20 34 16 54 18 72 L26 66 C28 50 36 42 48 44 C60 42 68 50 70 66 L78 72 C80 54 76 32 64 28 C56 16 40 16 32 30 Z";
}

function CollegeSilhouette({
  fill,
  stroke,
  accent,
  mood,
  variant,
}: {
  fill: string;
  stroke: string;
  accent: string;
  mood: MascotMood;
  variant?: string | null;
}) {
  const eyeY =
    mood === "think" || mood === "puzzled"
      ? 46
      : mood === "wince" || mood === "angry"
        ? 47
        : 45;
  const mouth =
    mood === "cheer" || mood === "angel"
      ? "M44 56 Q50 62 56 56"
      : mood === "wince" || mood === "angry"
        ? "M46 58 L54 56"
        : mood === "think" || mood === "puzzled" || mood === "worry"
          ? "M46 58 Q50 56 54 58"
          : mood === "fluster"
            ? "M46 57 Q50 60 54 57"
            : "M46 57 Q50 59 54 57";

  return (
    <svg className={styles.svg} viewBox="0 0 100 130" aria-hidden focusable="false">
      <ellipse cx="50" cy="122" rx="28" ry="5" fill={stroke} opacity="0.18" />
      <path
        d="M28 72 L36 58 L50 62 L64 58 L72 72 L78 118 L22 118 Z"
        fill={fill}
        stroke={stroke}
        strokeWidth="2"
      />
      <path
        d="M40 62 L50 78 L60 62 L50 68 Z"
        fill={accent}
        stroke={stroke}
        strokeWidth="1.5"
      />
      <path
        d="M46 70 L50 82 L54 70 L50 74 Z"
        fill={accent}
        stroke={stroke}
        strokeWidth="1"
      />
      <circle cx="50" cy="44" r="18" fill={fill} stroke={stroke} strokeWidth="2" />
      <path d={hairPath(variant)} fill={accent} stroke={stroke} strokeWidth="1.5" />
      <path
        d="M34 38 C42 28 58 28 66 38 L62 42 C56 34 44 34 38 42 Z"
        fill={accent}
        opacity="0.95"
      />
      {mood === "wince" || mood === "angry" ? (
        <>
          <path d={`M40 ${eyeY} L46 ${eyeY - 2}`} stroke={stroke} strokeWidth="2" />
          <path d={`M54 ${eyeY - 2} L60 ${eyeY}`} stroke={stroke} strokeWidth="2" />
        </>
      ) : (
        <>
          <circle cx="43" cy={eyeY} r="2.2" fill={stroke} />
          <circle cx="57" cy={eyeY} r="2.2" fill={stroke} />
        </>
      )}
      <path
        d={mouth}
        fill="none"
        stroke={stroke}
        strokeWidth="1.8"
        strokeLinecap="round"
      />
      {mood === "think" || mood === "puzzled" ? (
        <circle cx="72" cy="28" r="3" fill={accent} stroke={stroke} strokeWidth="1" />
      ) : null}
      {mood === "cheer" || mood === "angel" ? (
        <path
          d="M70 24 L72 30 L78 30 L73 34 L75 40 L70 36 L65 40 L67 34 L62 30 L68 30 Z"
          fill={accent}
          stroke={stroke}
          strokeWidth="1"
        />
      ) : null}
    </svg>
  );
}

export function MascotFigure({
  mood = "idle",
  size = "md",
  line = null,
  quiet = false,
  className = "",
  artSrc,
  variant = null,
  kind = "mascot",
  label,
}: Props) {
  const hue = variantHue(variant);
  const fill =
    kind === "writer"
      ? `hsl(${hue} 28% 78%)`
      : "color-mix(in srgb, var(--paper) 70%, var(--accent))";
  const stroke = "var(--line)";
  const accent = kind === "writer" ? `hsl(${hue} 55% 42%)` : "var(--accent)";

  // null/undefined → mood art; "" → force SVG; string → explicit override
  const resolvedArt =
    kind === "writer"
      ? artSrc || null
      : artSrc === undefined || artSrc === null
        ? mascotArtSrc(mood)
        : artSrc === ""
          ? null
          : artSrc;

  return (
    <div
      className={`${styles.wrap} ${styles[size]} ${quiet ? styles.quiet : ""} ${resolvedArt ? styles.hasArt : ""} ${className}`}
      data-mascot={kind}
      data-mood={mood}
      aria-hidden={line ? undefined : true}
    >
      <div className={styles.figure}>
        <div
          className={styles.slot}
          style={kind === "writer" ? { borderColor: accent } : undefined}
        >
          {resolvedArt ? (
            <img className={styles.art} src={resolvedArt} alt="" draggable={false} />
          ) : (
            <CollegeSilhouette
              fill={fill}
              stroke={stroke}
              accent={accent}
              mood={mood}
              variant={variant}
            />
          )}
        </div>
        {kind === "mascot" && size === "sm" && !resolvedArt ? (
          <span className={styles.dockBadge}>{label || "搭"}</span>
        ) : null}
      </div>
      {line ? <p className={styles.line}>{line}</p> : null}
    </div>
  );
}
