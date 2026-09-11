import { useEffect, useState } from "react";
import styles from "./FirstRunChecklist.module.css";

/**
 * 新用户三步引导条（激活用，见 docs/roadmap-2026-09.md 方向 A）。
 *
 * 目标：让新用户在 5 分钟内完成「AI 续写 → 生成 RPY → 试玩/导出」，
 * 从而真正看到产品价值，而不是面对空白编辑器流失。
 *
 * 行为：
 * - 三步各自可点，完成后打勾；全部完成或用户关闭后不再出现；
 * - 状态存 localStorage（不需要后端参与）；
 * - 每一步都会上报埋点（B），用于验证引导是否真的提升了激活率。
 */

const DONE_KEY = "vnss-firstrun-done";
const HIDDEN_KEY = "vnss-firstrun-hidden";

type StepKey = "ai" | "rpy" | "export";

const STEPS: Array<{ key: StepKey; label: string; hint: string }> = [
  { key: "ai", label: "让 AI 续写这一段", hint: "不用配置 Key，站内免费模型就能试" },
  { key: "rpy", label: "生成可试玩的脚本", hint: "把正文转成 Ren'Py，能直接玩" },
  { key: "export", label: "导出 Word 存档", hint: "投稿/留底一份" },
];

function readDone(): Record<StepKey, boolean> {
  const empty = { ai: false, rpy: false, export: false };
  try {
    const raw = localStorage.getItem(DONE_KEY);
    if (!raw) return empty;
    const parsed = JSON.parse(raw) as Partial<Record<StepKey, boolean>>;
    return { ...empty, ...parsed };
  } catch {
    return empty;
  }
}

type Props = {
  /** 第一步：打开 AI 责编面板（由 StudioApp 提供信号） */
  onOpenAgent: () => void;
  /** 第二步：生成 RPY（跳到导出页并触发） */
  onGenerateRpy: () => void;
  /** 第三步：导出 Word/Markdown */
  onExport: () => void;
  /** 是否已经有可写的正文（没有正文时不显示 RPY/导出两步的"已完成"感） */
  hasContent: boolean;
  /** 埋点：由调用方注入，避免这里直接依赖 track 模块的副作用时机 */
  onStep?: (step: StepKey) => void;
};

export function FirstRunChecklist({
  onOpenAgent,
  onGenerateRpy,
  onExport,
  hasContent,
  onStep,
}: Props) {
  const [done, setDone] = useState<Record<StepKey, boolean>>(() => readDone());
  const [hidden, setHidden] = useState<boolean>(() => {
    try {
      return localStorage.getItem(HIDDEN_KEY) === "1";
    } catch {
      return false;
    }
  });

  // 观测到用户"已经有正文"时，自动把第一步打勾（他已经写过东西了）
  useEffect(() => {
    if (hasContent && !done.ai) {
      setDone((prev) => ({ ...prev, ai: true }));
    }
  }, [hasContent, done.ai]);

  useEffect(() => {
    try {
      localStorage.setItem(DONE_KEY, JSON.stringify(done));
    } catch {
      /* ignore */
    }
  }, [done]);

  const allDone = done.ai && done.rpy && done.export;
  useEffect(() => {
    if (allDone) {
      try {
        localStorage.setItem(HIDDEN_KEY, "1");
      } catch {
        /* ignore */
      }
      setHidden(true);
    }
  }, [allDone]);

  if (hidden) return null;

  const mark = (key: StepKey) => setDone((prev) => ({ ...prev, [key]: true }));

  return (
    <div className={styles.bar} role="region" aria-label="新手上手三步">
      <span className={styles.title}>三步上手</span>
      {STEPS.map((s, i) => (
        <button
          key={s.key}
          type="button"
          className={done[s.key] ? styles.stepDone : styles.step}
          title={s.hint}
          onClick={() => {
            onStep?.(s.key);
            if (s.key === "ai") onOpenAgent();
            if (s.key === "rpy") onGenerateRpy();
            if (s.key === "export") onExport();
            mark(s.key);
          }}
        >
          <span className={styles.idx}>{done[s.key] ? "✓" : i + 1}</span>
          <span className={styles.label}>{s.label}</span>
          <span className={styles.hint}>{s.hint}</span>
        </button>
      ))}
      <button
        type="button"
        className={styles.close}
        aria-label="不再显示"
        onClick={() => {
          try {
            localStorage.setItem(HIDDEN_KEY, "1");
          } catch {
            /* ignore */
          }
          setHidden(true);
        }}
      >
        ×
      </button>
    </div>
  );
}
