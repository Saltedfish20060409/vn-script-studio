import { useCallback, useMemo, useState, type ReactNode } from "react";
import { ApiError } from "../api/http";
import {
  consistencyScan,
  fetchAdaptivePlan,
  fetchBranchRecommendations,
  fetchBranchReport,
  fetchContinuityReport,
  fetchPlaytestAnalytics,
  fetchStoryMetrics,
  fetchTelemetrySettings,
  fetchVoiceReport,
  saveTelemetrySettings,
  type AdaptivePlanOut,
  type AnalysisFinding,
  type BranchRecommendationsOut,
  type BranchReportOut,
  type ConsistencyScanOut,
  type ContinuityReportOut,
  type PlaytestAnalyticsOut,
  type StoryMetricsOut,
  type TelemetrySettingsOut,
  type VoiceReportOut,
} from "../api/projects";
import {
  adviceGroups,
  adviceRows,
  adviceStale,
  adviceSummary,
  basisView,
  choiceVarietyView,
  DEFAULT_MIN_RUNS,
  emptyAdvice,
  isKnownSeverity,
  MIN_RUNS_RANGE,
  minRunsView,
  parseMinRuns,
  type AdviceRowView,
} from "../lib/branchAdvice";
import {
  calibrationNote,
  chapterLabel,
  chapterTitleMap,
  codeLabel,
  driftView,
  findingGroups,
  groupBySeverity,
  scanCategoryLabel,
  scanCoverageSentence,
  scanSeverityLabel,
  scanSeverityTone,
  summarizeFindings,
  summarizeScanIssues,
  unknownKeyLabel,
  viewCoverage,
  viewScanCoverage,
  viewVoiceReport,
} from "../lib/analysisReport";
import {
  coverageView,
  endingsView,
  funnelView,
  menuView,
  OPTION_COPY_NOTE,
  sampleView,
  telemetrySwitchCopy,
} from "../lib/playtestReport";
import {
  ADAPTIVE_EXPORT_NOTE,
  adaptiveCandidateRows,
  declaredMismatchGroups,
  declaredMismatchSummary,
  EMOTION_INFERENCE_NOTE,
  emotionArcRows,
  emotionBreakRows,
  emotionChapterRows,
  foreshadowView,
  openHookRows,
  preludeView,
  recipeRows,
  summarizeAdaptivePlan,
  summarizeStoryMetrics,
  tendencyCounterRows,
} from "../lib/storyReport";
import styles from "./InsightPanel.module.css";

type Kind = "branch" | "voice" | "continuity" | "scan" | "readers" | "advice" | "story";

const TABS: ReadonlyArray<{ id: Kind; label: string }> = [
  { id: "branch", label: "分支推理" },
  { id: "voice", label: "声线" },
  { id: "continuity", label: "跨章事实" },
  { id: "scan", label: "全书一致性" },
  { id: "readers", label: "读者行为" },
  { id: "advice", label: "改进建议" },
  { id: "story", label: "故事层" },
];

const TAB_HINTS: Record<Kind, string> = {
  branch:
    "按真实 label 图推理：哪些选项玩家看不到、哪个条件永远不成立、会不会卡在死循环里、写了几个结局实际能走到几个。",
  voice: "每个角色的语言画像 + 每章声线漂移：谁在哪一章说话不像自己。阈值由该角色自己的台词分布自校准。",
  continuity:
    "跨章事实体检：未登记的说话人、指向已删角色的关系边、重名、时间线错序、死亡后仍然出场。",
  scan: "把全书按重叠窗口分片送审模型，跨窗合并去重，并如实报回这次到底扫了多少章。",
  readers:
    "读者**实际**选了什么：每个菜单各选项的占比（含从没人选的）、章级流失、结局分布（含没人走到的），以及读者侧分支覆盖率。默认不采集，要先在下面把开关打开。",
  advice:
    "把结构分析与读者行为**合起来**给改法：每条都带「依据」与「具体怎么改」。读者数据不足时只出静态建议，并在最上面说清楚——那是「还看不出来」，不是「没问题」。",
  story:
    "故事层两件事：①伏笔埋了多少、回收了几成、哪些钩子挂得最久；逐角色情绪弧线（**关键词推断**，每条带证据句）与「哪一章把情绪写反了」；和节拍表声明的对账。②自适应选项：让读者的选择历史改变分支的方案（计数器、可直接照抄的条件、要写进 .rpy 的声明块）。纯本地计算。",
};

const TAB_COSTLY: Record<Kind, boolean> = {
  branch: false,
  voice: false,
  continuity: false,
  scan: true,
  readers: false,
  advice: false,
  story: false,
};

const TAB_EMPTY: Record<Kind, string> = {
  branch: "还没有结果。点上面的按钮开始分支体检。",
  voice: "还没有结果。点上面的按钮生成声线报告。",
  continuity: "还没有结果。点上面的按钮做跨章体检。",
  scan: "还没有结果。点上面的按钮开始全书扫描（会调用模型）。",
  readers: "还没有结果。点上面的按钮读取采集开关并拉取读者行为数据。",
  advice: "还没有结果。点上面的按钮生成改稿建议（纯本地计算，不调模型）。",
  story: "还没有结果。点上面的按钮做故事层体检（纯本地计算，不调模型）。",
};

/** 每个 code 分组默认最多列这么多行，其余折叠（后端可能一次报几百条） */
const MAX_ROWS_PER_GROUP = 6;
/** 回路列表最多列几条 */
const MAX_CYCLE_ROWS = 5;
/** 扫描出的冲突最多列几条 */
const MAX_SCAN_ROWS = 20;
/** 读者行为：最多列这么多菜单（按"有从没人选的选项"优先排前面） */
const MAX_READER_MENUS = 10;
/** 改进建议：每个等级默认最多展开这么多条 */
const MAX_ADVICE_PER_GROUP = 6;
/** 故事层：未回收钩子 / 逐角色弧线 / 逐章走向各自最多列几行 */
const MAX_HOOK_ROWS = 8;
const MAX_ARC_ROWS = 12;
const MAX_CHAPTER_ROWS = 8;

/**
 * 可复制的等宽代码块：自适应条件与 .rpy 声明块都要能一键拿走。
 *
 * 复制失败（非安全上下文里没有 clipboard）时不能只是静默失败：把"手动选中上面的文本"
 * 说出来，并且这段文本本身就是可选中的 `<code>`，所以功能不会丢。
 */
function CopyableCode({ text, label }: { text: string; label: string }) {
  const [state, setState] = useState<"idle" | "copied" | "failed">("idle");

  const copy = useCallback(async () => {
    try {
      await navigator.clipboard.writeText(text);
      setState("copied");
    } catch {
      setState("failed");
    }
  }, [text]);

  return (
    <div className={styles.codeRow}>
      <code className={styles.code} aria-label={label}>
        {text}
      </code>
      <button type="button" className={styles.copyBtn} onClick={() => void copy()}>
        {state === "copied" ? "已复制" : "复制"}
      </button>
      {state === "failed" ? (
        <span className={styles.dim}>复制失败：请手动选中上面的文本</span>
      ) : null}
    </div>
  );
}

type Props = {
  projectId: string;
  /** 项目章节：用来把 findings 的 chapterId 换成人看得懂的标题（找不到退回 id） */
  chapters?: ReadonlyArray<{ id?: string; title?: string }>;
};

/** 无 key / 权限不足时把后端的 detail 原样带给作者，而不是只说"失败了"。 */
function errorDetailOf(e: unknown): string {
  if (!(e instanceof ApiError)) return "";
  const d = e.detail;
  if (typeof d === "string") return d === e.message ? "" : d;
  if (d && typeof d === "object") {
    const msg = (d as { message?: unknown }).message;
    if (typeof msg === "string" && msg !== e.message) return msg;
  }
  return "";
}

function driftScoreText(ch: {
  drift?: number;
  watchThreshold?: number;
  driftThreshold?: number;
}): string {
  if (!Number.isFinite(ch.drift)) return "";
  const watch = ch.watchThreshold;
  const drift = ch.driftThreshold;
  const thresholds =
    Number.isFinite(watch) && Number.isFinite(drift)
      ? `（留意 ≥${(watch as number).toFixed(3)} / 跑味 ≥${(drift as number).toFixed(3)}）`
      : "";
  return `漂移 ${(ch.drift as number).toFixed(3)}${thresholds}`;
}

/**
 * 结论列表：按 code 分组，每行给 severity + 中文 message + 所在章节。
 *
 * 展示上限挡住的条数会如实写出来（"另有 N 条未展开"），不假装只剩这么多。
 */
function FindingList({
  findings,
  titles,
  emptyText,
}: {
  findings?: readonly AnalysisFinding[] | null;
  titles: Record<string, string>;
  emptyText: string;
}) {
  const [expandAll, setExpandAll] = useState(false);
  const severities = groupBySeverity(findings);
  const groups = findingGroups(findings, titles, {
    maxRowsPerGroup: MAX_ROWS_PER_GROUP,
    expandAll,
  });
  const hidden = groups.reduce((n, g) => n + g.hidden, 0);

  if (!findings || findings.length === 0) {
    return <p className={styles.ok}>{emptyText}</p>;
  }

  return (
    <>
      <div className={styles.chips}>
        {severities.map((g) => (
          <span key={g.severity} className={styles.chip} data-sev={g.severity}>
            {g.label} {g.findings.length}
          </span>
        ))}
      </div>

      {groups.map((g) => (
        <div key={g.code} className={styles.block}>
          <span className={styles.blockTitle}>
            {g.label}（{g.count}）
          </span>
          <ul className={styles.list}>
            {g.rows.map((row) => (
              <li key={row.key}>
                <span className={styles.sev} data-sev={row.severity}>
                  {row.severityLabel}
                </span>
                <span className={styles.msg}>{row.message}</span>
                {row.chapter ? <span className={styles.dim}>（{row.chapter}）</span> : null}
                {row.label ? <code>{row.label}</code> : null}
              </li>
            ))}
          </ul>
          {g.hidden > 0 ? (
            <p className={styles.note}>…另有 {g.hidden} 条同类问题未展开</p>
          ) : null}
        </div>
      ))}

      {hidden > 0 ? (
        <button type="button" className={styles.link} onClick={() => setExpandAll(true)}>
          展开全部 {findings.length} 条
        </button>
      ) : null}
    </>
  );
}

/**
 * 按钮文案：读者行为 / 改进建议这两类不是"体检"，各有自己的说法。
 */
function runLabel(kind: Kind, busy: boolean, hasResult: boolean): string {
  if (kind === "readers") {
    return busy ? "读取中…" : hasResult ? "刷新读者行为数据" : "读取开关与数据";
  }
  if (kind === "advice") {
    return busy ? "分析中…" : hasResult ? "重新生成建议" : "生成改进建议";
  }
  if (kind === "story") {
    return busy ? "分析中…" : hasResult ? "重新分析" : "开始故事层分析";
  }
  return busy ? "体检中…" : hasResult ? "重新体检" : "开始体检";
}

/**
 * 改稿建议列表：按 severity 分组（必须改 → 建议改 → 可以看看 → 等级未知），
 * 每组默认展开若干条，其余可一键展开。
 *
 * 每一行都是可折叠的 `<details open>`：**默认就把 `action` 摊开**（这份功能的全部价值就是
 * "具体怎么改"），但作者看完可以收起来，一屏上只留结论。`where` 为空时整段不渲染，
 * 不留一个空标签；`action` 缺失时如实说"这条只有结论"，而不是安静地什么都不显示。
 */
function AdviceList({ rows }: { rows: readonly AdviceRowView[] }) {
  const [expandAll, setExpandAll] = useState(false);
  const groups = adviceGroups(rows);
  const shownPerGroup = (n: number) => (expandAll ? n : Math.min(n, MAX_ADVICE_PER_GROUP));
  const hidden = groups.reduce((n, g) => n + (g.rows.length - shownPerGroup(g.rows.length)), 0);

  if (rows.length === 0) return null;

  return (
    <>
      {groups.map((group) => (
        <div key={group.severity} className={styles.block}>
          <span className={styles.blockTitle}>
            {group.label}（{group.rows.length}）
          </span>
          <ul className={styles.list}>
            {group.rows.slice(0, shownPerGroup(group.rows.length)).map((row) => (
              <li key={row.key}>
                <details className={styles.advice} open>
                  <summary className={styles.adviceHead}>
                    <span className={styles.sev} data-sev={row.severity}>
                      {row.severityLabel}
                    </span>
                    <span className={styles.msg}>{row.title}</span>
                    <span
                      className={styles.sev}
                      data-sev={
                        row.confidence.tone === "evidence"
                          ? "ok"
                          : row.confidence.tone === "static"
                            ? "muted"
                            : "other"
                      }
                    >
                      {row.confidence.label}
                    </span>
                    {/* 没有位置就不渲染空标签 */}
                    {row.where ? <code>{row.where}</code> : null}
                  </summary>
                  <p className={styles.note}>依据：{row.why}</p>
                  {isKnownSeverity(row.rawSeverity) ? null : (
                    <p className={styles.note}>
                      后端给的等级是「{row.rawSeverity || "（空）"}」，界面归到「其它」：不认识的等级
                      一律当"要人看一眼"，也不丢掉。
                    </p>
                  )}
                  {row.actionMissing ? (
                    <p className={styles.error}>
                      这条只有结论，后端没给具体改法：先按上面的依据自己判断这一步该怎么改。
                    </p>
                  ) : (
                    <p className={styles.action}>怎么改：{row.action}</p>
                  )}
                  <p className={styles.note}>{row.confidence.hint}</p>
                </details>
              </li>
            ))}
          </ul>
          {!expandAll && group.rows.length > MAX_ADVICE_PER_GROUP ? (
            <p className={styles.note}>
              …另有 {group.rows.length - MAX_ADVICE_PER_GROUP} 条「{group.label}」未展开
            </p>
          ) : null}
        </div>
      ))}
      {hidden > 0 ? (
        <button type="button" className={styles.link} onClick={() => setExpandAll(true)}>
          展开全部 {rows.length} 条建议
        </button>
      ) : null}
    </>
  );
}

/**
 * 深度体检面板：分支推理 / 声线 / 跨章事实 / 全书一致性扫描 / 读者行为 / 改进建议 /
 * 故事层，七类结果一个入口。
 *
 * 两条刻意的取舍：
 * 1. **首次进入不自动请求**——一次要打 6 个接口（其中一个还调模型），打开页面就烧钱不可接受，
 *    所以每类结果都由作者点按钮才取（读者行为同理：点按钮才读开关与数据；
 *    改进建议也同理：点按钮才拉，参数改了也不会自动重拉；故事层两个接口一起拉，纯本地所以不心疼）。
 *    结果留在本地直到重新体检。
 * 2. 界面上只给结论与人话，不 dump 原始 JSON：想看原始字段应该去后端的 OpenAPI 文档。
 */
export function InsightPanel({ projectId, chapters }: Props) {
  const [kind, setKind] = useState<Kind>("branch");
  const [busy, setBusy] = useState<Kind | null>(null);
  const [error, setError] = useState("");
  const [errorDetail, setErrorDetail] = useState("");
  const [focus, setFocus] = useState("");

  const [branch, setBranch] = useState<BranchReportOut | null>(null);
  const [voice, setVoice] = useState<VoiceReportOut | null>(null);
  const [continuity, setContinuity] = useState<ContinuityReportOut | null>(null);
  const [scan, setScan] = useState<ConsistencyScanOut | null>(null);
  /** 采集开关：null = 还没读过（界面按后端口径"默认关"显示，且**不自动请求**） */
  const [settings, setSettings] = useState<TelemetrySettingsOut | null>(null);
  const [analytics, setAnalytics] = useState<PlaytestAnalyticsOut | null>(null);
  const [advice, setAdvice] = useState<BranchRecommendationsOut | null>(null);
  /** 故事层：两个接口一次拉齐（都是纯本地计算），分段只是同一份结果的两个视角 */
  const [story, setStory] = useState<StoryMetricsOut | null>(null);
  const [adaptive, setAdaptive] = useState<AdaptivePlanOut | null>(null);
  const [storySection, setStorySection] = useState<"arcs" | "adaptive">("arcs");
  /** 改进建议的两个参数：改完只提示"下面还是旧结果"，要不要重拉由作者点按钮决定 */
  const [adviceMinRuns, setAdviceMinRuns] = useState(String(DEFAULT_MIN_RUNS));
  const [includeReaders, setIncludeReaders] = useState(true);
  /** 开关自己一套 busy / 错误：切换开关不该把体检的加载态和错误串在一起 */
  const [savingSwitch, setSavingSwitch] = useState(false);
  const [switchError, setSwitchError] = useState("");

  const titles = useMemo(() => chapterTitleMap(chapters), [chapters]);
  /** 输入框里的原文 → 真正发出去的 min_runs（空/非法回落默认值，超范围夹住） */
  const minRunsValue = parseMinRuns(adviceMinRuns);

  const hasResult =
    kind === "branch"
      ? branch !== null
      : kind === "voice"
        ? voice !== null
        : kind === "continuity"
          ? continuity !== null
          : kind === "scan"
            ? scan !== null
            : kind === "advice"
              ? advice !== null
              : kind === "story"
                ? story !== null || adaptive !== null
                : settings !== null || analytics !== null;

  const run = useCallback(
    async (which: Kind) => {
      setBusy(which);
      setError("");
      setErrorDetail("");
      try {
        if (which === "branch") setBranch(await fetchBranchReport(projectId));
        else if (which === "voice") setVoice(await fetchVoiceReport(projectId));
        else if (which === "continuity") setContinuity(await fetchContinuityReport(projectId));
        else if (which === "scan") setScan(await consistencyScan(projectId, { focus }));
        else if (which === "advice") {
          setAdvice(
            await fetchBranchRecommendations(projectId, {
              minRuns: minRunsValue,
              includeReaders,
            })
          );
        } else if (which === "story") {
          // 两个端点都是纯本地计算，一起拉：作者点一下就同时拿到"伏笔与弧线"和"自适应方案"
          const [nextStory, nextAdaptive] = await Promise.all([
            fetchStoryMetrics(projectId),
            fetchAdaptivePlan(projectId),
          ]);
          setStory(nextStory);
          setAdaptive(nextAdaptive);
        } else {
          // 开关与数据一次拉齐：作者点一下就能看到"开没开 + 数据长什么样"
          const [nextSettings, nextAnalytics] = await Promise.all([
            fetchTelemetrySettings(projectId),
            fetchPlaytestAnalytics(projectId),
          ]);
          setSettings(nextSettings);
          setAnalytics(nextAnalytics);
          setSwitchError("");
        }
      } catch (e) {
        setError(
          e instanceof ApiError ? e.message : e instanceof Error ? e.message : "体检失败"
        );
        setErrorDetail(errorDetailOf(e));
      } finally {
        setBusy(null);
      }
    },
    [projectId, focus, minRunsValue, includeReaders]
  );

  /** 切换采集开关（需 owner / editor；viewer 会 403，这里如实说明而不是假装成功）。 */
  const toggleTelemetry = useCallback(
    async (next: boolean) => {
      setSavingSwitch(true);
      setSwitchError("");
      try {
        const saved = await saveTelemetrySettings(projectId, next);
        setSettings((prev) => ({
          projectId: prev?.projectId ?? projectId,
          enabled: saved.enabled,
          defaultEnabled: prev?.defaultEnabled ?? false,
        }));
      } catch (e) {
        const detail = errorDetailOf(e);
        setSwitchError(
          `${
            e instanceof ApiError && e.status === 403
              ? "只有工程 owner / editor 能改这个开关（当前账号没有权限）"
              : e instanceof Error
                ? e.message
                : "切换失败"
          }${detail ? `：${detail}` : ""}`
        );
      } finally {
        setSavingSwitch(false);
      }
    },
    [projectId]
  );

  function renderBranch(report: BranchReportOut) {
    const cov = viewCoverage(report.coverage);
    const counts = report.counts ?? { error: 0, warn: 0, info: 0 };
    const cycles = (report.cycles ?? []).filter((c) => c.canLoopForever || c.reachable);
    const deadly = cycles.filter((c) => c.canLoopForever).length;
    const endings = report.endings;

    return (
      <>
        <div className={styles.cards}>
          <div className={styles.card}>
            <span>错误</span>
            <strong className={counts.error ? styles.bad : undefined}>{counts.error ?? 0}</strong>
          </div>
          <div className={styles.card}>
            <span>警告</span>
            <strong>{counts.warn ?? 0}</strong>
          </div>
          <div className={styles.card}>
            <span>提示</span>
            <strong>{counts.info ?? 0}</strong>
          </div>
          <div className={styles.card}>
            <span>分支覆盖</span>
            <strong>{cov.scorePercent}%</strong>
          </div>
          <div className={styles.card}>
            <span>看到了也选不到</span>
            <strong className={cov.impossibleChoices ? styles.bad : undefined}>
              {cov.impossibleChoices}
            </strong>
          </div>
          <div className={styles.card}>
            <span>没有路径走到</span>
            <strong className={cov.neverTraversedChoices ? styles.bad : undefined}>
              {cov.neverTraversedChoices}
            </strong>
          </div>
          <div className={styles.card}>
            <span>死循环</span>
            <strong className={deadly ? styles.bad : undefined}>{deadly}</strong>
          </div>
          <div className={styles.card}>
            <span>结局可达</span>
            <strong>
              {endings?.reachableDeclared ?? 0}/{endings?.declaredCount ?? 0}
            </strong>
          </div>
        </div>

        <p className={styles.summary}>{summarizeFindings(report.findings)}</p>
        <p className={styles.note}>{cov.verdict}</p>
        <p className={styles.note}>
          {cov.labelsText}；{cov.choicesText}；{cov.pathsText}
        </p>
        {cov.choicesNote ? <p className={styles.note}>{cov.choicesNote}</p> : null}
        {(endings?.undeclaredTerminals ?? []).length > 0 ? (
          <p className={styles.note}>
            可达但没登记为结局的终点（这里是 label 名）：
            {(endings?.undeclaredTerminals ?? []).join("、")}
          </p>
        ) : null}

        {cycles.length > 0 ? (
          <div className={styles.block}>
            <span className={styles.blockTitle}>回路与死循环（{cycles.length}）</span>
            <ul className={styles.list}>
              {cycles.slice(0, MAX_CYCLE_ROWS).map((c) => (
                <li key={c.labels.join(">")}>
                  <span className={styles.sev} data-sev={c.canLoopForever ? "error" : "info"}>
                    {c.canLoopForever ? "死循环" : "回路"}
                  </span>
                  <span className={styles.msg}>{c.labels.join(" → ")}</span>
                  {c.canLoopForever ? (
                    <span className={styles.dim}>没有变量变化也没有条件出口，玩家出不去</span>
                  ) : null}
                  {!c.reachable ? (
                    <span className={styles.dim}>（从入口走不到，暂时影响不到玩家）</span>
                  ) : null}
                </li>
              ))}
            </ul>
            {cycles.length > MAX_CYCLE_ROWS ? (
              <p className={styles.note}>…另有 {cycles.length - MAX_CYCLE_ROWS} 条回路未列出</p>
            ) : null}
          </div>
        ) : null}

        <FindingList
          findings={report.findings}
          titles={titles}
          emptyText="没有发现问题：label 都走得到、条件都能成立、结局都对得上。"
        />
      </>
    );
  }

  function renderVoice(report: VoiceReportOut) {
    const view = viewVoiceReport(report);
    const characters = (report.characters ?? []).filter(Boolean);
    const pairs = (report.confusablePairs ?? []).filter(Boolean);

    return (
      <>
        <p className={styles.summary}>{view.text}</p>

        {pairs.length > 0 ? (
          <div className={styles.block}>
            <span className={styles.blockTitle}>声线太像的角色对（{pairs.length}）</span>
            <ul className={styles.list}>
              {pairs.map((p) => (
                <li key={`${p.aId}-${p.bId}`}>
                  <span className={styles.sev} data-sev="watch">
                    可混淆
                  </span>
                  <span className={styles.msg}>
                    {p.a} ↔ {p.b}
                  </span>
                  <span className={styles.dim}>
                    距离{" "}
                    {Number.isFinite(p.distance) ? p.distance.toFixed(3) : "未知"}
                    （越小越像，读者可能分不清谁在说话）
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {characters.length === 0 ? <p className={styles.note}>后端没有返回任何角色。</p> : null}

        {characters.map((c) => {
          const chapterRows = (c.chapters ?? []).filter(Boolean);
          const phrases = (c.signaturePhrases ?? [])
            .map((s) => (s.phrase ?? "").trim())
            .filter(Boolean);
          return (
            <div className={styles.block} key={c.characterId}>
              <span className={styles.blockTitle}>
                {c.displayName || c.characterId}
                {c.ready
                  ? `（${c.utteranceCount} 句台词 / 出场 ${c.chaptersSpoken ?? 0} 章）`
                  : ""}
              </span>
              <p className={styles.note}>
                {c.ready
                  ? calibrationNote(c.calibration)
                  : `未评估：${c.reason || "台词不足"}`}
              </p>
              {c.ready && phrases.length > 0 ? (
                <p className={styles.note}>
                  口癖 / 习惯说法：{phrases.slice(0, 8).join("、")}
                </p>
              ) : null}
              {c.ready && chapterRows.length === 0 ? (
                <p className={styles.note}>
                  没有可逐章比对的章节（每章台词太少，或这个角色只出场一两章）。
                </p>
              ) : null}
              {chapterRows.length > 0 ? (
                <ul className={styles.list}>
                  {chapterRows.map((ch) => {
                    const d = driftView(ch.level);
                    const score = driftScoreText(ch);
                    return (
                      <li key={`${c.characterId}-${ch.chapterId}`}>
                        <span className={styles.sev} data-sev={d.tone}>
                          {d.label}
                        </span>
                        <span className={styles.msg}>{chapterLabel(ch.chapterId, titles)}</span>
                        <span className={styles.dim}>{d.hint}</span>
                        {score ? <span className={styles.dim}>{score}</span> : null}
                      </li>
                    );
                  })}
                </ul>
              ) : null}
            </div>
          );
        })}

        {(report.notes ?? []).length > 0 ? (
          <p className={styles.note}>{(report.notes ?? []).join("；")}</p>
        ) : null}
      </>
    );
  }

  function renderContinuity(report: ContinuityReportOut) {
    const summary = report.summary;
    const checks = Object.entries(summary?.checks ?? {})
      .map(([code, v]) => ({ code, checked: v?.checked ?? 0, issues: v?.issues ?? 0 }))
      .sort((a, b) => b.issues - a.issues || b.checked - a.checked);
    const unknownRows = Object.entries(summary?.unknown ?? {}).filter(([, v]) => v > 0);

    return (
      <>
        <p className={styles.summary}>{summarizeFindings(report.findings)}</p>
        <p className={styles.note}>
          读了 {summary?.chapters ?? 0} 章、{summary?.dialogueLines ?? 0} 条对白、对比{" "}
          {summary?.characters ?? 0} 个角色、{summary?.characterLinks ?? 0} 条角色关系、
          {summary?.locationLinks ?? 0} 条地点通路、{summary?.timelineEvents ?? 0} 个时间线事件。
        </p>

        {checks.length > 0 ? (
          <div className={styles.block}>
            <span className={styles.blockTitle}>各项检查跑了多少、报了几条</span>
            <ul className={styles.list}>
              {checks.map((r) => (
                <li key={r.code}>
                  <span className={styles.sev} data-sev={r.issues > 0 ? "warn" : "info"}>
                    {codeLabel(r.code)}
                  </span>
                  <span className={styles.msg}>
                    查了 {r.checked} 处，报出 {r.issues} 条
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {unknownRows.length > 0 ? (
          <div className={styles.block}>
            <span className={styles.blockTitle}>机器也拿不准的（这些不算「通过」）</span>
            <ul className={styles.list}>
              {unknownRows.map(([key, n]) => (
                <li key={key}>
                  <span className={styles.msg}>{unknownKeyLabel(key)}</span>
                  <span className={styles.dim}>{n} 处</span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        <FindingList
          findings={report.findings}
          titles={titles}
          emptyText="没有发现问题：说话人都登记过、关系边没有悬空、时间线顺序一致。"
        />
      </>
    );
  }

  function renderScan(result: ConsistencyScanOut) {
    const cov = viewScanCoverage(result.coverage);
    const issues = (result.issues ?? []).filter(Boolean);
    const shown = issues.slice(0, MAX_SCAN_ROWS);
    const windowErrors = (result.windowErrors ?? []).filter(Boolean);

    return (
      <>
        <p className={styles.summary}>{scanCoverageSentence(result)}</p>

        <div className={styles.cards}>
          <div className={styles.card}>
            <span>本次扫到</span>
            <strong className={cov.complete ? undefined : styles.bad}>
              {cov.scanned}/{cov.scannable} 章
            </strong>
          </div>
          <div className={styles.card}>
            <span>覆盖率</span>
            <strong className={cov.complete ? undefined : styles.bad}>{cov.percent}%</strong>
          </div>
          <div className={styles.card}>
            <span>窗口</span>
            <strong>{result.coverage?.windowsRun ?? 0}</strong>
          </div>
          <div className={styles.card}>
            <span>失败的窗口</span>
            <strong className={result.coverage?.windowsFailed ? styles.bad : undefined}>
              {result.coverage?.windowsFailed ?? 0}
            </strong>
          </div>
          <div className={styles.card}>
            <span>没扫到的章</span>
            <strong className={cov.missedChapterIds.length ? styles.bad : undefined}>
              {cov.missedChapterIds.length}
            </strong>
          </div>
          <div className={styles.card}>
            <span>冲突</span>
            <strong>{issues.length}</strong>
          </div>
        </div>

        {result.error ? <p className={styles.error}>{result.error}</p> : null}

        {cov.missedChapterIds.length > 0 ? (
          <p className={styles.note}>
            没扫到的章节本轮没有结论，别当成「没问题」：
            {cov.missedChapterIds.map((id) => chapterLabel(id, titles)).join("、")}
          </p>
        ) : null}

        {cov.notes.map((n) => (
          <p key={n} className={styles.note}>
            {n}
          </p>
        ))}
        {result.issuesTruncated > 0 ? (
          <p className={styles.note}>
            另有 {result.issuesTruncated} 条冲突超出合并上限，没列出来。
          </p>
        ) : null}
        {result.issuesDroppedByWindowCap > 0 ? (
          <p className={styles.note}>
            另有 {result.issuesDroppedByWindowCap} 条冲突超出单窗上限，未纳入合并。
          </p>
        ) : null}

        {windowErrors.length > 0 ? (
          <div className={styles.block}>
            <span className={styles.blockTitle}>失败的窗口（{windowErrors.length}）</span>
            <ul className={styles.list}>
              {windowErrors.map((w) => (
                <li key={w.index}>
                  <span className={styles.sev} data-sev="error">
                    失败
                  </span>
                  <span className={styles.msg}>
                    第 {w.index + 1} 段（
                    {(w.chapterIds ?? [])
                      .map((id) => chapterLabel(id, titles))
                      .filter(Boolean)
                      .join("、")}
                    ）：{w.error}
                  </span>
                </li>
              ))}
            </ul>
          </div>
        ) : null}

        {issues.length === 0 ? (
          <p className={styles.ok}>
            {result.error ? "本轮没有可用结论。" : "没有发现明显冲突。"}
          </p>
        ) : (
          <>
            <p className={styles.note}>
              {summarizeScanIssues(issues)}
              {result.model ? `本次使用的模型：${result.model}` : ""}
            </p>
            <ul className={styles.list}>
              {shown.map((issue, i) => {
                const tone = scanSeverityTone(issue.severity);
                const chaptersText = (issue.chapterIds ?? [])
                  .map((id) => chapterLabel(id, titles))
                  .filter(Boolean)
                  .join("、");
                return (
                  <li key={`${issue.category}-${i}`}>
                    <span className={styles.sev} data-sev={tone}>
                      {scanSeverityLabel(issue.severity)}
                      {scanCategoryLabel(issue.category)}
                    </span>
                    <span className={styles.msg}>
                      {issue.quote ? `「${issue.quote}」` : ""}
                      {issue.description}
                    </span>
                    {issue.suggestion ? (
                      <span className={styles.dim}>建议：{issue.suggestion}</span>
                    ) : null}
                    <span className={styles.dim}>
                      {chaptersText}
                      {issue.foundInWindows >= 2
                        ? `${chaptersText ? " · " : ""}${issue.foundInWindows} 个窗口都报了`
                        : ""}
                    </span>
                  </li>
                );
              })}
            </ul>
            {issues.length > shown.length ? (
              <p className={styles.note}>
                …另有 {issues.length - shown.length} 条未列出（先修上面的）。
              </p>
            ) : null}
          </>
        )}
      </>
    );
  }

  function renderReaders() {
    const enabled = settings?.enabled ?? false;
    const copy = telemetrySwitchCopy(enabled);

    // 开关永远可见：数据没读到也能开/关（这就是"点进子标签就能改"的那一步）
    const switchBox = (
      <div className={styles.switchRow}>
        <label className={styles.switchLabel}>
          <input
            type="checkbox"
            checked={enabled}
            disabled={savingSwitch}
            onChange={(e) => void toggleTelemetry(e.target.checked)}
            aria-label="读者行为采集开关"
          />
          {copy.title}
          {savingSwitch ? "（保存中…）" : ""}
        </label>
        <span className={styles.dim}>
          {settings === null ? "还没读取过服务端状态，这里按默认「关」显示" : "已与服务端一致"}
        </span>
      </div>
    );

    const shell = (body: ReactNode) => (
      <>
        {switchBox}
        <p className={styles.note}>
          {copy.hint}
          {settings?.defaultEnabled === false ? "（工程没显式开启时，后端默认按关闭处理）" : ""}
        </p>
        {switchError ? <p className={styles.error}>{switchError}</p> : null}
        {body}
      </>
    );

    if (analytics === null) {
      return shell(<p className={styles.note}>{hasResult ? copy.emptyText : TAB_EMPTY[kind]}</p>);
    }

    const sample = sampleView(analytics.sample);
    const coverage = coverageView(analytics.coverage);
    const funnel = funnelView(analytics.funnel, (id) => chapterLabel(id, titles));
    const endings = endingsView(analytics.endings);
    const readers = analytics.runs;
    // 菜单排序：有"从没人选"的排前面（那才是作者要找的东西），其余按被选次数降序
    const menus = [...(analytics.choices.menus ?? [])]
      .map((m) => menuView(m, chapterLabel(m.chapterId, titles)))
      .sort(
        (a, b) =>
          b.rows.filter((r) => r.tone === "warn").length -
            a.rows.filter((r) => r.tone === "warn").length ||
          b.rows.reduce((n, r) => n + r.selected, 0) - a.rows.reduce((n, r) => n + r.selected, 0)
      );
    const shownMenus = menus.slice(0, MAX_READER_MENUS);

    return shell(
      <>
        <div className={styles.cards}>
          <div className={styles.card}>
            <span>试玩次数</span>
            <strong className={sample.tone === "warn" ? styles.bad : undefined}>
              {analytics.sample.runs}
            </strong>
          </div>
          <div className={styles.card}>
            <span>选择次数</span>
            <strong>{analytics.sample.choices}</strong>
          </div>
          <div className={styles.card}>
            <span>读者侧覆盖</span>
            <strong className={coverage.tone === "bad" ? styles.bad : undefined}>
              {coverage.percent.toFixed(0)}%
            </strong>
          </div>
          <div className={styles.card}>
            <span>走过的结局</span>
            <strong>
              {analytics.endings.declaredReached}/{analytics.endings.declaredTotal}
            </strong>
          </div>
          <div className={styles.card}>
            <span>没走到结局</span>
            <strong className={analytics.endings.unfinishedRuns ? styles.bad : undefined}>
              {analytics.endings.unfinishedRuns}
            </strong>
          </div>
          <div className={styles.card}>
            <span>试玩里读了几章</span>
            <strong>{(readers.chaptersPlayed.avg || 0).toFixed(1)}</strong>
          </div>
          <div className={styles.card}>
            <span>每次试玩选择数</span>
            <strong>{(readers.choicesReported.median || 0).toFixed(0)}</strong>
          </div>
          <div className={styles.card}>
            <span>时长中位</span>
            <strong>
              {readers.durationSeconds
                ? `${Math.round(readers.durationSeconds.median / 60)} 分`
                : "—"}
            </strong>
          </div>
        </div>

        <p className={styles.summary}>{sample.headline}</p>
        <p className={styles.note}>{sample.hint}</p>

        {!enabled ? (
          <p className={styles.note}>
            现在开关是关的：下面的数据是之前开启时采集到的历史记录；关掉之后不会再新增，
            试玩器那边的上报会被后端按 403 拒绝（前端识别后停止本次会话的后续上报，不会刷接口）。
          </p>
        ) : null}

        <p className={styles.note}>{OPTION_COPY_NOTE}</p>

        <div className={styles.block}>
          <span className={styles.blockTitle}>选项占比（{menus.length} 个菜单）</span>
          {menus.length === 0 ? (
            <p className={styles.note}>
              还没有任何归到菜单上的选择。可能原因：剧本结构分析拿不到菜单（选择记录里只有
              menu_id 与序号），或者读者还没走到任何菜单。
            </p>
          ) : null}
          {shownMenus.map((menu) => (
            <div className={styles.block} key={menu.key}>
              <span className={styles.blockTitle}>
                {menu.title}（{menu.summary}）
              </span>
              <ul className={styles.bars}>
                {menu.rows.map((row) => (
                  <li
                    className={styles.shareRow}
                    key={row.key}
                    data-never={row.tone === "warn" ? "1" : "0"}
                  >
                    <span className={styles.shareLabel}>
                      {row.label}
                      {row.note ? <span className={styles.dim}>（{row.note}）</span> : null}
                    </span>
                    <span className={styles.bar}>
                      <span className={styles.barFill} style={{ width: `${row.percent}%` }} />
                    </span>
                    <span className={styles.shareValue}>
                      {row.shareText} · {row.selected} 次
                    </span>
                  </li>
                ))}
              </ul>
              <p className={styles.note}>
                {menu.touchedText}；{menu.neverSelectedText}
              </p>
              {menu.notes.map((n) => (
                <p key={n} className={styles.note}>
                  {n}
                </p>
              ))}
            </div>
          ))}
          {menus.length > shownMenus.length ? (
            <p className={styles.note}>
              …另有 {menus.length - shownMenus.length} 个菜单未列出（先看上面这些）。
            </p>
          ) : null}
        </div>

        <div className={styles.block}>
          <span className={styles.blockTitle}>章级漏斗与流失</span>
          <p className={styles.note}>{funnel.verdict}</p>
          {funnel.rows.length > 0 ? (
            <ul className={styles.list}>
              {funnel.rows.map((row) => (
                <li key={row.key}>
                  <span className={styles.sev} data-sev={row.tone === "warn" ? "warn" : "ok"}>
                    {row.reached} 次到达
                  </span>
                  <span className={styles.msg}>{row.title}</span>
                  <span className={styles.dim}>
                    {row.dropText}；其中 {row.choosingRuns} 次在这一章做过选择
                  </span>
                </li>
              ))}
            </ul>
          ) : null}
          {funnel.notes.map((n) => (
            <p key={n} className={styles.note}>
              {n}
            </p>
          ))}
        </div>

        <div className={styles.block}>
          <span className={styles.blockTitle}>结局分布</span>
          <p className={styles.summary}>{endings.headline}</p>
          {endings.rows.length > 0 ? (
            <ul className={styles.list}>
              {endings.rows.map((row) => (
                <li key={row.key}>
                  <span className={styles.sev} data-sev={row.tone === "warn" ? "warn" : "ok"}>
                    {row.runs} 次
                  </span>
                  <span className={styles.msg}>
                    {row.title}
                    <span className={styles.dim}>（{row.shareText}）</span>
                  </span>
                  {row.note ? <span className={styles.dim}>{row.note}</span> : null}
                </li>
              ))}
            </ul>
          ) : (
            <p className={styles.note}>没有任何试玩走到可识别的结局。</p>
          )}
          {endings.neverReachedText ? (
            <p className={styles.note}>{endings.neverReachedText}</p>
          ) : null}
          {endings.neverReached.length > 0 ? (
            <ul className={styles.list}>
              {endings.neverReached.map((row) => (
                <li key={row.label}>
                  <span className={styles.sev} data-sev="warn">
                    没人走到
                  </span>
                  <span className={styles.msg}>{row.name}</span>
                  <code>{row.label}</code>
                  <span className={styles.dim}>
                    {row.reachableInScript
                      ? "静态分析认为可达 → 要么入口太难找，要么条件实际写死了"
                      : "静态分析也认为不可达 → 这条线现在到不了"}
                  </span>
                </li>
              ))}
            </ul>
          ) : null}
          {endings.notes.map((n) => (
            <p key={n} className={styles.note}>
              {n}
            </p>
          ))}
        </div>

        <div className={styles.block}>
          <span className={styles.blockTitle}>读者侧分支覆盖率</span>
          <p className={styles.summary}>{coverage.text}</p>
          <p className={styles.note}>{coverage.menusNeverTouchedText}</p>
          {coverage.notes.map((n) => (
            <p key={n} className={styles.note}>
              {n}
            </p>
          ))}
        </div>

        {analytics.choices.unknownMenus.length > 0 ? (
          <p className={styles.note}>
            有 {analytics.choices.unknownMenus.length} 个 menu_id 在当前剧本里找不到（剧本改过？）：
            {analytics.choices.unknownMenus
              .slice(0, 6)
              .map((m) => `${m.menuId}(${m.selections} 次)`)
              .join("、")}
          </p>
        ) : null}

        {(analytics.notes ?? []).map((n) => (
          <p key={n} className={styles.note}>
            {n}
          </p>
        ))}
      </>
    );
  }

  /**
   * 改进建议：这一屏最容易被误读的地方就是顶部那句 `basis`，所以它排在最前面，
   * 而且 `script-only` 时用一句明说的警告 + 后端的 `sampleNote` 把"还看不出来"讲清楚。
   */
  function renderAdvice(result: BranchRecommendationsOut) {
    const basis = basisView(result.basis, result.sampleNote);
    const summary = adviceSummary(result);
    const rows = adviceRows(result);
    const minRuns = minRunsView(result.minRuns);
    const stale = adviceStale(result, { minRuns: minRunsValue, includeReaders });
    const empty = emptyAdvice(result);
    const variety = choiceVarietyView(result.choiceVariety);

    return (
      <>
        <div className={styles.block}>
          <p className={basis.tone === "warn" ? styles.warnText : styles.summary}>
            {basis.headline}
          </p>
          <p className={styles.note}>{basis.sampleNote}</p>
          {basis.caveat ? <p className={styles.note}>{basis.caveat}</p> : null}
        </div>

        {/* 选项分类（Dunyazad 三分法的结构代理）：只看结构，不判断玩家心理 */}
        {variety ? (
          <div className={styles.block} data-testid="choice-variety">
            <p className={styles.summary}>{variety.headline}</p>
            <p className={styles.note}>
              {variety.parts.map((part) => `${part.label} ${part.count}`).join(" · ")}
            </p>
            {variety.relaxedMenus.length > 0 ? (
              <p className={styles.note}>
                怎么选都一样的选择点：{variety.relaxedMenus.slice(0, 6).join("、")}
                {variety.relaxedMenus.length > 6 ? ` 等 ${variety.relaxedMenus.length} 处` : ""}
              </p>
            ) : null}
            {variety.notes.map((note) => (
              <p key={note} className={styles.note}>
                {note}
              </p>
            ))}
          </div>
        ) : null}

        {stale.stale ? <p className={styles.note}>{stale.reason}</p> : null}

        <p className={styles.note}>
          {minRuns.text}：{minRuns.hint}
        </p>
        {minRuns.notes.map((n) => (
          <p key={n} className={styles.note}>
            {n}
          </p>
        ))}

        <div className={styles.cards}>
          <div className={styles.card}>
            <span>必须改</span>
            <strong className={summary.counts.error ? styles.bad : undefined}>
              {summary.counts.error}
            </strong>
          </div>
          <div className={styles.card}>
            <span>建议改</span>
            <strong>{summary.counts.warn}</strong>
          </div>
          <div className={styles.card}>
            <span>可以看看</span>
            <strong>{summary.counts.info}</strong>
          </div>
          <div className={styles.card}>
            <span>共</span>
            <strong>{summary.counts.total}</strong>
          </div>
          <div className={styles.card}>
            <span>有读者证据</span>
            <strong>{rows.filter((r) => r.confidence.tone === "evidence").length}</strong>
          </div>
          <div className={styles.card}>
            <span>纯静态推断</span>
            <strong>{rows.filter((r) => r.confidence.tone === "static").length}</strong>
          </div>
        </div>

        <p className={styles.summary}>{summary.headline}</p>
        {summary.confidenceText ? (
          <p className={styles.note}>{summary.confidenceText}</p>
        ) : null}
        {summary.notes.map((n) => (
          <p key={n} className={styles.note}>
            {n}
          </p>
        ))}

        {rows.length === 0 ? (
          <div className={styles.block}>
            <p className={styles.ok}>{empty.headline}</p>
            <p className={styles.note}>{empty.caveat}</p>
            {empty.notes.map((n) => (
              <p key={n} className={styles.note}>
                {n}
              </p>
            ))}
          </div>
        ) : (
          <AdviceList rows={rows} />
        )}

        {(result.notes ?? []).length > 0 ? (
          <p className={styles.note}>{(result.notes ?? []).join("；")}</p>
        ) : null}
      </>
    );
  }

  /** 故事层：同一份结果的两个视角，用分段切换（不动上面那排七个子标签）。 */
  function renderStory() {
    // 整体失败 / 正在加载时上面已经有错误块或加载提示：这里不再叠一段空状态
    if (!story && !adaptive && (error || busy !== null)) return null;
    const segment = (id: "arcs" | "adaptive", label: string) => (
      <button
        key={id}
        type="button"
        className={storySection === id ? styles.tabActive : styles.tab}
        onClick={() => setStorySection(id)}
      >
        {label}
      </button>
    );
    return (
      <>
        <div className={styles.segments}>
          {segment("arcs", "伏笔与弧线")}
          {segment("adaptive", "自适应选项")}
        </div>
        {storySection === "arcs" ? renderStoryArcs() : renderAdaptive()}
      </>
    );
  }

  /**
   * 伏笔与弧线。
   *
   * 两条不能省的口径：
   * - 「没有伏笔」绝不能显示成「回收率 0%」（`foreshadowView` 已经分好，这里只转述）。
   * - 情绪结论旁边**必须**有「这是关键词推断、可能读错」+ 证据句，否则作者会把推断当结论。
   */
  function renderStoryArcs() {
    if (!story) {
      return (
        <p className={styles.note}>
          还没有故事层结果。点上面的按钮开始分析：伏笔与自适应两段会一次拉齐（纯本地计算）。
        </p>
      );
    }
    const f = foreshadowView(story);
    const summary = summarizeStoryMetrics(story, titles);
    const hooks = openHookRows(story, titles);
    const arcs = emotionArcRows(story);
    const chapterRows = emotionChapterRows(story, titles);
    const breaks = emotionBreakRows(story, titles);
    const mismatchSummary = declaredMismatchSummary(story);
    const mismatchGroups = declaredMismatchGroups(story);
    const flatArcs = arcs.filter((a) => a.flat).length;

    return (
      <>
        <div className={styles.cards}>
          <div className={styles.card}>
            <span>伏笔</span>
            <strong>{f.total}</strong>
          </div>
          <div className={styles.card}>
            <span>已回收</span>
            <strong>{f.paid}</strong>
          </div>
          <div className={styles.card}>
            <span>未回收</span>
            <strong className={f.open ? styles.bad : undefined}>{f.open}</strong>
          </div>
          <div className={styles.card}>
            {/* 没有伏笔时这里是「—」而**不是** 0%：下面那行会解释为什么 */}
            <span>回收率</span>
            <strong>{f.percent === null ? "—" : `${f.percent}%`}</strong>
          </div>
          <div className={styles.card}>
            <span>最老未回收</span>
            <strong>{f.oldestOpenChapters} 章</strong>
          </div>
          <div className={styles.card}>
            <span>有弧线的角色</span>
            <strong>{arcs.length}</strong>
          </div>
          <div className={styles.card}>
            <span>全篇没变化</span>
            <strong>{flatArcs}</strong>
          </div>
          <div className={styles.card}>
            <span>逐章写反</span>
            <strong className={breaks.length ? styles.bad : undefined}>{breaks.length}</strong>
          </div>
        </div>

        <p className={styles.summary}>{summary.headline}</p>
        {summary.notes.map((n) => (
          <p key={n} className={styles.note}>
            {n}
          </p>
        ))}

        <div className={styles.block}>
          <span className={styles.blockTitle}>伏笔回收</span>
          <p className={styles.summary}>{f.headline}</p>
          <p className={styles.note}>{f.detail}</p>
          {f.notes.map((n) => (
            <p key={n} className={styles.note}>
              {n}
            </p>
          ))}
          {story.foreshadow?.note ? (
            <p className={styles.note}>{story.foreshadow.note}</p>
          ) : null}
        </div>

        {hooks.length > 0 ? (
          <div className={styles.block}>
            <span className={styles.blockTitle}>
              未回收的钩子（{hooks.length}，挂得最久的排最前）
            </span>
            <ul className={styles.list}>
              {hooks.slice(0, MAX_HOOK_ROWS).map((h) => (
                <li key={h.key}>
                  <span
                    className={styles.sev}
                    data-sev={h.chaptersOpen >= 5 ? "warn" : "info"}
                  >
                    {h.chaptersOpen >= 5 ? "挂得久" : "未回收"}
                  </span>
                  <span className={styles.msg}>{h.hook}</span>
                  <span className={styles.dim}>
                    埋在 {h.chapter || "（章节未知）"}；{h.ageText}
                  </span>
                </li>
              ))}
            </ul>
            {hooks.length > MAX_HOOK_ROWS ? (
              <p className={styles.note}>
                …另有 {hooks.length - MAX_HOOK_ROWS} 条未列出（最久的已经排在上面）
              </p>
            ) : null}
          </div>
        ) : f.hasRate ? (
          <p className={styles.ok}>没有未回收的钩子：埋下的伏笔都收完了。</p>
        ) : null}

        <div className={styles.block}>
          <span className={styles.blockTitle}>情感弧线（逐角色）</span>
          {/* 结论是推断来的：这句说明与结论同屏，不能折叠、不能只放在帮助里 */}
          <p className={styles.note}>{EMOTION_INFERENCE_NOTE}</p>
          {arcs.length === 0 ? (
            <p className={styles.note}>
              没有可评估的角色：后端要求一个角色至少 2 句台词才推断情绪，对白太少就一条都不出。
            </p>
          ) : (
            <ul className={styles.list}>
              {arcs.slice(0, MAX_ARC_ROWS).map((a) => (
                <li key={a.key}>
                  <span
                    className={styles.sev}
                    data-sev={a.flat ? "muted" : a.direction === "down" ? "warn" : "ok"}
                  >
                    {a.flat ? "没变化" : a.direction === "down" ? "往下走" : "往上走"}
                  </span>
                  <span className={styles.msg}>{a.character}</span>
                  <span className={styles.dim}>{a.text}</span>
                  {a.flatNote ? <span className={styles.dim}>{a.flatNote}</span> : null}
                </li>
              ))}
            </ul>
          )}
          {arcs.length > MAX_ARC_ROWS ? (
            <p className={styles.note}>…另有 {arcs.length - MAX_ARC_ROWS} 个角色未列出</p>
          ) : null}
          {story.emotionArcs?.note ? (
            <p className={styles.note}>{story.emotionArcs.note}</p>
          ) : null}
        </div>

        <div className={styles.block}>
          <span className={styles.blockTitle}>哪一章把情绪写反了（{breaks.length}）</span>
          {breaks.length === 0 ? (
            <p className={styles.note}>
              没有找到「局部走向与全篇相反」的章：只有全篇与该章都有明确走向、且方向相反时才报
              （本来就平的章属于「没写情绪」，不算写反）。
            </p>
          ) : (
            <ul className={styles.list}>
              {breaks.map((b) => (
                <li key={b.key}>
                  <span className={styles.sev} data-sev="warn">
                    {b.character}
                  </span>
                  <span className={styles.msg}>{b.comparison}</span>
                  <span className={styles.dim}>
                    位置：{b.chapter || "（章节未知）"}
                    {b.chapterId ? `（${b.chapterId}）` : ""}
                  </span>
                  <span className={styles.dim}>{b.message}</span>
                </li>
              ))}
            </ul>
          )}
        </div>

        {chapterRows.length > 0 ? (
          <div className={styles.block}>
            <span className={styles.blockTitle}>
              逐章走向与证据句（每章至少 2 句才评估，共 {chapterRows.length} 行）
            </span>
            <ul className={styles.list}>
              {chapterRows.slice(0, MAX_CHAPTER_ROWS).map((c) => (
                <li key={c.key}>
                  <span className={styles.sev} data-sev={c.broken ? "warn" : "muted"}>
                    {c.broken ? "与全篇相反" : "逐章"}
                  </span>
                  <span className={styles.msg}>
                    {c.character} · {c.chapter || "（章节未知）"}
                  </span>
                  <span className={styles.dim}>
                    {c.text}；这一章 {c.lines} 句台词
                  </span>
                  <span className={styles.dim}>{c.evidenceText}</span>
                </li>
              ))}
            </ul>
            {chapterRows.length > MAX_CHAPTER_ROWS ? (
              <p className={styles.note}>
                …另有 {chapterRows.length - MAX_CHAPTER_ROWS} 行未列出（与全篇相反的已排在最前）
              </p>
            ) : null}
          </div>
        ) : null}

        <div className={styles.block}>
          <span className={styles.blockTitle}>与节拍表声明的对账</span>
          <p className={styles.summary}>{mismatchSummary}</p>
          {mismatchGroups.map((g) => (
            <div key={g.issue} className={styles.block}>
              <span className={styles.blockTitle}>
                {g.label}（{g.rows.length}）
              </span>
              <p className={styles.note}>{g.hint}</p>
              <ul className={styles.list}>
                {g.rows.map((r) => (
                  <li key={r.key}>
                    <span
                      className={styles.sev}
                      data-sev={g.issue === "arc_reversed" ? "error" : "warn"}
                    >
                      {r.character}
                    </span>
                    <span className={styles.msg}>
                      声明「{r.declared}」→ 实际「{r.actual}」
                    </span>
                    <span className={styles.dim}>{r.message}</span>
                  </li>
                ))}
              </ul>
            </div>
          ))}
        </div>

        <FindingList
          findings={story.findings}
          titles={titles}
          emptyText="故事层没有额外结论：伏笔都收着、弧线有变化、与节拍表对得上。"
        />
      </>
    );
  }

  /**
   * 自适应选项。
   *
   * 最上面那句 `ADAPTIVE_EXPORT_NOTE` 是这一屏的重点：**导出默认不开**，
   * 不说清楚的话作者会以为"导出就有了"（这是后端专门为之写了文档的一条）。
   * 条件与声明块都给可复制的等宽文本（复制失败也能手动选中）。
   */
  function renderAdaptive() {
    if (!adaptive) {
      return (
        <p className={styles.note}>
          还没有自适应方案。点上面的按钮开始分析：与伏笔那段会一次拉齐（纯本地计算）。
        </p>
      );
    }
    const summary = summarizeAdaptivePlan(adaptive, titles);
    const counters = tendencyCounterRows(adaptive.tendencyCounters);
    const recipes = recipeRows(adaptive, { threshold: adaptive.recipeThreshold });
    const candidates = adaptiveCandidateRows(adaptive, titles);
    const prelude = preludeView(adaptive.prelude);

    return (
      <>
        <p className={styles.warnText}>{ADAPTIVE_EXPORT_NOTE}</p>

        <div className={styles.cards}>
          <div className={styles.card}>
            <span>计数器</span>
            <strong>{summary.counters}</strong>
          </div>
          <div className={styles.card}>
            <span>条件示例</span>
            <strong>{summary.recipes}</strong>
          </div>
          <div className={styles.card}>
            <span>值得做的菜单</span>
            <strong>{summary.candidates}</strong>
          </div>
          <div className={styles.card}>
            <span>声明块</span>
            <strong>{summary.hasPrelude ? "有" : "空"}</strong>
          </div>
        </div>

        <p className={styles.summary}>{summary.headline}</p>
        {summary.notes.map((n) => (
          <p key={n} className={styles.note}>
            {n}
          </p>
        ))}

        <div className={styles.block}>
          <span className={styles.blockTitle}>读者倾向计数器（{counters.length}）</span>
          {counters.length === 0 ? (
            <p className={styles.note}>
              还没有任何变量被选项改过：自适应的前提是「某个选项会改变量」，先在选项里改变量
              （set 块），这里才会出现计数器。
            </p>
          ) : (
            <ul className={styles.list}>
              {counters.map((c) => (
                <li key={c.key}>
                  <span className={styles.msg}>{c.variableKey}</span>
                  {c.ref ? <code>{c.ref}</code> : null}
                  <span className={styles.dim}>{c.note}</span>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className={styles.block}>
          <span className={styles.blockTitle}>可直接照抄的自适应条件（{recipes.length}）</span>
          {recipes.length === 0 ? (
            <p className={styles.note}>
              还没有条件示例：等有计数器之后，这里会给出「计数器 ≥ 门槛」这样可以直接粘进选项
              条件的表达式。
            </p>
          ) : null}
          {recipes.map((r) => (
            <div key={r.key} className={styles.block}>
              <span className={styles.msg}>{r.variableKey}</span>
              {r.condition ? (
                <CopyableCode
                  text={r.condition}
                  label={`复制 ${r.variableKey} 的自适应条件`}
                />
              ) : null}
              <p className={styles.note}>{r.meaning}</p>
              <p className={styles.note}>{r.note}</p>
            </div>
          ))}
        </div>

        <div className={styles.block}>
          <span className={styles.blockTitle}>值得做成自适应的菜单（{candidates.length}）</span>
          {candidates.length === 0 ? (
            <p className={styles.note}>
              没有菜单被判为值得做：只有「所有选项后果完全相同」或「读者几乎总是选同一个」时才会
              出现在这里。
            </p>
          ) : (
            <ul className={styles.list}>
              {candidates.map((c) => (
                <li key={c.key}>
                  <span className={styles.sev} data-sev="info">
                    候选
                  </span>
                  <span className={styles.msg}>{c.title}</span>
                  <span className={styles.dim}>为什么：{c.reason}</span>
                  <span className={styles.dim}>怎么改：{c.suggestion}</span>
                </li>
              ))}
            </ul>
          )}
        </div>

        <div className={styles.block}>
          <span className={styles.blockTitle}>要写进 .rpy 的声明块</span>
          <p className={styles.note}>{prelude.headline}</p>
          {prelude.empty ? (
            // 空的 prelude 绝不渲染成空代码框：说清为什么空、下一步做什么
            <p className={styles.note}>{prelude.emptyGuide}</p>
          ) : (
            <>
              <CopyableCode text={prelude.text} label="复制 .rpy 声明块" />
              <p className={styles.note}>{prelude.hint}</p>
            </>
          )}
        </div>

        {(adaptive.notes ?? []).map((n, i) => (
          <p key={`${i}-${n}`} className={styles.note}>
            {n}
          </p>
        ))}
      </>
    );
  }

  return (
    <div className={styles.wrap} data-testid="insight-panel">
      <div className={styles.head}>
        <strong className={styles.title}>深度体检</strong>
        <span className={styles.dim}>
          {kind === "readers"
            ? "读的是已落库的读者行为数据，不消耗模型额度"
            : kind === "advice"
              ? "纯本地计算 + 已落库的读者数据，不消耗模型额度"
              : kind === "story"
                ? "纯本地计算：读伏笔账本 + 台词关键词推断，不消耗模型额度"
                : TAB_COSTLY[kind]
                  ? "会调用模型，按章节消耗额度"
                  : "纯本地静态分析，不消耗模型额度"}
        </span>
      </div>

      <div className={styles.tabs}>
        {TABS.map((t) => (
          <button
            key={t.id}
            type="button"
            className={kind === t.id ? styles.tabActive : styles.tab}
            onClick={() => setKind(t.id)}
          >
            {t.label}
          </button>
        ))}
      </div>

      <p className={styles.hint}>{TAB_HINTS[kind]}</p>

      {TAB_COSTLY[kind] ? (
        <p className={styles.cost}>
          注意：这一类体检会把全书按重叠窗口分片送审模型，章节越多花的额度越多；点之前请确认
          已经配好模型 Key（没配会直接返回错误说明）。
        </p>
      ) : null}

      <div className={styles.toolbar}>
        {kind === "scan" ? (
          <input
            className={styles.focusInput}
            value={focus}
            onChange={(e) => setFocus(e.target.value)}
            placeholder="可选：聚焦某类问题，如「角色年龄」"
            disabled={busy !== null}
            aria-label="扫描聚焦"
          />
        ) : null}
        {kind === "advice" ? (
          <>
            <label className={styles.switchLabel}>
              <input
                type="checkbox"
                checked={includeReaders}
                disabled={busy !== null}
                onChange={(e) => setIncludeReaders(e.target.checked)}
                aria-label="是否使用读者数据"
              />
              用读者数据
            </label>
            <label className={styles.switchLabel}>
              试玩门槛
              <input
                className={styles.numInput}
                type="number"
                inputMode="numeric"
                min={MIN_RUNS_RANGE.min}
                max={MIN_RUNS_RANGE.max}
                value={adviceMinRuns}
                disabled={busy !== null}
                onChange={(e) => setAdviceMinRuns(e.target.value)}
                aria-label="经验判断门槛（试玩次数）"
              />
              次
            </label>
            <span className={styles.dim}>
              低于门槛只出静态建议；留空按默认 {DEFAULT_MIN_RUNS} 次算
            </span>
          </>
        ) : null}
        <button type="button" disabled={busy !== null} onClick={() => void run(kind)}>
          {runLabel(kind, busy === kind, hasResult)}
        </button>
      </div>

      {busy === kind ? (
        <p className={styles.note}>
          {kind === "readers"
            ? "正在读取采集开关与读者行为数据…"
            : kind === "advice"
              ? "正在生成改稿建议…（纯本地计算，不调模型）"
              : kind === "story"
                ? "正在分析故事层…（伏笔账本 + 台词关键词推断，纯本地计算）"
                : "正在体检…（全书分片扫描可能要等一会儿）"}
        </p>
      ) : null}

      {error ? (
        <div className={styles.block}>
          <p className={styles.error}>{error}</p>
          {errorDetail ? <p className={styles.note}>后端说明：{errorDetail}</p> : null}
          <button type="button" className={styles.link} onClick={() => void run(kind)}>
            重试
          </button>
        </div>
      ) : null}

      {/* 读者行为 / 改进建议 / 故事层各有自己的空状态（要连带开关或分段一起显示） */}
      {!hasResult && !error && busy === null && kind !== "readers" && kind !== "advice" && kind !== "story" ? (
        <p className={styles.note}>{TAB_EMPTY[kind]}</p>
      ) : null}

      {kind === "branch" && branch ? renderBranch(branch) : null}
      {kind === "voice" && voice ? renderVoice(voice) : null}
      {kind === "continuity" && continuity ? renderContinuity(continuity) : null}
      {kind === "scan" && scan ? renderScan(scan) : null}
      {kind === "readers" ? renderReaders() : null}
      {kind === "story" ? renderStory() : null}
      {kind === "advice"
        ? advice
          ? renderAdvice(advice)
          : !error && busy === null
            ? <p className={styles.note}>{TAB_EMPTY.advice}</p>
            : null
        : null}
    </div>
  );
}
