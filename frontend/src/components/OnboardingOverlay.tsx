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
      body: "写作页默认用大白话写剧本：旁白直接写，对白写成「角色名：台词」。想做成能试玩的游戏时，再切到 RPY 模式（Ren'Py 视觉小说引擎的脚本格式，可以手写，也可以点「根据剧本生成」）。导出跟随当前模式：剧本导出 Word 文档（.docx），RPY 稿导出 .rpy 文件；「试玩」读取的是 RPY 稿。",
    },
    {
      emoji: "🗺️",
      title: "设定先行",
      body: narrow
        ? "底栏切「设定」管角色卡和世界观，「地图」管地点；「项目」里看统计、导出与快照。设定写得越清楚，AI 越懂你的作品。"
        : "顶部「设定」页管理角色卡、设定库、地点地图；「项目」页看写作统计、导出与快照。这些设定会单独保存，AI 写作时按需参考——写得越清楚，它越懂你的作品。",
    },
    {
      emoji: "📊",
      title: "让 AI 帮你分析",
      body: "写作页切到「分析」：「分支树」把剧情走向画成一张图，帮你看清结构；「弧线」显示角色出场的变化；「一致性」检查前后章节有没有矛盾；「语气」看看人物说话是否符合人设。分析结果仅供参考，改不改由你决定。项目页也能直达「结构分析」。",
    },
    {
      emoji: "🤖",
      title: "右下角是审稿 Agent（AI 责编）",
      body: narrow
        ? "手机上 Agent 贴在屏幕侧边，点开即可。它能帮你改稿（先给对照稿、你确认才写入，也能撤回）、续写、润色、挑毛病。不确定就直说：「先别改正文，只给我本章修改意见」。顶栏「帮助」或登录页「使用指南」有完整说明。"
        : "它能直接帮你改作品——加角色、改设定、写大纲，也能续写、改写、润色。改稿时会先给你左右对照，确认后才写入，之后还能撤回。不确定怎么用？直接问它：「先别改正文，只给我本章修改意见」。顶栏「帮助」随时可再看；完整说明在「使用指南」。",
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
