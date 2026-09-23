import { useDeferredValue, useEffect, useMemo, useState } from "react";
import { getProjectStats, type ProjectStats } from "../api/projects";
import {
  SCENE_SEPARATOR,
  countIssues,
  goalProgress,
  lintProse,
  parseScenes,
  type TextIssue,
} from "../lib/editorAssist";
import { countWords, formatWords } from "../lib/wordCount";
import type { WritingGoals } from "../types/vn";
import styles from "./WriteAids.module.css";

type Props = {
  projectId: string;
  chapterId: string;
  /** 当前章节所属卷（用来显示本卷目标进度）；未分卷时为空 */
  volumeId?: string;
  /** 正文（受控） */
  text: string;
  /** 光标偏移：用来高亮"正在写的这一场" */
  caret: number;
  /** 是否做笔误体检（只有正文模式做；RPY 是代码，中文标点规则不适用） */
  lint: boolean;
  writingGoals?: WritingGoals;
  onSaveGoals: (goals: WritingGoals) => void;
  /** 跳到正文某处（父组件负责聚焦与滚动） */
  onJump: (from: number, length: number) => void;
  /** 在光标处插入一段文本（分场标记） */
  onInsert: (snippet: string) => void;
};

const todayKey = (): string => {
  const d = new Date();
  return `${d.getFullYear()}-${String(d.getMonth() + 1).padStart(2, "0")}-${String(
    d.getDate()
  ).padStart(2, "0")}`;
};

function Bar({ ratio, done }: { ratio: number; done: boolean }) {
  return (
    <span className={styles.bar} aria-hidden>
      <span
        className={done ? styles.barFillDone : styles.barFill}
        style={{ width: `${Math.round(ratio * 100)}%` }}
      />
    </span>
  );
}

function GoalItem({
  label,
  words,
  target,
}: {
  label: string;
  words: number | null;
  target: number;
}) {
  if (words === null) return null;
  const p = goalProgress(words, target);
  return (
    <span className={styles.goal} data-testid={`goal-${label}`}>
      <span className={styles.goalLabel}>{label}</span>
      <Bar ratio={p.ratio} done={p.done} />
      <span className={styles.goalNum}>
        {formatWords(p.words)} / {formatWords(p.target)}
      </span>
      <span className={p.done ? styles.goalDone : styles.goalLeft}>
        {p.done ? "已达成" : `还差 ${formatWords(p.remaining)}`}
      </span>
    </span>
  );
}

/** 常用标点一键插入（…… 与 —— 在中文输入法里都别扭） */
function SnippetBar({ onInsert }: { onInsert: (snippet: string) => void }) {
  return (
    <span className={styles.snippets}>
      {["……", "——", "「」"].map((snippet) => (
        <button
          key={snippet}
          type="button"
          className={styles.snippet}
          title={`插入 ${snippet}`}
          onClick={() => onInsert(snippet)}
        >
          {snippet}
        </button>
      ))}
    </span>
  );
}

/**
 * 写作页的"手感条"：字数目标进度 · 分场导航 · 笔误体检。
 *
 * 三个东西放在一条里，是因为它们都在回答同一个问题："这一章写到哪了、写到哪一段、
 * 刚才那句有没有敲错"。分开做成三个面板反而会让写作者离开正文。
 *
 * 体检只做**几乎肯定是手误**的那几类（引号不配对、半角标点贴汉字、`--`/`...`），
 * 命中就给出原文片段并可点击跳过去；语义层面的好坏判断一概不做——那是模型和作者的事。
 */
export function WriteAids({
  projectId,
  chapterId,
  volumeId,
  text,
  caret,
  lint,
  writingGoals,
  onSaveGoals,
  onJump,
  onInsert,
}: Props) {
  const [stats, setStats] = useState<ProjectStats | null>(null);
  const [goalOpen, setGoalOpen] = useState(false);
  const [draft, setDraft] = useState({ daily: "", chapter: "", volume: "" });
  const [issueIndex, setIssueIndex] = useState(0);

  // 今日净增 / 本卷字数只有服务端知道（/stats 已经在维护按天净增），
  // 切章时再拉一次即可——正文本身实时算，不需要等接口。
  useEffect(() => {
    let cancelled = false;
    getProjectStats(projectId)
      .then((s) => {
        if (!cancelled) setStats(s);
      })
      .catch(() => {
        // 统计拿不到不影响写作：进度条少两个数字，界面上不弹错
        if (!cancelled) setStats(null);
      });
    return () => {
      cancelled = true;
    };
  }, [projectId, chapterId]);

  const scenes = useMemo(() => parseScenes(text), [text]);
  // 体检扫全文，长章节在每一次按键都重算会拖慢输入 → 用 deferred 值降低优先级
  const deferredText = useDeferredValue(text);
  const issues = useMemo<TextIssue[]>(
    () => (lint ? lintProse(deferredText) : []),
    [lint, deferredText]
  );
  const counts = useMemo(() => countIssues(issues), [issues]);
  const stale = deferredText !== text;

  const chapterWords = countWords(text);
  const volumes = stats?.volumes ?? [];
  const volumeWords = volumeId ? volumes.find((v) => v.id === volumeId)?.words ?? null : null;
  const todayNet = stats?.activity?.find((d) => d.date === todayKey())?.net ?? null;

  const goals = writingGoals ?? {};
  const hasGoals = Boolean(goals.daily || goals.chapter || goals.volume);

  useEffect(() => {
    setIssueIndex(0);
  }, [chapterId]);

  const activeScene = useMemo(() => {
    let found = 0;
    for (const s of scenes) {
      if (s.from <= caret) found = s.index;
    }
    return found;
  }, [scenes, caret]);

  // 正文被改动后条数会变，下标可能越界——统一在这里夹一次，别让"下一条"跳空
  const activeIssueIndex = issues.length ? Math.min(issueIndex, issues.length - 1) : 0;
  const currentIssue = issues.length ? issues[activeIssueIndex] : null;

  function openGoalEditor() {
    setDraft({
      daily: goals.daily ? String(goals.daily) : "",
      chapter: goals.chapter ? String(goals.chapter) : "",
      volume: goals.volume ? String(goals.volume) : "",
    });
    setGoalOpen(true);
  }

  const parseGoal = (raw: string): number | undefined => {
    const n = Number.parseInt(raw.replace(/[^\d]/g, ""), 10);
    return Number.isFinite(n) && n > 0 ? n : undefined;
  };

  function saveGoals() {
    onSaveGoals({
      daily: parseGoal(draft.daily),
      chapter: parseGoal(draft.chapter),
      volume: parseGoal(draft.volume),
    });
    setGoalOpen(false);
  }

  return (
    <div className={styles.wrap} data-testid="write-aids">
      <div className={styles.head}>
        <strong className={styles.headTitle}>写作辅助</strong>
        <span className={styles.hint}>
          字数目标 · 分场导航 · 笔误体检（点条目可直接跳到正文那一处）
        </span>
      </div>
      <div className={styles.row}>
        <span className={styles.rowLabel}>目标</span>
        {goalOpen ? (
          <span className={styles.goalForm}>
            {(
              [
                ["chapter", "本章"],
                ["volume", "本卷"],
                ["daily", "今日"],
              ] as const
            ).map(([key, label]) => (
              <label key={key} className={styles.goalInput}>
                {label}
                <input
                  inputMode="numeric"
                  placeholder="不限"
                  value={draft[key]}
                  onChange={(e) => setDraft((d) => ({ ...d, [key]: e.target.value }))}
                  onKeyDown={(e) => {
                    if (e.key === "Enter") {
                      e.preventDefault();
                      saveGoals();
                    } else if (e.key === "Escape") {
                      e.preventDefault();
                      setGoalOpen(false);
                    }
                  }}
                />
                字
              </label>
            ))}
            <button type="button" className={styles.ghost} onClick={saveGoals}>
              保存
            </button>
            <button type="button" className={styles.ghost} onClick={() => setGoalOpen(false)}>
              取消
            </button>
            <span className={styles.hint}>
              留空 = 不设该目标；目标存在作品里，换设备也在
            </span>
          </span>
        ) : hasGoals ? (
          <>
            <GoalItem label="本章" words={chapterWords} target={goals.chapter ?? 0} />
            <GoalItem label="本卷" words={volumeWords} target={goals.volume ?? 0} />
            <GoalItem label="今日" words={todayNet} target={goals.daily ?? 0} />
            <button type="button" className={styles.ghost} onClick={openGoalEditor}>
              改目标
            </button>
          </>
        ) : (
          <>
            <span className={styles.hint}>
              这一章 {formatWords(chapterWords)} 字
              {volumeWords !== null ? ` · 本卷 ${formatWords(volumeWords)} 字` : ""}
              {todayNet !== null ? ` · 今日净增 ${formatWords(todayNet)} 字` : ""}
            </span>
            <button
              type="button"
              className={styles.ghost}
              data-testid="open-goal-editor"
              onClick={openGoalEditor}
            >
              设置字数目标
            </button>
          </>
        )}
      </div>

      <div className={styles.row}>
        <span className={styles.rowLabel}>分场</span>
        {scenes.length > 1 ? (
          <span className={styles.scenes}>
            {scenes.map((s) => (
              <button
                key={s.index}
                type="button"
                className={s.index === activeScene ? styles.sceneOn : styles.sceneOff}
                title={`跳到这一场（${s.words} 字）`}
                onClick={() => onJump(s.from, 0)}
              >
                {s.index + 1}. {s.title.length > 10 ? `${s.title.slice(0, 10)}…` : s.title}
                <span className={styles.sceneWords}>{formatWords(s.words)}</span>
              </button>
            ))}
          </span>
        ) : (
          <span className={styles.hint}>
            还没有分场。写到换场的地方插入「{SCENE_SEPARATOR}」或写一行【场景名】，这里就会出现导航。
          </span>
        )}
        <button
          type="button"
          className={styles.ghost}
          data-testid="insert-scene-separator"
          title="在光标处插入分场标记"
          onClick={() => onInsert(`\n${SCENE_SEPARATOR}\n`)}
        >
          + 分场标记
        </button>
        <SnippetBar onInsert={onInsert} />
      </div>

      {lint ? (
        <div className={styles.row}>
          <span className={styles.rowLabel}>笔误</span>
          {issues.length === 0 ? (
            <span className={styles.hint}>
              {stale ? "正在检查…" : "没发现标点/空格的明显手误"}
            </span>
          ) : (
            <>
              <span className={styles.counts}>
                {counts.error > 0 ? (
                  <span className={styles.countError}>{counts.error} 处错误</span>
                ) : null}
                {counts.warn > 0 ? <span className={styles.countWarn}>{counts.warn} 处提醒</span> : null}
                {counts.info > 0 ? <span className={styles.countInfo}>{counts.info} 处提示</span> : null}
              </span>
              <button
                type="button"
                className={styles.issue}
                data-testid="issue-jump"
                title="跳到这一处"
                onClick={() => currentIssue && onJump(currentIssue.offset, currentIssue.length)}
              >
                第 {currentIssue?.line} 行：{currentIssue?.message}
              </button>
              <span className={styles.navNums}>
                {activeIssueIndex + 1} / {issues.length}
              </span>
              <button
                type="button"
                className={styles.ghost}
                aria-label="上一条"
                onClick={() => setIssueIndex((i) => (i - 1 + issues.length) % issues.length)}
              >
                ↑
              </button>
              <button
                type="button"
                className={styles.ghost}
                aria-label="下一条"
                onClick={() => setIssueIndex((i) => (i + 1) % issues.length)}
              >
                ↓
              </button>
            </>
          )}
        </div>
      ) : null}
    </div>
  );
}
