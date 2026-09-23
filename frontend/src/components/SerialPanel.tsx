import { useCallback, useEffect, useMemo, useState } from "react";
import { getProjectStats, type ProjectStats } from "../api/projects";
import { countChapterWords, formatWords } from "../lib/wordCount";
import { goalProgress } from "../lib/editorAssist";
import {
  paceEstimate,
  publishState,
  serializationStats,
  streakInfo,
  todayKey,
  updateCalendar,
} from "../lib/serialization";
import { copyForProject } from "../lib/genreCopy";
import type { VnProject } from "../types/vn";
import styles from "./SerialPanel.module.css";

type Props = {
  project: VnProject;
  /** 跳到写作页的某一章 */
  onOpenChapter: (chapterId: string) => void;
  /** 标记已发布 / 撤回发布（父组件写进作品并交给自动保存） */
  onTogglePublish: (chapterId: string, publish: boolean) => void;
};

const WEEKDAYS = ["一", "二", "三", "四", "五", "六", "日"];

/**
 * 连载工作台：日更目标、连续更新天数、更新日历、存稿与发布状态。
 *
 * 为什么单独一页而不是塞进「写作统计」：统计回答的是"写了多少"，连载作者真正每天
 * 要回答的是另外三个问题——**今天写了没有、断了几天、手里有几章存稿能发**。
 * 三者都指向"今天要不要坐下来写"，所以放在一起、并且一进来就能看完。
 *
 * 口径如实标注：日历与连续天数量的是**当日净增 > 0**（与「写作统计」同一份数据，
 * 来自后端逐日记录），它表示"今天往前写了"，不等于"今天发了新章"；
 * 发布状态是作者自己标的，工具不会去猜哪一章"像"是发过的。
 */
export function SerialPanel({ project, onOpenChapter, onTogglePublish }: Props) {
  const [stats, setStats] = useState<ProjectStats | null>(null);
  const [error, setError] = useState("");
  const copy = copyForProject(project);

  const load = useCallback(async () => {
    try {
      setStats(await getProjectStats(project.id));
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "写作记录加载失败");
    }
  }, [project.id]);

  useEffect(() => {
    void load();
  }, [load]);

  const activity = useMemo(() => stats?.activity ?? [], [stats]);
  const streak = useMemo(() => streakInfo(activity), [activity]);
  const weeks = useMemo(() => updateCalendar(activity, 12), [activity]);
  const serial = useMemo(() => serializationStats(project.chapters ?? []), [project.chapters]);
  // 必须用本地时区的今天（toISOString 是 UTC，晚上写的东西会算到明天）
  const todayNet = activity.find((d) => d.date === todayKey())?.net ?? 0;
  const dailyGoal = project.writingGoals?.daily ?? 0;
  const progress = goalProgress(todayNet, dailyGoal);

  // 节奏预估只在"作者自己设了单章目标、而且手里有存稿"时给：样本不足一律不编数字
  const nextDraft = serial.nextToPublish
    ? (project.chapters ?? []).find((c) => c.id === serial.nextToPublish?.id)
    : undefined;
  const chapterGoal = project.writingGoals?.chapter ?? 0;
  const pace =
    nextDraft && chapterGoal > 0
      ? paceEstimate(activity, Math.max(0, chapterGoal - countChapterWords(nextDraft)))
      : null;

  return (
    <div className={styles.wrap} data-testid="serial-panel">
      <div className={styles.toolbar}>
        <span>
          连载 — 今天写了没有、断了几天、手里有几章能发
          <span className={styles.badge}>每天进来先看这一页</span>
        </span>
        <button type="button" className={styles.ghost} onClick={() => void load()}>
          刷新记录
        </button>
      </div>

      {error ? <p className={styles.error}>{error}</p> : null}

      <div className={styles.cards}>
        <div className={styles.card}>
          <span className={styles.cardLabel}>今日净增</span>
          <strong className={styles.cardValue}>
            {formatWords(todayNet)}
            {dailyGoal > 0 ? (
              <span className={styles.cardUnit}> / {formatWords(dailyGoal)} 字</span>
            ) : null}
          </strong>
          {dailyGoal > 0 ? (
            <>
              <span className={styles.bar} aria-hidden>
                <span
                  className={progress.done ? styles.barFillDone : styles.barFill}
                  style={{ width: `${Math.round(progress.ratio * 100)}%` }}
                />
              </span>
              <span className={styles.cardSub}>
                {progress.done ? "今日目标已达成" : `还差 ${formatWords(progress.remaining)} 字`}
              </span>
            </>
          ) : (
            <span className={styles.cardSub}>写作页「写作辅助」里可以设日更目标</span>
          )}
        </div>

        <div className={styles.card}>
          <span className={styles.cardLabel}>连续更新</span>
          <strong className={styles.cardValue}>
            {streak.current}
            <span className={styles.cardUnit}> 天</span>
          </strong>
          <span className={styles.cardSub}>
            最长 {streak.longest} 天 · 共 {streak.totalDays} 天有产出
          </span>
        </div>

        <div className={styles.card}>
          <span className={styles.cardLabel}>存稿</span>
          <strong className={styles.cardValue}>
            {serial.drafts}
            <span className={styles.cardUnit}> 章</span>
          </strong>
          <span className={styles.cardSub}>{formatWords(serial.draftWords)} 字还没发</span>
        </div>

        <div className={styles.card}>
          <span className={styles.cardLabel}>已发布</span>
          <strong className={styles.cardValue}>
            {serial.published}
            <span className={styles.cardUnit}> / {serial.total} 章</span>
          </strong>
          <span className={styles.cardSub}>{formatWords(serial.publishedWords)} 字</span>
        </div>
      </div>

      {streak.current === 0 && streak.totalDays > 0 ? (
        <p className={styles.warnLine}>
          连续性断了（最近一次产出：{streak.lastWriteDate || "——"}）。日历上的今天还是空的。
        </p>
      ) : null}
      {streak.totalDays === 0 ? (
        <p className={styles.hint}>
          还没有连续更新记录。这条按「当天净增 &gt; 0」算，写一点就算——改旧章也算。
        </p>
      ) : null}

      <div className={styles.section}>
        <h3 className={styles.sectionTitle}>更新日历（近 12 周，周一起）</h3>
        <div className={styles.calendar}>
          <div className={styles.weekdays}>
            {WEEKDAYS.map((w) => (
              <span key={w}>{w}</span>
            ))}
          </div>
          <div className={styles.grid}>
            {weeks.map((column, ci) => (
              <div key={ci} className={styles.column}>
                {column.map((cell) => (
                  <span
                    key={cell.date}
                    className={`${styles.cell} ${cell.level > 0 ? styles[`lvl${cell.level}`] : ""} ${
                      cell.today ? styles.today : ""
                    } ${cell.future ? styles.future : ""}`}
                    title={
                      cell.future
                        ? cell.date
                        : `${cell.date} · ${
                            cell.hasRecord ? `净增 ${cell.net} 字` : "没有记录"
                          }`
                    }
                  />
                ))}
              </div>
            ))}
          </div>
        </div>
        <p className={styles.hint}>
          颜色越深当天写得越多（按净增字数，与「写作统计」同一份记录）。删字、只改标点
          的日期会有记录但不着色。
        </p>
      </div>

      <div className={styles.section}>
        <h3 className={styles.sectionTitle}>发布进度</h3>
        {serial.nextToPublish ? (
          <p className={styles.hint}>
            下一章待发布：
            <button
              type="button"
              className={styles.chapterBtn}
              onClick={() => onOpenChapter(serial.nextToPublish!.id)}
            >
              {serial.nextToPublish.title}
            </button>
            （已有 {formatWords(serial.nextToPublish.words)} 字）
            {pace ? `（按近 7 天日均 ${pace.perDay} 字算，写到单章目标还要约 ${pace.days} 天）` : ""}
          </p>
        ) : serial.drafts === 0 && serial.empty > 0 ? (
          <p className={styles.hint}>没有存稿了：还有 {serial.empty} 章是空的，接着写吧。</p>
        ) : serial.total === 0 ? (
          <p className={styles.hint}>还没有章节。</p>
        ) : (
          <p className={styles.hint}>全部章节都已标记发布。</p>
        )}

        {serial.total > 0 ? (
          <table className={styles.table}>
            <thead>
              <tr>
                <th>章</th>
                <th>字数</th>
                <th>状态</th>
                <th>发布时间</th>
                <th />
              </tr>
            </thead>
            <tbody>
              {(project.chapters ?? []).map((chapter) => {
                const state = publishState(chapter);
                return (
                  <tr key={chapter.id}>
                    <td>
                      <button
                        type="button"
                        className={styles.chapterBtn}
                        onClick={() => onOpenChapter(chapter.id)}
                      >
                        {chapter.title}
                      </button>
                    </td>
                    <td>{formatWords(countChapterWords(chapter))}</td>
                    <td>
                      <span
                        className={
                          state === "published"
                            ? styles.statePublished
                            : state === "draft"
                              ? styles.stateDraft
                              : styles.stateEmpty
                        }
                      >
                        {state === "published" ? "已发布" : state === "draft" ? "存稿" : "空章"}
                      </span>
                    </td>
                    <td className={styles.time}>
                      {chapter.publishedAt
                        ? new Date(chapter.publishedAt).toLocaleDateString()
                        : "—"}
                    </td>
                    <td>
                      <button
                        type="button"
                        className={styles.ghost}
                        disabled={state === "empty"}
                        title={
                          state === "empty"
                            ? "这一章还没写，先写点内容再标记发布"
                            : state === "published"
                              ? "撤回发布标记（正文不动）"
                              : "把这一章标记为已发布"
                        }
                        onClick={() =>
                          onTogglePublish(chapter.id, state !== "published")
                        }
                      >
                        {state === "published" ? "撤回发布" : "标记已发布"}
                      </button>
                    </td>
                  </tr>
                );
              })}
            </tbody>
          </table>
        ) : null}
        <p className={styles.hint}>
          发布状态只在本工具里记账（正文与导出不受影响），用来回答「{copy.work}
          里还有几章能发」。工具不会去猜哪一章像发过的。
        </p>
      </div>
    </div>
  );
}
