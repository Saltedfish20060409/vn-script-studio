import { useState } from "react";
import { markTourSeen } from "../lib/onboarding";
import styles from "./OnboardingOverlay.module.css";

const STEPS = [
  {
    emoji: "✍️",
    title: "剧本就是一切",
    body: "写作页的编辑器直接写 Ren'Py 风格脚本：旁白用双引号行，对白用 角色名 \"台词\"。写完后点「▶ 试玩本章」立刻在播放器里看效果。",
  },
  {
    emoji: "🗺️",
    title: "设定先行",
    body: "顶部「世界」页管理角色卡、设定库（bible）、地点地图；「项目」页看写作统计、导出与快照。设定写得越全，AI 助手越懂你的作品。",
  },
  {
    emoji: "📊",
    title: "让 AI 帮你分析",
    body: "写作页切到「分析」：分支树看剧情结构、弧线看角色出场热度、一致性查跨章矛盾、语气检查人设是否走形。项目页也有「结构分析」直达。",
  },
  {
    emoji: "🤖",
    title: "右下角是你的 AI 编辑",
    body: "Agent 可以直接改工程（加角色/改设定/写大纲），也能续写、改写、润色。不确定怎么用？直接问它：\"先不要改工程，给我本章修改意见\"。",
  },
];

export function OnboardingOverlay({ onDone }: { onDone: () => void }) {
  const [step, setStep] = useState(0);
  const last = step === STEPS.length - 1;
  const s = STEPS[step];

  const finish = () => {
    markTourSeen();
    onDone();
  };

  return (
    <div
      className={styles.overlay}
      role="dialog"
      aria-modal="true"
      aria-label="新手引导"
      data-testid="onboarding-overlay"
    >
      <div className={styles.card}>
        <p className={styles.kicker}>VN SCRIPT STUDIO · 一分钟上手</p>
        <div className={styles.emoji} aria-hidden>
          {s.emoji}
        </div>
        <h1 className={styles.title}>{s.title}</h1>
        <p className={styles.body}>{s.body}</p>
        <div className={styles.dots} aria-hidden>
          {STEPS.map((_, i) => (
            <span key={i} className={i === step ? styles.dotOn : styles.dot} />
          ))}
        </div>
        <div className={styles.actions}>
          {step > 0 ? (
            <button
              type="button"
              className={styles.ghost}
              onClick={() => setStep((v) => v - 1)}
            >
              上一步
            </button>
          ) : (
            <span />
          )}
          <button type="button" className={styles.ghost} onClick={finish}>
            跳过
          </button>
          <button
            type="button"
            className={styles.primary}
            onClick={() => (last ? finish() : setStep((v) => v + 1))}
          >
            {last ? "开始写作" : "下一步"}
          </button>
        </div>
      </div>
    </div>
  );
}
