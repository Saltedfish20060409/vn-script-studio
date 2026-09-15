import { useCallback, useEffect, useState } from "react";
import { fetchScriptReport, type ScriptReportOut } from "../api/projects";
import { ApiError } from "../api/http";
import styles from "./ScriptReportPanel.module.css";

type Props = {
  projectId: string;
  /** 点某条问题跳到对应章节 */
  onOpenChapter?: (chapterId: string) => void;
};

function fmtMinutes(minutes: number): string {
  if (minutes < 1) return "不到 1 分钟";
  if (minutes < 60) return `约 ${minutes} 分钟`;
  const h = Math.floor(minutes / 60);
  const m = Math.round(minutes % 60);
  return `约 ${h} 小时 ${m} 分`;
}

/**
 * 剧本工程体检：分支覆盖 / 结局可达性 / 悬空跳转 / 变量使用 / 时长 / 重复率。
 *
 * 这些指标直接对应作者最怕的三件事：分支写歪、结局漏了、体量估不准。
 * 全部是本地计算，点一下就有，不消耗任何模型额度。
 */
export function ScriptReportPanel({ projectId, onOpenChapter }: Props) {
  const [report, setReport] = useState<ScriptReportOut | null>(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  const load = useCallback(async () => {
    setBusy(true);
    setError("");
    try {
      setReport(await fetchScriptReport(projectId));
    } catch (e) {
      setError(e instanceof ApiError ? e.message : "体检失败");
    } finally {
      setBusy(false);
    }
  }, [projectId]);

  useEffect(() => {
    void load();
  }, [load]);

  if (busy && !report) {
    return <p className={styles.note}>正在体检剧本…</p>;
  }
  if (error) {
    return (
      <p className={styles.note}>
        {error}
        <button type="button" className={styles.link} onClick={() => void load()}>
          重试
        </button>
      </p>
    );
  }
  if (!report) return null;

  const unreachable = report.labels.unreachable;
  const unreachableEndings = report.endings.filter((e) => !e.reachable);
  const problems =
    unreachable.length +
    unreachableEndings.length +
    report.danglingJumps.length +
    report.invalidConditions.length +
    report.variables.undeclared.length;

  return (
    <div className={styles.wrap} data-testid="script-report">
      <div className={styles.head}>
        <strong className={styles.title}>剧本工程体检</strong>
        <button type="button" className={styles.link} onClick={() => void load()}>
          {busy ? "刷新中…" : "重新体检"}
        </button>
      </div>

      <div className={styles.cards}>
        <div className={styles.card}>
          <span>结局可达</span>
          <strong>
            {report.endingsReachable}/{report.endings.length}
          </strong>
        </div>
        <div className={styles.card}>
          <span>分支点</span>
          <strong>{report.branchPoints.length}</strong>
        </div>
        <div className={styles.card}>
          <span>通关时长（估）</span>
          <strong>{fmtMinutes(report.duration.minutes)}</strong>
        </div>
        <div className={styles.card}>
          <span>文本重复</span>
          <strong>{Math.round(report.repetition.ratio * 100)}%</strong>
        </div>
        <div className={styles.card}>
          <span>待处理问题</span>
          <strong className={problems ? styles.bad : undefined}>{problems}</strong>
        </div>
      </div>

      {problems === 0 ? (
        <p className={styles.ok}>
          ✅ 没有发现问题：所有 label 可达、结局都能走到、跳转目标都存在、条件语法正确。
        </p>
      ) : null}

      {unreachable.length > 0 ? (
        <div className={styles.block}>
          <span className={styles.blockTitle}>走不到的 label（死代码）</span>
          <ul className={styles.list}>
            {unreachable.map((name) => (
              <li key={name}>
                <code>{name}</code>
                <span className={styles.dim}>
                  没有任何 jump / 选项能到这里，玩家永远看不到
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {unreachableEndings.length > 0 ? (
        <div className={styles.block}>
          <span className={styles.blockTitle}>写了但走不到的结局</span>
          <ul className={styles.list}>
            {unreachableEndings.map((e) => (
              <li key={`${e.chapterId}-${e.label}`}>
                <button
                  type="button"
                  className={styles.link}
                  onClick={() => onOpenChapter?.(e.chapterId)}
                >
                  {e.label}
                </button>
                <span className={styles.dim}>（{e.chapterId}）</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {report.danglingJumps.length > 0 ? (
        <div className={styles.block}>
          <span className={styles.blockTitle}>跳转目标不存在</span>
          <ul className={styles.list}>
            {report.danglingJumps.map((d, i) => (
              <li key={`${d.chapterId}-${d.target}-${i}`}>
                <code>{d.target}</code>
                <span className={styles.dim}>（{d.chapterId}）</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {report.invalidConditions.length > 0 ? (
        <div className={styles.block}>
          <span className={styles.blockTitle}>条件语法错误（导出时会被注释掉，不会静默放行）</span>
          <ul className={styles.list}>
            {report.invalidConditions.map((c, i) => (
              <li key={i}>
                <code>{c.text}</code>
                <span className={styles.dim}>{c.error}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {report.variables.undeclared.length > 0 ? (
        <div className={styles.block}>
          <span className={styles.blockTitle}>条件/赋值里用到但没声明的变量</span>
          <ul className={styles.list}>
            {report.variables.undeclared.map((k) => (
              <li key={k}>
                <code>{k}</code>
                <span className={styles.dim}>
                  到「设置 → 变量」补一个，否则试玩时它永远是 0/假
                </span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {report.variables.unused.length > 0 ? (
        <div className={styles.block}>
          <span className={styles.blockTitle}>声明了但没用的变量</span>
          <ul className={styles.list}>
            {report.variables.unused.map((k) => (
              <li key={k}>
                <code>{k}</code>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      {report.repetition.top.length > 0 ? (
        <div className={styles.block}>
          <span className={styles.blockTitle}>
            重复文本 Top {report.repetition.top.length}（共 {report.repetition.uniqueDuplicated} 处、
            {report.repetition.duplicateChars} 字）
          </span>
          <ul className={styles.list}>
            {report.repetition.top.map((t, i) => (
              <li key={i}>
                <span className={styles.count}>×{t.count}</span>
                <span className={styles.quote}>{t.text}</span>
              </li>
            ))}
          </ul>
        </div>
      ) : null}

      <p className={styles.note}>
        时长{fmtMinutes(report.duration.minutes)}（{report.duration.assumption}）；
        正文 {report.duration.chars} 字 + 显式等待 {report.duration.waitSeconds} 秒。
      </p>
      <p className={styles.note}>
        块统计：
        {Object.entries(report.counts)
          .sort((a, b) => b[1] - a[1])
          .map(([k, v]) => `${k} ${v}`)
          .join(" · ")}
      </p>
    </div>
  );
}
