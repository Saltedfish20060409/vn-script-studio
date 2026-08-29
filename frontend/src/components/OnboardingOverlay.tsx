import { useState } from "react";
import { markTourSeen } from "../lib/onboarding";
import styles from "./OnboardingOverlay.module.css";

function isNarrow(): boolean {
  try {
    return window.matchMedia("(max-width: 820px)").matches;
  } catch {
    return false;
  }
}

function steps(narrow: boolean) {
  return [
    {
      emoji: "✍️",
      title: "先写人话",
      body: "写作页默认是自然语言剧本：旁白直接写，对白写成「角色名：台词」。需要上演脚本时切到 RPY，可手写或点「根据剧本生成」。顶栏导出跟当前视图走（剧本 → .docx，RPY → .rpy）。试玩读的是 RPY 稿。",
    },
    {
      emoji: "🗺️",
      title: "设定先行",
      body: narrow
        ? "底栏切「设定」管角色卡和世界观，「地图」管地点；「项目」里看统计、导出与快照。设定写得越全，AI 越懂你的作品。"
        : "顶部「设定」页管理角色卡、设定库、地点地图；「项目」页看写作统计、导出与快照。设定写得越全，AI 助手越懂你的作品。",
    },
    {
      emoji: "📊",
      title: "让 AI 帮你分析",
      body: "写作页切到「分析」：分支树看剧情结构、弧线看角色出场热度、一致性查跨章矛盾、语气检查人设是否走形。项目页也有「结构分析」直达。",
    },
    {
      emoji: "🤖",
      title: narrow ? "侧边贴片是 AI 编辑" : "右下角是你的 AI 编辑",
      body: narrow
        ? "手机上 Agent 贴在屏幕侧边，点开即可。可以直接改工程，也能续写、改写、润色。不确定就说：「先不要改工程，给我本章修改意见」。顶栏「帮助」或登录页「使用指南」有完整说明。"
        : "Agent 可以直接改工程（加角色/改设定/写大纲），也能续写、改写、润色。不确定怎么用？直接问它：「先不要改工程，给我本章修改意见」。顶栏「帮助」随时可再看；完整说明在「使用指南」。",
    },
  ];
}

export function OnboardingOverlay({ onDone }: { onDone: () => void }) {
  const [narrow] = useState(isNarrow);
  const STEPS = steps(narrow);
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
        {last ? (
          <p className={styles.helpLink}>
            <a href="/guide" target="_blank" rel="noreferrer">
              打开完整使用指南
            </a>
          </p>
        ) : null}
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
