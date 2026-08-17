import type { MascotMood } from "./MascotFigure";
import styles from "./PetPlaceholder.module.css";

/**
 * Q 版桌宠占位 — 美术逐帧 PNG 交付前的程序生成形象（雾岛雪菜 Q 版比例）。
 * 大头 + 小身体；mood 只改表情。帧图就位后播放器用真实 PNG 替换本组件。
 */
export function PetPlaceholder({
  mood = "idle",
  className = "",
  title = "美术资源待交付",
}: {
  mood?: MascotMood;
  className?: string;
  title?: string;
}) {
  const eyes = renderEyes(mood);
  const mouth = renderMouth(mood);
  return (
    <svg
      className={`${styles.placeholder} ${className}`}
      viewBox="0 0 360 480"
      role="img"
      aria-label="桌宠占位（美术待交付）"
    >
      <title>{title}</title>
      <g>
        {/* 小身体：水手裙 */}
        <path
          d="M150 300 L210 300 L222 400 Q180 416 138 400 Z"
          fill="var(--pet-body, #dfe6f4)"
          stroke="var(--line)"
          strokeWidth="3"
        />
        <path d="M156 300 L204 300 L196 340 L164 340 Z" fill="var(--pet-accent, #8fa8d8)" />
        {/* 头：大圆 */}
        <circle cx="180" cy="168" r="120" fill="var(--pet-skin, #ffe8da)" stroke="var(--line)" strokeWidth="3" />
        {/* 刘海 + 侧发（Q 版雪菜短发） */}
        <path
          d="M60 168 C60 84 132 44 180 44 C228 44 300 84 300 168 L300 150 C280 108 240 92 180 92 C120 92 80 108 60 150 Z"
          fill="var(--pet-hair, #44548f)"
          stroke="var(--line)"
          strokeWidth="3"
        />
        <path d="M62 152 C58 210 84 250 96 258 C92 224 96 192 108 168 Z" fill="var(--pet-hair, #44548f)" stroke="var(--line)" strokeWidth="3" />
        <path d="M298 152 C302 210 276 250 264 258 C268 224 264 192 252 168 Z" fill="var(--pet-hair, #44548f)" stroke="var(--line)" strokeWidth="3" />
        {/* 呆毛 */}
        <path d="M180 40 C186 18 200 14 208 22 C196 26 190 34 188 46 Z" fill="var(--pet-hair, #44548f)" />
        {/* 眼睛 */}
        {eyes}
        {/* 腮红 */}
        <circle cx="122" cy="196" r="14" fill="var(--pet-blush, #f6b8a8)" opacity="0.55" />
        <circle cx="238" cy="196" r="14" fill="var(--pet-blush, #f6b8a8)" opacity="0.55" />
        {/* 嘴 */}
        {mouth}
      </g>
    </svg>
  );
}

function renderEyes(mood: MascotMood) {
  const common = { fill: "var(--pet-eye, #2c3350)" };
  switch (mood) {
    case "cheer":
      return (
        <g>
          <path d="M108 176 Q126 152 146 176" fill="none" stroke="var(--pet-eye, #2c3350)" strokeWidth="6" strokeLinecap="round" />
          <path d="M214 176 Q234 152 252 176" fill="none" stroke="var(--pet-eye, #2c3350)" strokeWidth="6" strokeLinecap="round" />
        </g>
      );
    case "think":
      return (
        <g>
          <circle cx="127" cy="168" r="16" {...common} />
          <circle cx="233" cy="172" r="12" {...common} />
        </g>
      );
    case "fluster":
    case "puzzled":
      return (
        <g>
          <circle cx="127" cy="172" r="18" {...common} />
          <circle cx="233" cy="172" r="18" {...common} />
          <circle cx="120" cy="164" r="4" fill="var(--pet-skin, #ffe8da)" />
          <circle cx="226" cy="164" r="4" fill="var(--pet-skin, #ffe8da)" />
        </g>
      );
    case "worry":
      return (
        <g>
          <path d="M112 184 Q127 172 142 182" fill="none" stroke="var(--pet-eye, #2c3350)" strokeWidth="5" strokeLinecap="round" />
          <path d="M218 182 Q233 172 248 184" fill="none" stroke="var(--pet-eye, #2c3350)" strokeWidth="5" strokeLinecap="round" />
        </g>
      );
    case "wince":
    case "angry":
      return (
        <g>
          <path d="M112 166 L146 178" stroke="var(--pet-eye, #2c3350)" strokeWidth="5" strokeLinecap="round" />
          <path d="M248 166 L214 178" stroke="var(--pet-eye, #2c3350)" strokeWidth="5" strokeLinecap="round" />
        </g>
      );
    default:
      return (
        <g>
          <circle cx="127" cy="176" r="15" {...common} />
          <circle cx="233" cy="176" r="15" {...common} />
          <circle cx="131" cy="172" r="4" fill="var(--pet-skin, #ffe8da)" />
          <circle cx="237" cy="172" r="4" fill="var(--pet-skin, #ffe8da)" />
        </g>
      );
  }
}

function renderMouth(mood: MascotMood) {
  const color = "var(--pet-mouth, #a5534a)";
  switch (mood) {
    case "cheer":
      return <path d="M156 216 Q180 240 204 216" fill="none" stroke={color} strokeWidth="5" strokeLinecap="round" />;
    case "worry":
    case "wince":
      return <path d="M168 224 Q180 214 192 224" fill="none" stroke={color} strokeWidth="4" strokeLinecap="round" />;
    case "fluster":
      return <ellipse cx="180" cy="220" rx="10" ry="9" fill={color} />;
    default:
      return <path d="M170 220 Q180 228 190 220" fill="none" stroke={color} strokeWidth="4" strokeLinecap="round" />;
  }
}
