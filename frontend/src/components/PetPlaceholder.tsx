import type { MascotMood } from "./MascotFigure";
import styles from "./PetPlaceholder.module.css";

/**
 * Q 版桌宠 — CSS/SVG 分层（透明底）。
 * 层级：投影 → 背发/耳机后壳 → 身体 → 头 → 五官 → 刘海 → 耳机前壳/呆毛。
 * 造型对齐看板娘：浅蓝短发、异色瞳、耳机、水手领结、绷带。
 */
export function PetPlaceholder({
  mood = "idle",
  className = "",
  title = "桌宠",
}: {
  mood?: MascotMood;
  className?: string;
  title?: string;
}) {
  return (
    <svg
      className={`${styles.placeholder} ${className}`}
      viewBox="0 0 360 480"
      role="img"
      aria-label="桌宠"
    >
      <title>{title}</title>
      <defs>
        <linearGradient id="petHair" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0%" stopColor="#9ec8f0" />
          <stop offset="100%" stopColor="#6a9fd4" />
        </linearGradient>
        <linearGradient id="petSkirt" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor="#b8c4ef" />
          <stop offset="100%" stopColor="#8fa0d8" />
        </linearGradient>
      </defs>

      {/* L0 脚底淡影（可有，无白底） */}
      <ellipse className={styles.shadow} cx="180" cy="452" rx="70" ry="9" />

      {/* L1 背发 + 耳机后壳 */}
      <g className={styles.layerBack}>
        <path
          d="M62 140 C50 220 62 310 88 380 C100 330 108 250 102 180 Z"
          fill="url(#petHair)"
        />
        <path
          d="M298 140 C310 220 298 310 272 380 C260 330 252 250 258 180 Z"
          fill="url(#petHair)"
        />
        <ellipse cx="78" cy="168" rx="28" ry="34" fill="#7eb6e8" stroke="#4a7aaa" strokeWidth="3" />
        <ellipse cx="282" cy="168" rx="28" ry="34" fill="#7eb6e8" stroke="#4a7aaa" strokeWidth="3" />
      </g>

      {/* L2 身体：卫衣 + 裙 + 腿套 */}
      <g className={styles.layerBody}>
        <path
          d="M132 286 L228 286 L248 400 Q180 430 112 400 Z"
          fill="#f4f6fb"
          stroke="#3a4560"
          strokeWidth="2.5"
        />
        <path
          d="M140 286 L220 286 L232 348 L128 348 Z"
          fill="url(#petSkirt)"
          stroke="#3a4560"
          strokeWidth="2"
        />
        {/* 水手领 + 结 */}
        <path
          d="M150 286 L180 318 L210 286"
          fill="none"
          stroke="#5b7fd4"
          strokeWidth="10"
          strokeLinejoin="round"
        />
        <circle cx="180" cy="308" r="7" fill="#2c3350" />
        <path d="M168 308 L152 322 L164 318 Z" fill="#5b7fd4" />
        <path d="M192 308 L208 322 L196 318 Z" fill="#5b7fd4" />
        {/* 手臂袖 */}
        <ellipse cx="118" cy="330" rx="22" ry="28" fill="#f4f6fb" stroke="#3a4560" strokeWidth="2" />
        <ellipse cx="242" cy="330" rx="22" ry="28" fill="#f4f6fb" stroke="#3a4560" strokeWidth="2" />
        {/* 腿套 */}
        <path d="M138 400 L158 400 L162 448 L134 448 Z" fill="#eef2fa" stroke="#3a4560" strokeWidth="2" />
        <path d="M202 400 L222 400 L226 448 L198 448 Z" fill="#eef2fa" stroke="#3a4560" strokeWidth="2" />
        {/* 挎包小挂件 */}
        <circle cx="236" cy="360" r="8" fill="#e11d48" opacity="0.9" />
      </g>

      {/* L3 头 */}
      <circle
        className={styles.layerHead}
        cx="180"
        cy="168"
        r="112"
        fill="#ffe4d4"
        stroke="#3a4560"
        strokeWidth="3"
      />

      {/* L4 五官（刘海下） */}
      <g className={styles.layerFace}>
        {renderBrows(mood)}
        {renderEyes(mood)}
        {/* 左颊绷带 */}
        <g transform="translate(108 198) rotate(-18)">
          <rect x="0" y="0" width="28" height="12" rx="2" fill="#fff" stroke="#c9b8ae" strokeWidth="1.5" />
          <line x1="14" y1="-2" x2="14" y2="14" stroke="#c9b8ae" strokeWidth="1.5" />
        </g>
        <circle cx="120" cy="196" r="12" fill="#f6b8a8" opacity="0.45" />
        <circle cx="240" cy="196" r="12" fill="#f6b8a8" opacity="0.45" />
        {renderMouth(mood)}
      </g>

      {/* L5 前发刘海（盖额） */}
      <g className={styles.layerBangs}>
        <path
          d="M78 120 C100 70 140 52 180 52 C220 52 260 70 282 120
             C266 98 246 88 226 86 C212 108 200 130 192 152
             C186 128 176 108 168 92 C154 110 142 132 134 154
             C118 128 98 106 78 120 Z"
          fill="url(#petHair)"
          stroke="#4a7aaa"
          strokeWidth="2"
        />
        <path
          d="M92 128 C86 168 92 210 108 238 C102 200 104 160 116 138 Z"
          fill="url(#petHair)"
        />
        <path
          d="M268 128 C274 168 268 210 252 238 C258 200 256 160 244 138 Z"
          fill="url(#petHair)"
        />
        {/* 十字发夹 */}
        <g stroke="#fff" strokeWidth="3" strokeLinecap="round">
          <line x1="148" y1="88" x2="148" y2="104" />
          <line x1="140" y1="96" x2="156" y2="96" />
          <line x1="212" y1="86" x2="212" y2="102" />
          <line x1="204" y1="94" x2="220" y2="94" />
        </g>
      </g>

      {/* L6 耳机前壳 + 头带 + 呆毛 */}
      <g className={styles.layerFront}>
        <path
          d="M96 120 Q180 48 264 120"
          fill="none"
          stroke="#7eb6e8"
          strokeWidth="10"
          strokeLinecap="round"
        />
        <ellipse cx="78" cy="168" rx="22" ry="28" fill="#8fc0ec" stroke="#4a7aaa" strokeWidth="2.5" />
        <ellipse cx="282" cy="168" rx="22" ry="28" fill="#8fc0ec" stroke="#4a7aaa" strokeWidth="2.5" />
        {/* 像素心 */}
        <path
          d="M70 160 h6 v-6 h6 v6 h6 v6 h-6 v6 h-6 v-6 h-6 z"
          fill="#ff4d8d"
        />
        <path
          className={styles.ahoge}
          d="M176 52 C184 22 208 14 218 28 C200 32 190 44 186 58 Z"
          fill="url(#petHair)"
          stroke="#4a7aaa"
          strokeWidth="2"
        />
      </g>
    </svg>
  );
}

function renderBrows(mood: MascotMood) {
  const s = "#2c3350";
  if (mood === "angry" || mood === "wince") {
    return (
      <g stroke={s} strokeWidth="4" strokeLinecap="round">
        <path d="M108 148 L148 158" />
        <path d="M252 148 L212 158" />
      </g>
    );
  }
  if (mood === "worry" || mood === "puzzled") {
    return (
      <g fill="none" stroke={s} strokeWidth="3.5" strokeLinecap="round">
        <path d="M110 156 Q128 146 148 154" />
        <path d="M212 154 Q232 146 250 156" />
      </g>
    );
  }
  return (
    <g fill="none" stroke={s} strokeWidth="3" strokeLinecap="round" opacity="0.75">
      <path d="M110 152 Q128 146 148 152" />
      <path d="M212 152 Q232 146 250 152" />
    </g>
  );
}

function renderEyes(mood: MascotMood) {
  // 异色瞳：左蓝右褐
  const left = "#3b82c4";
  const right = "#c45a4a";
  switch (mood) {
    case "cheer":
    case "angel":
      return (
        <g fill="none" stroke="#2c3350" strokeWidth="6" strokeLinecap="round">
          <path d="M112 176 Q130 154 148 176" />
          <path d="M212 176 Q230 154 248 176" />
        </g>
      );
    case "worry":
      return (
        <g fill="none" stroke="#2c3350" strokeWidth="5" strokeLinecap="round">
          <path d="M114 184 Q130 172 146 182" />
          <path d="M214 182 Q230 172 246 184" />
        </g>
      );
    case "wince":
    case "angry":
      return (
        <g stroke="#2c3350" strokeWidth="5" strokeLinecap="round">
          <path d="M114 166 L148 178" />
          <path d="M246 166 L212 178" />
        </g>
      );
    case "think":
      return (
        <g>
          <circle cx="130" cy="170" r="15" fill={left} />
          <circle cx="230" cy="174" r="12" fill={right} />
          <circle cx="134" cy="166" r="4" fill="#fff" opacity="0.9" />
        </g>
      );
    case "fluster":
    case "puzzled":
      return (
        <g>
          <circle cx="130" cy="172" r="17" fill={left} />
          <circle cx="230" cy="172" r="17" fill={right} />
          <circle cx="124" cy="166" r="5" fill="#fff" opacity="0.9" />
          <circle cx="224" cy="166" r="5" fill="#fff" opacity="0.9" />
        </g>
      );
    default:
      return (
        <g>
          <circle cx="130" cy="174" r="16" fill={left} />
          <circle cx="230" cy="174" r="16" fill={right} />
          <circle cx="135" cy="168" r="5" fill="#fff" opacity="0.92" />
          <circle cx="235" cy="168" r="5" fill="#fff" opacity="0.92" />
        </g>
      );
  }
}

function renderMouth(mood: MascotMood) {
  const c = "#a5534a";
  switch (mood) {
    case "cheer":
    case "angel":
      return <path d="M158 216 Q180 242 202 216" fill="none" stroke={c} strokeWidth="5" strokeLinecap="round" />;
    case "worry":
      return <path d="M162 222 Q180 214 198 222" fill="none" stroke={c} strokeWidth="4" strokeLinecap="round" />;
    case "angry":
      return <path d="M160 220 L200 216" stroke={c} strokeWidth="4" strokeLinecap="round" />;
    case "fluster":
      return <ellipse cx="180" cy="220" rx="9" ry="6" fill={c} opacity="0.85" />;
    default:
      return <path d="M164 218 Q180 226 196 218" fill="none" stroke={c} strokeWidth="4" strokeLinecap="round" />;
  }
}
