import type {
  AgentAction,
  AgentChatMessage,
  AgentContextMeta,
  AgentTaskKind,
  Location,
  LocationLink,
  VnProject,
  VoiceReport,
} from "../types/vn";
import {
  API_BASE,
  ApiError,
  apiFetch,
  authedRawFetch,
  buildApiHeaders,
  readErrorPayload,
} from "./http";
import { TIMEOUTS } from "./timeouts";
export interface ProjectSummary {
  id: string;
  title: string;
  logline?: string | null;
  genre?: string | null;
  updated_at: string;
  created_at: string;
  /** 章数（列表接口直接从 jsonb 数出来）：桌面图标角标 / 一眼进度 */
  chapters_count?: number;
}

export type WritingActivityDay = {
  date: string;
  added: number;
  removed: number;
  net: number;
  edits: number;
};

type ChapterStats = {
  index: number;
  id: string;
  title: string;
  words: number;
  lines: number;
  dialogueWords: number;
  dialogueRatio: number;
  speakers: string[];
  /** 所属卷 id（"" = 未分卷） */
  volumeId?: string;
};

/** 每卷进度（有卷时后端才返回内容） */
export type VolumeStats = {
  id: string;
  title: string;
  index: number;
  note: string;
  chapters: number;
  words: number;
  avgChapterWords: number;
  chapterIds: string[];
};

export type ProjectStats = {
  projectId: string;
  totals: {
    chapters: number;
    words: number;
    lines: number;
    avgChapterWords: number;
  };
  chapters: ChapterStats[];
  /** 每卷进度（含末尾的「未分卷」档；没有卷时为空数组） */
  volumes?: VolumeStats[];
  activity: WritingActivityDay[];
};

export function getProjectStats(id: string): Promise<ProjectStats> {
  return apiFetch<ProjectStats>(`/projects/${id}/stats`);
}

export function listProjects(): Promise<ProjectSummary[]> {
  return apiFetch<ProjectSummary[]>("/projects");
}

export function getProject(id: string): Promise<VnProject> {
  return apiFetch<VnProject>(`/projects/${id}`);
}

export function createProject(
  body: { title?: string; from_demo?: boolean; template_id?: string } = {}
): Promise<VnProject> {
  return apiFetch<VnProject>("/projects", {
    method: "POST",
    timeoutMs: TIMEOUTS.upload,
    body: JSON.stringify(body),
  });
}

export type ProjectTemplate = {
  id: string;
  title: string;
  genre: string;
  logline: string;
  characters: string[];
};

export function listProjectTemplates(): Promise<{ templates: ProjectTemplate[] }> {
  return apiFetch("/projects/templates");
}

export function putProject(
  id: string,
  data: VnProject,
  updatedAt?: string,
  opts?: {
    force?: boolean;
    /** Chapters this save actually modified — server merges only these. */
    chapterIds?: string[];
    /** Non-chapter top-level fields this save modified. */
    sections?: string[];
  }
): Promise<VnProject> {
  return apiFetch<VnProject>(`/projects/${id}`, {
    method: "PUT",
    body: JSON.stringify({
      data,
      updated_at: updatedAt,
      force: Boolean(opts?.force),
      chapter_ids: opts?.chapterIds?.length ? opts.chapterIds : undefined,
      sections: opts?.sections?.length ? opts.sections : undefined,
    }),
  });
}

export function patchProject(
  id: string,
  patch: { title?: string; logline?: string; genre?: string }
): Promise<VnProject> {
  return apiFetch<VnProject>(`/projects/${id}`, {
    method: "PATCH",
    body: JSON.stringify(patch),
  });
}

export function deleteProject(id: string): Promise<{ ok: boolean }> {
  return apiFetch<{ ok: boolean }>(`/projects/${id}`, { method: "DELETE" });
}

export function duplicateProject(id: string): Promise<VnProject> {
  return apiFetch<VnProject>(`/projects/${id}/duplicate`, { method: "POST" });
}

/** 前情提要（卷首回顾）：生成一段"之前发生了什么"的可读回述。 */
export type RecapOut = {
  text: string;
  model: string;
  chaptersUsed: number;
  archivesUsed: number;
  included: string[];
  label: string;
  mode: "before" | "volume";
  volumeId: string | null;
};

export function getRecap(
  id: string,
  body: { volumeId?: string; mode?: "before" | "volume"; upToChapterId?: string }
): Promise<RecapOut> {
  return apiFetch<RecapOut>(`/projects/${id}/recap`, {
    method: "POST",
    timeoutMs: TIMEOUTS.write,
    body: JSON.stringify({
      volume_id: body.volumeId,
      mode: body.mode ?? "before",
      up_to_chapter_id: body.upToChapterId,
    }),
  });
}

/** 多候选里每版的取舍依据（后端 `core/variant_select.py`；缺的字段=该信号未测量）。 */
export type MarkVariantRow = {
  /** 这版在**原始采样顺序**里的下标（排序后仍能映射回去） */
  variantIndex: number;
  rank: number;
  score?: number;
  temperature?: number | null;
  chars?: number;
  problems?: string[];
  /** 模型自身置信度（top-k 代理）；null/缺省 = 这次拿不到 logprobs，不是 0 分 */
  certainty?: {
    meanLogprob?: number;
    confidence?: number;
    peakedness?: number;
    composite?: number;
    thin?: boolean;
    kind?: string;
  } | null;
  /** 与其余候选的平均一致度；候选少于 3 份时为 null（没有多数可依） */
  consensus?: number | null;
  recommended?: boolean;
};

/** 写作页「标记批改」：让 AI 只改标出来的这一处（intent=advice 时只给建议，不动正文）。 */
export type MarkReviseOut = {
  replacement: string;
  /** 多候选：1–3 版改写（**已按证据排序**，第一版即 replacement） */
  candidates?: string[];
  /** 每版的分数/置信度/一致度/问题（与 candidates 同序） */
  ranking?: MarkVariantRow[];
  /** 这次用了哪些信号、缺了哪些（"未测量"≠"0 分"） */
  selectionNote?: string;
  advice: string;
  changed: boolean;
  model: string;
  styleUsed: boolean;
  /** 生成后自检发现、但没自动修好的问题（空/缺省 = 通过） */
  warnings?: string[];
  intent: "rewrite" | "advice";
  chapterId: string;
};

export function reviseMark(
  id: string,
  body: {
    chapterId: string;
    quote: string;
    prefix?: string;
    suffix?: string;
    instruction?: string;
    intent?: "rewrite" | "advice";
    /** 一次要几版改写（1–3） */
    candidates?: number;
  }
): Promise<MarkReviseOut> {
  return apiFetch<MarkReviseOut>(`/projects/${id}/marks/revise`, {
    method: "POST",
    timeoutMs: TIMEOUTS.long,
    body: JSON.stringify({
      chapter_id: body.chapterId,
      quote: body.quote,
      prefix: body.prefix ?? "",
      suffix: body.suffix ?? "",
      instruction: body.instruction ?? "",
      intent: body.intent ?? "rewrite",
      candidates: body.candidates ?? 1,
    }),
  });
}

/** 标记面板的一句提示：项目有没有可用文风记忆（决定"按你的文风改"是否生效）。 */
export function marksHint(id: string): Promise<{ hasStyleMemory: boolean }> {
  return apiFetch<{ hasStyleMemory: boolean }>(`/projects/${id}/marks/hint`);
}

export function importProjectFile(file: File, title?: string): Promise<VnProject> {
  const form = new FormData();
  form.append("file", file);
  if (title) form.append("title", title);
  return apiFetch<VnProject>("/projects/import", {
    method: "POST",
    timeoutMs: TIMEOUTS.upload,
    body: form,
  });
}

export async function exportRpy(id: string): Promise<string> {
  const res = await authedRawFetch(`/projects/${id}/export/rpy`);
  return res.text();
}

export async function exportJson(id: string): Promise<Blob> {
  const res = await authedRawFetch(`/projects/${id}/export/json`);
  return res.blob();
}

/** Submission export: whole project as readable Markdown. */
export async function exportMarkdown(id: string): Promise<Blob> {
  const res = await authedRawFetch(`/projects/${id}/export/markdown`);
  return res.blob();
}

/** Submission export: whole project as a styled Word document. */
export async function exportDocx(id: string): Promise<Blob> {
  const res = await authedRawFetch(`/projects/${id}/export/docx`);
  return res.blob();
}

export type SubmissionOptions = {
  /** true = 分章打包（一章一个 .docx + 投稿信息.txt） */
  split?: boolean;
  /** 正文首行缩进 2 字符（中文投稿惯例） */
  indent?: boolean;
  /** 每章另起一页 */
  pageBreak?: boolean;
  /** 每章末尾标注字数 */
  counts?: boolean;
  /** 是否带上章节梗概。默认 false：那是写给自己看的备注，会被编辑当正文 */
  synopsis?: boolean;
  /**
   * 注音是否写成 **Word 原生注音**（`w:ruby`）。默认 true。
   *
   * 关掉会回退成 `漢字（かんじ）` 这样的括号文本——原生注音的基准词只存在于
   * `w:rubyBase` 里，简单取文本的工具会漏掉（我们自己的导入侧认得，见 `core/file_text.py`）。
   */
  nativeRuby?: boolean;
  author?: string;
  contact?: string;
};

/**
 * 投稿包导出：投稿排版单篇（.docx）或分章包（.zip）。
 *
 * 与 `exportDocx` 的分工：那个是"把作品读出来"的通用导出，排版中性、给作者自己看；
 * 这个按投稿方的格式要求来（缩进/分页/字数/信息页/一章一文件）。
 */
export async function exportSubmission(
  id: string,
  opts: SubmissionOptions = {}
): Promise<Blob> {
  const params = new URLSearchParams();
  if (opts.split) params.set("split", "1");
  if (opts.indent === false) params.set("indent", "0");
  if (opts.pageBreak === false) params.set("page_break", "0");
  if (opts.counts === false) params.set("counts", "0");
  if (opts.synopsis) params.set("synopsis", "1");
  if (opts.nativeRuby === false) params.set("ruby", "0");
  if (opts.author?.trim()) params.set("author", opts.author.trim());
  if (opts.contact?.trim()) params.set("contact", opts.contact.trim());
  const qs = params.toString();
  const res = await authedRawFetch(
    `/projects/${id}/export/submission${qs ? `?${qs}` : ""}`
  );
  return res.blob();
}

export type GenerateRpyOut = {
  rpy: string;
  blocks: import("../types/vn").ScriptBlock[];
  usedLlm: boolean;
  proseHash: string;
};

export async function generateRpyFromProse(
  id: string,
  chapterId: string,
  prose: string,
  useLlm = true
): Promise<GenerateRpyOut> {
  return apiFetch<GenerateRpyOut>(`/projects/${id}/generate-rpy`, {
    method: "POST",
    body: JSON.stringify({
      timeoutMs: TIMEOUTS.chat,
      chapter_id: chapterId,
      prose,
      use_llm: useLlm,
    }),
  });
}

export interface LocalizationEntry {
  key: string;
  chapterId: string;
  kind: string;
  source: string;
  sourceHash: string;
  targets: Record<string, string>;
  status: Record<string, string>;
  note?: string;
}

export interface LocalizationOut {
  locales: Array<{ code: string; name?: string; status?: string }>;
  glossary: Array<{ term: string; targets: Record<string, string>; note?: string }>;
  entries: LocalizationEntry[];
  stats: {
    locales: Array<{
      code: string;
      name: string;
      status: string;
      translated: number;
      total: number;
      ratio: number;
    }>;
    entries: number;
    glossary: number;
    updatedAt?: string | null;
  };
}

export async function fetchLocalization(id: string): Promise<LocalizationOut> {
  return apiFetch<LocalizationOut>(`/projects/${id}/localization`);
}

export async function saveLocalization(
  id: string,
  payload: {
    locales: Array<{ code: string; name?: string; status?: string }>;
    entries: LocalizationEntry[];
    glossary: Array<{ term: string; targets: Record<string, string>; note?: string }>;
  }
): Promise<{ ok: boolean; stats: LocalizationOut["stats"] }> {
  return apiFetch(`/projects/${id}/localization`, {
    method: "PUT",
    body: JSON.stringify(payload),
  });
}

export async function prefillLocalization(
  id: string,
  locale: string
): Promise<{ ok: boolean; filled: number; stats: LocalizationOut["stats"] }> {
  return apiFetch(`/projects/${id}/localization/prefill?locale=${encodeURIComponent(locale)}`, {
    method: "POST",
  });
}

/** AI 代翻（草稿，状态标记为 ai，需人工校对后再导出）。 */
export async function aiTranslateLocalization(
  id: string,
  opts: { locale: string; localeName?: string; overwrite?: boolean; limit?: number }
): Promise<{
  ok: boolean;
  applied: number;
  skipped: number;
  remaining: number;
  /** 这一次实际交给模型的句数 */
  batch: number;
  model?: string;
  /** 这一次真实消耗的 token（服务端从模型响应里取） */
  tokens: { prompt: number; completion: number; total: number };
  /** 今日已消耗 / 每日上限（0 表示不限）——让用户看到共享额度还剩多少 */
  usedToday: number;
  dailyCap: number;
  message: string;
  stats: LocalizationOut["stats"];
}> {
  return apiFetch(`/projects/${id}/localization/translate`, {
    method: "POST",
    body: JSON.stringify({
      locale: opts.locale,
      locale_name: opts.localeName ?? "",
      overwrite: Boolean(opts.overwrite),
      limit: opts.limit ?? 25,
    }),
    // 这是一次真实的模型调用，默认 30s 太短：超时会让用户以为失败，
    // 而服务端其实已经写完并提交了译文（进度显示与实际不符）。
    timeoutMs: TIMEOUTS.chat,
  });
}

/** 下载 tl/<lang>/strings.rpy 打包 zip。 */
export async function downloadLocalizationZip(id: string): Promise<Blob> {
  const res = await authedRawFetch(`/projects/${id}/export/localization.rpy`);
  if (!res.ok) throw new ApiError(res.status, "还没有任何译文，先在本地化页填几条");
  return res.blob();
}

export interface AssetAuditOut {
  images: {
    total: number;
    items: Array<{ image: string; uses: number; chapters: string[] }>;
    suspicious: Array<{ image: string; uses: number; chapters: string[] }>;
  };
  audio: Record<
    string,
    { total: number; items: Array<{ file: string; uses: number }> }
  >;
  declaredTags: string[];
  unusedTags: string[];
  notes: string[];
}

export async function fetchAssetAudit(id: string): Promise<AssetAuditOut> {
  return apiFetch<AssetAuditOut>(`/projects/${id}/assets/audit`);
}

export interface ScriptReportOut {
  labels: { total: number; reachable: number; unreachable: string[] };
  endings: Array<{ chapterId: string; label: string; via: string; reachable: boolean }>;
  endingsReachable: number;
  branchPoints: Array<{
    chapterId: string;
    menuId: string;
    choices: number;
    conditional: number;
  }>;
  conditions: Array<{
    chapterId: string;
    where: string;
    text: string;
    detail: string;
    error?: string | null;
  }>;
  invalidConditions: Array<{ chapterId: string; text: string; error?: string | null }>;
  danglingJumps: Array<{ chapterId: string; target: string }>;
  variables: {
    declared: string[];
    used: string[];
    unused: string[];
    undeclared: string[];
  };
  duration: {
    chars: number;
    readSeconds: number;
    waitSeconds: number;
    totalSeconds: number;
    minutes: number;
    assumption: string;
  };
  repetition: {
    totalChars: number;
    duplicateChars: number;
    ratio: number;
    uniqueDuplicated: number;
    top: Array<{ text: string; count: number; chars: number }>;
  };
  counts: Record<string, number>;
}

/** 剧本工程体检（纯本地计算，不调模型）。 */
export async function fetchScriptReport(id: string): Promise<ScriptReportOut> {
  return apiFetch<ScriptReportOut>(`/projects/${id}/analysis/script-report`, {
    skipAuthRedirect: true,
  });
}

/* ------------------------------------------------------------------ 深度分析
 * 四个只读分析端点：前三个纯本地计算（点一下就有，不花模型额度），
 * 最后一个会调模型。形状对齐 backend/app/core/ 下的
 * branch_analysis / voice_fingerprint / continuity_graph / consistency_scan。
 * 结论等级沿用 error / warn / info 三态，后端口径是"没有 error 就算过"。
 */

/** 结论计数（`branch-report` 与 `continuity` 同形）。 */
export interface AnalysisCounts {
  error: number;
  warn: number;
  info: number;
  /** 后端口径：没有 error 就算过，warn / info 只是提示不是失败 */
  pass?: boolean;
}

/** 一条体检结论（`branch-report` 与 `continuity` 同形）。 */
export interface AnalysisFinding {
  /** 已知 error / warn / info；留 string 是为了后端将来加等级时不静默丢结论 */
  severity: string;
  code: string;
  message: string;
  /** 哪个分析器报的：branch / continuity */
  source?: string;
  /** 所在章节 id（可能为空：这条结论不属于某一章） */
  chapterId?: string;
  /** 相关 label（跳转点 / 结局） */
  label?: string;
  /** 相关角色（故事层的 `emotion_arc_break` 会带；其它分析器不带） */
  character?: string;
}

export interface BranchCoverage {
  labels: { total: number; reachable: number; ratio: number };
  choices: {
    /** 全部选项边 */
    total: number;
    /** 条件可满足 = 玩家看得见 */
    usable: number;
    /** 枚举出的可达路径确实走过 */
    traversed: number;
    /** 看得见、但没有任何路径走到 */
    neverTraversed: number;
    ratio: number;
    satisfiableRatio: number;
  };
  paths: {
    count: number;
    /** true = 路径枚举到上限就停了，组合还没列完（不是"只有这么多"） */
    truncated: boolean;
    minLabels: number;
    maxLabels: number;
    avgLabels: number;
  };
  terminals: string[];
  score: number;
}

export interface BranchCycle {
  labels: string[];
  length: number;
  reachable: boolean;
  hasVariableChange: boolean;
  hasConditionalExit: boolean;
  /** true = 玩家进去了出不来（视觉小说里最贵的一类 bug） */
  canLoopForever: boolean;
}

export interface BranchMenuChoice {
  index: number;
  text: string;
  condition: string;
  /** 选项的后果形态：jump / return / inline */
  effect: string;
  target: string | null;
  varsModified: string[];
  /** false = 条件恒不成立，玩家永远看不到这个选项 */
  available: boolean;
}

export interface BranchMenu {
  chapterId: string;
  label: string;
  menuId: string;
  prompt: string;
  choices: BranchMenuChoice[];
  findings: AnalysisFinding[];
}

export interface BranchEndingRow {
  id: string;
  name: string;
  label: string;
  route: string;
  condition: string;
  exists: boolean;
  reachable: boolean;
}

export interface BranchReportOut {
  graph: {
    labels: number;
    edges: number;
    roots: string[];
    edgeKinds: Record<string, number>;
  };
  coverage: BranchCoverage;
  cycles: BranchCycle[];
  deadBlocks: Array<{ chapterId: string; label: string; type: string; preview: string }>;
  chapterEndWithoutExit: Array<{
    chapterId: string;
    label: string;
    nextChapterId: string;
  }>;
  danglingJumps: Array<{ chapterId: string; label: string; target: string }>;
  duplicateLabels: string[];
  unreachableLabels: string[];
  conditions: Array<{
    chapterId: string;
    where: string;
    text: string;
    detail: string;
    branchIndex: number;
    satisfiable: boolean;
    unknown: boolean;
    reason: string;
    error?: string | null;
  }>;
  variables: Record<
    string,
    { type: string; values: string[]; unbounded?: boolean; declared?: boolean }
  >;
  menus: BranchMenu[];
  endings: {
    declared: BranchEndingRow[];
    declaredCount: number;
    reachableDeclared: number;
    undeclaredTerminals: string[];
    findings: AnalysisFinding[];
  };
  findings: AnalysisFinding[];
  counts: AnalysisCounts;
}

/** 分支结构体检：真实 label 图 / 环检测 / 分支覆盖 / 条件可满足性 / 结局对账（纯本地）。 */
export function fetchBranchReport(id: string): Promise<BranchReportOut> {
  return apiFetch<BranchReportOut>(`/projects/${id}/analysis/branch-report`, {
    skipAuthRedirect: true,
  });
}

export interface VoiceDriftLine {
  text: string;
  drift: number;
  reason: string;
}

/** 某角色在某一章的声线比对结果（参照画像是**其它章节**，被评的这章不参与建模）。 */
export interface VoiceChapterDrift {
  characterId: string;
  displayName: string;
  chapterId: string;
  ready: boolean;
  utteranceCount: number;
  drift: number;
  /** ok = 像本人；watch = 值得看一眼；drift = 明显跑味 */
  level: string;
  watchThreshold: number;
  driftThreshold: number;
  reasons: string[];
  signatureHits: string[];
  missingSignatures: string[];
  flaggedLines: VoiceDriftLine[];
}

export interface VoiceSignaturePhrase {
  phrase: string;
  count: number;
  sharePerMille: number;
  distinctiveness: number;
  othersSharePerMille: number;
}

export interface VoiceCharacterReport {
  characterId: string;
  displayName: string;
  ready: boolean;
  utteranceCount: number;
  /** 未评估时后端给的原因（台词不足 / 本章无台词） */
  reason?: string;
  chaptersSpoken?: number;
  /** calibrated = false 表示台词太少，没法用留一法自校准，阈值退回默认常数 */
  calibration?: {
    calibrated: boolean;
    samples: number;
    p50?: number;
    p90?: number;
    p975?: number;
    max?: number;
  };
  signaturePhrases?: VoiceSignaturePhrase[];
  averageFeatures?: Record<string, number>;
  /** 只列漂移最明显的前几章 */
  chapters?: VoiceChapterDrift[];
  driftChapters?: string[];
}

export interface VoicePair {
  a: string;
  b: string;
  aId: string;
  bId: string;
  /** 0–1，越小越"一个味"（后端 < 0.15 判为可混淆） */
  distance: number;
}

export interface VoiceReportOut {
  characters: VoiceCharacterReport[];
  closestPairs: VoicePair[];
  confusablePairs: VoicePair[];
  notes: string[];
}

/** 角色声线体检：逐角色语言画像 + 逐章声线漂移 + 角色间可混淆度（纯本地）。 */
export function fetchVoiceReport(id: string): Promise<VoiceReportOut> {
  return apiFetch<VoiceReportOut>(`/projects/${id}/analysis/voice-report`, {
    skipAuthRedirect: true,
  });
}

export interface ContinuityReportOut {
  findings: AnalysisFinding[];
  counts: AnalysisCounts;
  summary: {
    chapters: number;
    characters: number;
    locations: number;
    dialogueLines: number;
    sceneImages: number;
    timelineEvents: number;
    characterLinks: number;
    locationLinks: number;
    /** 每个检查器查了多少条、报了几条 */
    checks: Record<string, { checked: number; issues: number }>;
    /** 查不了的地方（如实报未知，而不是当成通过） */
    unknown: Record<string, number>;
  };
}

/** 跨章事实一致性体检：未登记说话人 / 悬空关系边 / 重名 / 时间线错序 / 死亡后仍出场（纯本地）。 */
export function fetchContinuityReport(id: string): Promise<ContinuityReportOut> {
  return apiFetch<ContinuityReportOut>(`/projects/${id}/analysis/continuity`, {
    skipAuthRedirect: true,
  });
}

export interface ConsistencyScanCoverage {
  chaptersTotal: number;
  /** 有正文（可送审）的章节数 */
  chaptersWithText: number;
  chaptersScanned: number;
  coverageRatio: number;
  windowsPlanned: number;
  windowsRun: number;
  windowsFailed: number;
  /** 没有被任何成功窗口覆盖的章节：预算砍掉的、窗口失败的、以及整体没跑的 */
  truncatedChapters: string[];
  maxWindowsHit: boolean;
  /** 正文超过单章上限、截断后送审的章节 */
  textTruncatedChapters: string[];
  chaptersWithBlocksButNoText: number;
}

export interface ConsistencyScanIssue {
  category: string;
  /** high / medium / low */
  severity: string;
  chapterIds: string[];
  quote: string;
  description: string;
  suggestion: string;
  /** 被几个窗口独立报出 */
  foundInWindows: number;
  /** high = 跨窗复发（多组章节对照下都成立） */
  confidence: string;
  windowIndexes: number[];
}

export interface ConsistencyScanWindow {
  index: number;
  chapterIds: string[];
  reported: boolean;
  issueCount: number;
  rawIssueCount: number;
  summary: string;
  error: string | null;
}

export interface ConsistencyScanOut {
  issues: ConsistencyScanIssue[];
  summary: string;
  model: string;
  /** 整体失败（如未配 key / 全部窗口失败）时的说明，null = 没有整体错误 */
  error: string | null;
  coverage: ConsistencyScanCoverage;
  /** 后端写给作者的一句话：这次扫了多少章 / 共多少章、哪里被截断 */
  ceilingNote: string;
  windowErrors: Array<{ index: number; chapterIds: string[]; error: string }>;
  windows: ConsistencyScanWindow[];
  issuesTruncated: number;
  issuesDroppedByWindowCap: number;
}

export type ConsistencyScanOpts = {
  /** 每个窗口覆盖几章（后端夹在 1–20，默认 6） */
  size?: number;
  /** 相邻窗口重叠几章（后端夹在 0–19，默认 2） */
  overlap?: number;
  /** 聚焦某类问题，如「角色年龄」「时间线」 */
  focus?: string;
  /** 显式预算上限：不传 = 不限；被用上时后端会如实报未扫章节 */
  maxWindows?: number;
};

/**
 * 全书分片一致性扫描 —— **会调用模型、有成本**。
 *
 * 与旧的 `consistencyAudit` 的区别：按重叠窗口扫完所有有正文的章节，并如实报回
 * 覆盖率（`coverage` / `ceilingNote`），修掉了旧实现"只扫前 14 章且不告知"的静默截断。
 */
/** 分片扫描的默认窗口参数（必须与后端路由默认值一致，见下方守卫测试）。 */
export const CONSISTENCY_SCAN_DEFAULTS = { size: 12, overlap: 4 } as const;

/**
 * 全书一致性分片扫描。
 *
 * **默认 12/4 是测出来的**（依据 Distance between Relevant Information Pieces,
 * ACL 2025 Findings；测量代码 `backend/app/core/scan_exposure.py`）：
 * 同窗距离上限恒等于 overlap，overlap=2 时"隔 3 章的线索"约 24% 的章对永远不可能同窗；
 * 而窗口预算（16）在长书上必被用满，所以窗口大小才是"能扫多少章"的杠杆
 * （6/2 → 66 章；12/4 → 132 章，且距离上限从 2 提到 4）。
 *
 * 与旧的 `consistencyAudit` 的区别：按重叠窗口扫完所有有正文的章节，并如实报回
 * 覆盖率（`coverage` / `ceilingNote`），修掉了旧实现"只扫前 14 章且不告知"的静默截断。
 */
export function consistencyScan(
  id: string,
  opts: ConsistencyScanOpts = {}
): Promise<ConsistencyScanOut> {
  const params = new URLSearchParams();
  params.set("size", String(opts.size ?? CONSISTENCY_SCAN_DEFAULTS.size));
  params.set("overlap", String(opts.overlap ?? CONSISTENCY_SCAN_DEFAULTS.overlap));
  if (opts.focus && opts.focus.trim()) params.set("focus", opts.focus.trim());
  if (opts.maxWindows != null) params.set("max_windows", String(opts.maxWindows));
  return apiFetch<ConsistencyScanOut>(
    `/projects/${id}/analysis/consistency-scan?${params.toString()}`,
    { method: "POST", timeoutMs: TIMEOUTS.long }
  );
}

/** Full Ren'Py project skeleton (script/options/gui/README) as a zip blob. */
export async function exportRenpyBundle(id: string): Promise<Blob> {
  const res = await authedRawFetch(`/projects/${id}/export/bundle`);
  return res.blob();
}

export type MapExtractProposal = {
  locations: Location[];
  locationLinks: LocationLink[];
  newPlaceIds: string[];
  newLinkIds: string[];
};

export type MapExtractPreviewResult = {
  project: VnProject;
  proposal: MapExtractProposal;
  addedCount: number;
  linkCount: number;
  llmAddedCount?: number;
  llmLinkCount?: number;
  mode?: string;
  llmUsed?: boolean;
  warnings?: string[];
};

export function mapExtract(
  id: string,
  opts?: { mode?: "smart" | "rules" }
): Promise<MapExtractPreviewResult> {
  return apiFetch(`/projects/${id}/map/extract`, {
    method: "POST",
    timeoutMs: TIMEOUTS.chat,
    body: JSON.stringify({ mode: opts?.mode ?? "smart" }),
  });
}

export function mapExtractAccept(
  id: string,
  body: {
    placeIds: string[];
    linkIds: string[];
    proposal: MapExtractProposal;
  }
): Promise<{
  project: VnProject;
  addedCount: number;
  linkCount: number;
}> {
  return apiFetch(`/projects/${id}/map/extract/accept`, {
    method: "POST",
    timeoutMs: TIMEOUTS.upload,
    body: JSON.stringify(body),
  });
}

export interface SnapshotSummary {
  id: string;
  label: string;
  createdAt: string;
}

export function listSnapshots(id: string): Promise<SnapshotSummary[]> {
  return apiFetch(`/projects/${id}/snapshots`);
}

export function createSnapshot(id: string, label: string): Promise<SnapshotSummary> {
  return apiFetch(`/projects/${id}/snapshots`, {
    method: "POST",
    timeoutMs: TIMEOUTS.upload,
    body: JSON.stringify({ label }),
  });
}

export function restoreSnapshot(id: string, snapshotId: string): Promise<VnProject> {
  return apiFetch(`/projects/${id}/snapshots/${snapshotId}/restore`, {
    method: "POST",
    timeoutMs: TIMEOUTS.upload,
  });
}

export function deleteSnapshot(
  id: string,
  snapshotId: string
): Promise<{ ok: boolean }> {
  return apiFetch(`/projects/${id}/snapshots/${snapshotId}`, {
    method: "DELETE",
  });
}

interface SnapshotChapterDiff {
  chapterId: string;
  title: string;
  status: "added" | "removed" | "changed" | "same";
  wordsFrom: number;
  wordsTo: number;
  linesFrom: number;
  linesTo: number;
}

interface SnapshotCharacterDiff {
  id: string;
  name: string;
  status: "added" | "removed" | "same";
}

export interface SnapshotDiffResult {
  summary: string;
  chapters: SnapshotChapterDiff[];
  characters: SnapshotCharacterDiff[];
  locations: { added: number; removed: number; changed: number };
  timeline: { added: number; removed: number; changed: number };
  changedChapters: number;
  fromHash: string;
  toHash: string;
}

export function compareSnapshot(
  id: string,
  fromSnapId: string,
  toSnapId?: string
): Promise<SnapshotDiffResult> {
  return apiFetch(`/projects/${id}/snapshots/compare`, {
    method: "POST",
    timeoutMs: TIMEOUTS.upload,
    body: JSON.stringify(
      toSnapId ? { from_snap_id: fromSnapId, to_snap_id: toSnapId } : { from_snap_id: fromSnapId }
    ),
  });
}

export interface AgentRunInBody {
  messages: AgentChatMessage[];
  chapter_id?: string;
  selection?: string;
  task?: AgentTaskKind;
  chat_memory?: string;
  conversation_id?: string;
  apply_actions?: boolean;
  lens_ids?: string[];
  lens_intent?: string;
  attachments?: AgentAttachment[];
  /** 断点续跑：从该会话 run_state 检查点继续上次中断/失败的多步运行 */
  resume?: boolean;
  /** 作者按需摘掉的资料块 key（见 lib/agentSections.AGENT_SECTIONS） */
  exclude_sections?: string[];
}

export type AgentAttachment = {
  id?: string | null;
  filename: string;
  text: string;
  chars?: number;
  warning?: string | null;
};

/** 动笔前问几句：给一个写作目标，拿回 2~3 个该先定下来的问题（可跳过）。 */
export type PreQuestionsResult = {
  questions: string[];
  /** llm = 模型按你的设定生成的；template = 模型不可用时的模板问题 */
  source: "llm" | "template";
};

export function fetchPreQuestions(
  projectId: string,
  body: { goal?: string; chapter_id?: string | null }
): Promise<PreQuestionsResult> {
  return apiFetch(`/projects/${projectId}/agent/pre-questions`, {
    method: "POST",
    timeoutMs: TIMEOUTS.quick,
    body: JSON.stringify(body),
  });
}

export function uploadAgentAttachment(
  projectId: string,
  file: File,
  persist = true
): Promise<AgentAttachment> {
  const form = new FormData();
  form.append("file", file);
  form.append("persist", persist ? "true" : "false");
  return apiFetch(`/projects/${projectId}/agent/attachments`, {
    method: "POST",
    timeoutMs: TIMEOUTS.upload,
    body: form,
  });
}

export function ingestAttachmentSettings(
  projectId: string,
  body: {
    attachments: AgentAttachment[];
    note?: string;
    conversation_id?: string;
  }
): Promise<{
  message: string;
  actions: AgentAction[];
  applied: string[];
  skipped: string[];
  project: VnProject;
  wrote: boolean;
}> {
  return apiFetch(`/projects/${projectId}/agent/ingest-settings`, {
    method: "POST",
    timeoutMs: TIMEOUTS.chat,
    body: JSON.stringify({
      attachments: body.attachments.map((a) => ({
        filename: a.filename,
        text: a.text,
        id: a.id,
      })),
      note: body.note,
      conversation_id: body.conversation_id,
    }),
  });
}

export function chapterRevise(
  projectId: string,
  body: {
    chapter_id?: string;
    note?: string;
    conversation_id?: string;
    attachments?: AgentAttachment[];
    mode?: "cut_lecture" | "human_warmth" | "light_touch";
    preferences?: {
      lockedNames?: string[];
      preferKeepOriginal?: boolean;
      notes?: string[];
      mode?: string;
    };
    async_mode?: boolean;
  }
): Promise<
  | {
      message: string;
      diagnosis: Record<string, unknown>;
      diagnosisMd: string;
      revisedText: string;
      sourceText?: string;
      chapterId: string | null;
      chapterTitle: string;
      sourceChars: number;
      warnings: string[];
      model?: string;
      criticNote?: string;
      lintIssues?: unknown[];
      llmCalls?: unknown[];
      elapsedMs?: number;
      wrote?: boolean;
      debugTrace?: unknown[];
    }
  | { jobId: string; async: true; status: string }
> {
  return apiFetch(`/projects/${projectId}/agent/chapter-revise`, {
    method: "POST",
    timeoutMs: TIMEOUTS.batch,
    body: JSON.stringify({
      ...body,
      attachments: body.attachments?.map((a) => ({
        filename: a.filename,
        text: a.text,
        id: a.id,
      })),
    }),
  });
}

export function chapterReviseApply(
  projectId: string,
  body: {
    chapter_id?: string;
    text: string;
    conversation_id?: string;
  }
): Promise<{
  message: string;
  applied: string[];
  skipped: string[];
  project: VnProject;
  wrote: boolean;
}> {
  return apiFetch(`/projects/${projectId}/agent/chapter-revise/apply`, {
    method: "POST",
    timeoutMs: TIMEOUTS.upload,
    body: JSON.stringify(body),
  });
}

export interface AgentRunOut {
  message: string;
  actions: AgentAction[];
  model: string;
  context_meta?: AgentContextMeta | null;
  project?: VnProject | null;
  applied: boolean;
  warnings: string[];
  conversation_id?: string | null;
  inbox_added?: number;
  trace?: import("../types/vn").AgentTraceEvent[];
}

// ---------------------------------------------------------------------------
// Agent streaming (SSE)
// ---------------------------------------------------------------------------

export type AgentStreamEvent =
  | { type: "task"; task?: string; craftMode?: string }
  | { type: "thought"; text?: string }
  | { type: "tool_call"; id?: string; name?: string; arguments?: unknown }
  | { type: "tool_result"; id?: string; name?: string; ok?: boolean; preview?: string }
  | { type: "actions"; actions?: AgentAction[]; skipped?: string[] }
  | { type: "review"; note?: string }
  | { type: "memory"; note?: string }
  | { type: "error"; message?: string }
  | { type: "done"; result?: AgentRunOut }
  | { type: "final"; result?: AgentRunOut };

/**
 * Streaming agent run. Resolves with the same AgentRunOut as runAgent();
 * `onEvent` receives each SSE event as it arrives (task / thought / tool / …).
 * Pass `signal` to cancel the stream (e.g. on component unmount); the fetch
 * and the read loop both observe it.
 *
 * `onActivity` fires on **every** received chunk, including the server's
 * `: keepalive` comments. Keep-alives carry no business event, but they prove
 * the connection is alive — a watchdog that only counts `data:` lines will kill
 * a slow (thinking) model mid-run and blame the user's model config.
 */
export async function runAgentStream(
  id: string,
  body: AgentRunInBody,
  onEvent: (evt: AgentStreamEvent) => void,
  signal?: AbortSignal,
  onActivity?: () => void
): Promise<AgentRunOut> {
  const res = await fetch(`${API_BASE}/projects/${id}/agent/stream`, {
    method: "POST",
    headers: buildApiHeaders(undefined, true),
    body: JSON.stringify(body),
    signal,
  });
  if (!res.ok || !res.body) {
    const payload = await readErrorPayload(res).catch(() => ({
      message: `HTTP ${res.status}`,
      detail: undefined as unknown,
    }));
    throw new ApiError(res.status, payload.message, payload.detail);
  }
  const reader = res.body.getReader();
  const decoder = new TextDecoder();
  let buffer = "";
  let finalResult: AgentRunOut | null = null;
  for (;;) {
    if (signal?.aborted) {
      reader.cancel().catch(() => undefined);
      throw new ApiError(499, "请求已取消");
    }
    const { done, value } = await reader.read();
    // 心跳也算"活着"：`: keepalive` 不含 data: 行，但它证明连接没断。
    if (value && value.byteLength > 0) onActivity?.();
    buffer += decoder.decode(value ?? new Uint8Array(), { stream: !done });
    let idx: number;
    while ((idx = buffer.indexOf("\n\n")) >= 0) {
      const chunk = buffer.slice(0, idx);
      buffer = buffer.slice(idx + 2);
      const line = chunk.split("\n").find((l) => l.startsWith("data:"));
      if (!line) continue;
      const payload = line.slice(5).trim();
      if (!payload) continue;
      let evt: AgentStreamEvent;
      try {
        evt = JSON.parse(payload) as AgentStreamEvent;
      } catch {
        continue;
      }
      onEvent(evt);
      if (evt.type === "final" && evt.result) finalResult = evt.result;
      if (evt.type === "error") {
        throw new ApiError(500, evt.message || "Agent 流式请求失败");
      }
    }
    if (done) break;
  }
  if (!finalResult) throw new ApiError(500, "Agent 流式响应缺少最终结果");
  return finalResult;
}

export interface AgentConversationSummary {
  id: string;
  title: string;
  message_count: number;
  created_at: string;
  updated_at: string;
}

export interface AgentConversationOut {
  id: string;
  title: string;
  messages: AgentChatMessage[];
  chat_memory: string;
  undo_stack: unknown[];
  /** 运行检查点摘要：status interrupted/error 时前端显示"继续上次运行" */
  run_state?: {
    status?: string;
    step?: number;
    steps?: number;
    updatedAt?: string;
  } | null;
  created_at: string;
  updated_at: string;
}

export function listAgentConversations(
  projectId: string
): Promise<AgentConversationSummary[]> {
  return apiFetch(`/projects/${projectId}/agent/conversations`);
}

export function createAgentConversation(
  projectId: string,
  title?: string
): Promise<AgentConversationOut> {
  return apiFetch(`/projects/${projectId}/agent/conversations`, {
    method: "POST",
    timeoutMs: TIMEOUTS.upload,
    body: JSON.stringify({
      title: title?.trim() || undefined,
    }),
  });
}

export function getAgentConversation(
  projectId: string,
  conversationId: string
): Promise<AgentConversationOut> {
  return apiFetch(`/projects/${projectId}/agent/conversations/${conversationId}`);
}

export function putAgentConversation(
  projectId: string,
  conversationId: string,
  body: {
    title?: string;
    messages?: AgentChatMessage[];
    chat_memory?: string;
    undo_stack?: unknown[];
  }
): Promise<AgentConversationOut> {
  return apiFetch(`/projects/${projectId}/agent/conversations/${conversationId}`, {
    method: "PUT",
    body: JSON.stringify(body),
  });
}

export function renameAgentConversation(
  projectId: string,
  conversationId: string,
  title: string
): Promise<AgentConversationOut> {
  return apiFetch(`/projects/${projectId}/agent/conversations/${conversationId}`, {
    method: "PATCH",
    body: JSON.stringify({ title }),
  });
}

export function deleteAgentConversation(
  projectId: string,
  conversationId: string
): Promise<{ ok: boolean }> {
  return apiFetch(`/projects/${projectId}/agent/conversations/${conversationId}`, {
    method: "DELETE",
  });
}

export function voiceCheck(
  id: string,
  body: { chapter_id?: string; draft?: string }
): Promise<VoiceReport> {
  return apiFetch(`/projects/${id}/voice-check`, {
    method: "POST",
    timeoutMs: TIMEOUTS.chat,
    body: JSON.stringify(body),
  });
}

interface ConsistencyIssue {
  category: "character" | "timeline" | "location" | "bible" | "plot" | "style";
  severity: "high" | "medium" | "low";
  chapterIds: string[];
  quote: string;
  description: string;
  suggestion: string;
}

export interface ConsistencyAuditResult {
  issues: ConsistencyIssue[];
  summary: string;
  scanned_chapters: number;
  model: string;
  error?: string;
}

export function consistencyAudit(
  id: string,
  body?: { focus?: string; chapter_id?: string }
): Promise<ConsistencyAuditResult> {
  return apiFetch(`/projects/${id}/consistency/audit`, {
    method: "POST",
    timeoutMs: TIMEOUTS.write,
    body: JSON.stringify(body ?? {}),
  });
}

export interface StyleMemoryOut {
  project: import("../types/vn").VnProject;
  guide: string;
  samples: string[];
  model?: string;
}

export function learnStyleMemory(id: string): Promise<StyleMemoryOut> {
  return apiFetch(`/projects/${id}/style-memory/learn`, {
    method: "POST",
    timeoutMs: TIMEOUTS.write,
  });
}

export function clearStyleMemory(
  id: string
): Promise<{ project: import("../types/vn").VnProject }> {
  return apiFetch(`/projects/${id}/style-memory`, {
    method: "DELETE",
  });
}

export type FactsChanged = {
  chapters: string[];
  bible: boolean;
  characters: string[];
  isFirstScan: boolean;
};

export function factsReconcile(id: string): Promise<{
  project: import("../types/vn").VnProject;
  changed: FactsChanged;
  staleCount: number;
  wrote?: boolean;
}> {
  return apiFetch(`/projects/${id}/analysis/facts/reconcile`, {
    method: "POST",
    timeoutMs: TIMEOUTS.chat,
    body: JSON.stringify({}),
  });
}

export function factsScan(
  id: string,
  body?: {
    chapter_id?: string;
    paste_text?: string;
    full?: boolean;
    persist_paste?: boolean;
  }
): Promise<{
  project: import("../types/vn").VnProject;
  changed: FactsChanged;
  summary: {
    added: number;
    characterLinks: number;
    timelineEvents: number;
  };
  inbox: import("../types/vn").FactInboxItem[];
}> {
  return apiFetch(`/projects/${id}/analysis/facts/scan`, {
    method: "POST",
    timeoutMs: TIMEOUTS.chat,
    body: JSON.stringify(body ?? {}),
  });
}

export function factsInbox(
  id: string
): Promise<{ items: import("../types/vn").FactInboxItem[] }> {
  return apiFetch(`/projects/${id}/analysis/facts/inbox`);
}

export function factsAccept(
  id: string,
  ids: string[]
): Promise<{
  acceptedIds: string[];
  skippedIds?: string[];
  project: import("../types/vn").VnProject;
}> {
  return apiFetch(`/projects/${id}/analysis/facts/accept`, {
    method: "POST",
    timeoutMs: TIMEOUTS.upload,
    body: JSON.stringify({ ids }),
  });
}

export function factsReject(
  id: string,
  ids: string[]
): Promise<{ rejectedIds: string[] }> {
  return apiFetch(`/projects/${id}/analysis/facts/reject`, {
    method: "POST",
    timeoutMs: TIMEOUTS.upload,
    body: JSON.stringify({ ids }),
  });
}

export function factsAckStale(
  id: string,
  body: { linkIds?: string[]; timelineIds?: string[]; all?: boolean }
): Promise<{ project: import("../types/vn").VnProject }> {
  return apiFetch(`/projects/${id}/analysis/facts/ack-stale`, {
    method: "POST",
    timeoutMs: TIMEOUTS.upload,
    body: JSON.stringify(body),
  });
}

/* ------------------------------------------------------------ 读者行为遥测
 * 路由见 backend/app/api/v1/playtest.py，字段白名单与分析形状见
 * backend/app/services/playtest_telemetry.py。类型与字段名是照着后端源码抄的，
 * 三条硬约束：
 * 1. 上报体的键是 **snake_case**（`sanitize_run_payload` / `sanitize_choice` 只认
 *    `_RUN_KEYS` / `_CHOICE_KEYS` 里的键），未知键一律丢弃并在 `droppedFields` 里
 *    回显 —— 所以发 camelCase 等于什么都没发。
 * 2. 每个字符串列都要过 `^[A-Za-z_][A-Za-z0-9_.:-]{0,63}$`：中文会被落成空串。
 *    库里没有任何自由文本列，选项文案、台词在物理上没有容器可放（隐私红线）。
 * 3. `client_run_id` 必须是 8~64 位 URL 安全随机串，否则 400；它是幂等键的一半。
 */

/** 一次试玩的标量字段（键名与后端 `_RUN_KEYS` 一致）。 */
export interface PlaytestRunIn {
  client_run_id: string;
  /** ISO 8601（带时区）。后端只接受 2000 年之后、且不晚于"明天"的时间 */
  started_at: string;
  ended_at: string;
  chapter_count: number;
  choice_count: number;
  /** 结局登记里的 label（ASCII 标识符）；不确定就发空串，别编一个 */
  ending_label: string;
}

/**
 * 一次试玩里的一条选择（键名与后端 `_CHOICE_KEYS` 一致）。
 *
 * `condition` **刻意不在**这里：后端白名单没有这个键（条件表达式是正文类字符串，
 * 由静态分析提供），发过去只会被丢弃并计入 `droppedFields`。
 */
export interface PlaytestChoiceIn {
  /** 同一次试玩内唯一、从 0 开始；重复上报时后端只补库里缺失的 seq */
  seq: number;
  chapter_id: string;
  /** 该选项所在 label（找不到就空串） */
  label: string;
  menu_id: string;
  /** 选项在**菜单原始 choices 数组**里的下标（与分支推理的 option index 对齐） */
  choice_index: number;
  /** 选中时它的条件是否成立（键盘数字键能选到被条件隐藏的选项） */
  condition_passed: boolean;
}

export interface PlaytestRecordIn {
  run: PlaytestRunIn;
  choices: PlaytestChoiceIn[];
}

export interface PlaytestRecordOut {
  ok: boolean;
  runId: string;
  /** false = 这次 (project_id, client_run_id) 之前已经落过行，本次只补缺失 seq */
  created: boolean;
  /** 本次真正落库的选择条数 */
  accepted: number;
  duplicates: number;
  /** 因 seq 缺失/越界被整条丢弃的选择数 */
  rejected: number;
  /** 被丢弃的非白名单字段名（含全部被清空成空串之外的未知键） */
  droppedFields: string[];
}

/**
 * 上报一次试玩（幂等：同 `(project_id, client_run_id)` 重复上报只补缺失的 seq）。
 *
 * 未开启采集时后端返回 403 `telemetry_disabled` 且**一行都不落**；
 * 调用方必须把这种 403 判成"工程没开采集"而不是"上报失败"（见 lib/playtestTelemetry.ts）。
 *
 * @param opts.keepalive 页面正在离开时用 `fetch(..., {keepalive:true})` 兜底发完
 *   （`sendBeacon` 带不了 Authorization 头，见 lib/playtestTelemetry.ts 的说明）
 */
export function recordPlaytest(
  id: string,
  body: PlaytestRecordIn,
  opts: { keepalive?: boolean } = {}
): Promise<PlaytestRecordOut> {
  return apiFetch<PlaytestRecordOut>(`/projects/${id}/playtest/record`, {
    method: "POST",
    body: JSON.stringify(body),
    keepalive: Boolean(opts.keepalive),
    // 遥测不值得把作者踢去登录页：401 只静默失败（与 lib/track.ts 同姿态）
    skipAuthRedirect: true,
  });
}

export interface TelemetrySettingsOut {
  projectId: string;
  enabled: boolean;
  /** 后端明示的口径：没有设置行 = 关闭。界面据此说明"默认关" */
  defaultEnabled: boolean;
}

export function fetchTelemetrySettings(id: string): Promise<TelemetrySettingsOut> {
  return apiFetch<TelemetrySettingsOut>(`/projects/${id}/playtest/settings`, {
    skipAuthRedirect: true,
  });
}

/** 写采集开关：需要 owner / editor，viewer 会 403（非成员 404）。 */
export function saveTelemetrySettings(
  id: string,
  enabled: boolean
): Promise<{ projectId: string; enabled: boolean }> {
  return apiFetch(`/projects/${id}/playtest/settings`, {
    method: "PUT",
    body: JSON.stringify({ enabled }),
  });
}

/** 计数类统计（`_stats`）：空输入时后端返回全 0，不返回 null。 */
export interface PlaytestStat {
  count: number;
  sum: number;
  avg: number;
  median: number;
  min: number;
  max: number;
}

export interface PlaytestOptionRow {
  /** 在菜单原始 choices 数组里的下标 —— 就是"第 index+1 个选项" */
  index: number;
  selected: number;
  /** 该菜单本次样本里的占比（0~1） */
  share: number;
  /** true = 这次样本里没有任何人选它 */
  neverSelected: boolean;
  /** false = 静态分析判定条件恒不成立（玩家看不到） */
  available: boolean;
  /** 选项自己的条件表达式（脚本侧文本，不是玩家数据） */
  condition: string;
  /** 选中了它、但条件实际不成立的次数（键盘选择/条件求值差异） */
  conditionBlockedSelections: number;
}

export interface PlaytestMenuRow {
  menuId: string;
  chapterId: string;
  /** 菜单标题（脚本侧的 label / prompt），可能为空 */
  label: string;
  selections: number;
  optionCount: number;
  options: PlaytestOptionRow[];
  neverSelected: number[];
}

export interface PlaytestFunnelChapter {
  index: number;
  chapterId: string;
  /** 到达过这一章的试玩数（含更后面的章，是前缀口径，天然单调不增） */
  reached: number;
  /** 在这一章真的做过选择的试玩数 */
  choosingRuns: number;
  dropFromPrevious: number;
  dropRate: number;
  retention: number;
}

export interface PlaytestEndingRow {
  label: string;
  name: string;
  runs: number;
  share: number;
  /** true = 这个 label 在工程里登记过为结局 */
  declared: boolean;
  declaredReachable: boolean;
  declaredExists: boolean;
  /** true = 静态分析的终点集合里有它（没登记但确实是个终点） */
  isStaticTerminal: boolean;
}

export interface PlaytestAnalyticsOut {
  sample: {
    runs: number;
    choices: number;
    /** 后端建议的样本下限（默认 10 次试玩） */
    minSample: number;
    sufficient: boolean;
    /** true = 试玩次数超过单次分析上限，只取了最近一批 */
    truncated: boolean;
  };
  choices: {
    totalSelections: number;
    menus: PlaytestMenuRow[];
    menuCount: number;
    /** 选择记录里出现、但当前剧本里找不到的 menu_id */
    unknownMenus: Array<{ menuId: string; selections: number }>;
    /** 没有 menu_id 的选择（只参与总数与漏斗） */
    unattributedSelections: number;
    /** 剧本里重复的 menu_id（同名菜单会被合并统计） */
    duplicateMenuIds: string[];
    observedMenuCount: number;
    /** 静态分析说"不可选"、玩家却选了的选项 */
    selectedUnavailableOptions: Array<{
      menuId: string;
      index: number;
      selections: number;
    }>;
  };
  funnel: {
    startedRuns: number;
    chapters: PlaytestFunnelChapter[];
    biggestDrop: PlaytestFunnelChapter | null;
    deepestChapterId: string;
    unknownChapters: Array<{ chapterId: string; selections: number }>;
  };
  endings: {
    reached: PlaytestEndingRow[];
    declaredTotal: number;
    declaredReached: number;
    /** 登记过、但没有任何玩家走到的结局 */
    neverReached: Array<{
      label: string;
      name: string;
      route: string;
      reachableInScript: boolean;
    }>;
    /** 玩家走到了、但没登记为结局的 label */
    undeclared: PlaytestEndingRow[];
    unknownEndingLabels: PlaytestEndingRow[];
    /** 登记了但没有 label 的结局（无法对账） */
    declaredWithoutLabel: Array<{ name: string; route: string }>;
    /** 没走到任何结局就结束的试玩数 */
    unfinishedRuns: number;
  };
  runs: {
    total: number;
    finished: number;
    withEnding: number;
    /** 客户端自报的选择数 */
    choicesReported: PlaytestStat;
    /** 库里真实落下的选择行数（与自报不一致 = 有丢报或幂等合并） */
    choicesObserved: PlaytestStat;
    chaptersPlayed: PlaytestStat;
    /** 没有任何一次试玩同时有 started_at / ended_at 时为 null */
    durationSeconds: PlaytestStat | null;
  };
  /** 读者视角的分支覆盖率：实际被玩家碰过的选项 / 剧本里可选的选项 */
  coverage: {
    availableOptions: number;
    observedOptions: number;
    ratio: number;
    menusTotal: number;
    menusTouched: number;
    menusNeverTouched: string[];
    unmappedSelections: number;
    selectedUnavailableOptions: Array<{
      menuId: string;
      index: number;
      selections: number;
    }>;
  };
  /** 后端写给作者的中文口径说明与样本量提示 */
  notes: string[];
}

/** 读者行为分析（只读；响应里同样不含任何选项文案）。 */
export function fetchPlaytestAnalytics(id: string): Promise<PlaytestAnalyticsOut> {
  return apiFetch<PlaytestAnalyticsOut>(`/projects/${id}/playtest/analytics`, {
    skipAuthRedirect: true,
  });
}

/* ---------------------------------------------------------- 分支改进建议
 * 路由见 backend/app/api/v1/playtest.py（`/playtest/recommendations`），
 * 形状见 backend/app/core/branch_recommendations.py。
 *
 * 与 `/analysis/branch-report`、`/playtest/analytics` 的分工：那两条各给一半**事实**
 * （结构上哪里写坏了 / 读者实际怎么玩），这条把两者融成**该怎么办**——每条建议都带
 * `why`（依据）与 `action`（具体改法）。所以 `action` 是这条链路的核心字段。
 *
 * 两条不可省的语义（界面必须原样转述，见 lib/branchAdvice.ts）：
 * 1. `basis === "script-only"` = 读者数据不足，**依赖读者行为的建议这一轮不会出现**。
 *    这是"还看不出来"，不是"没问题"。
 * 2. `confidence` 区分 `evidence`（有读者数据支撑）与 `static`（纯静态推断）。
 */

/** 建议等级：后端只发 error / warn / info（见 `branch_recommendations._SEVERITY_BASE`）。 */
export type BranchRecommendationSeverity = "error" | "warn" | "info";

/**
 * 判断依据：`script-only` = 只做了静态分析（没有读者数据，或样本低于 `minRuns`）；
 * `script+readers` = 静态分析 + 读者实际行为。
 */
export type BranchRecommendationBasis = "script-only" | "script+readers";

/** 一条改稿建议（`recommendations[]` 的元素）。 */
export interface BranchRecommendation {
  /** 机器码：no_effect_menu / never_selected_option / loop_no_exit … */
  code: string;
  /** 已知 error / warn / info；留 string 是为了后端将来加等级时不静默丢建议 */
  severity: string;
  /** 确定性打分 = 严重度基数 + 经验证据加成（后端已按它降序） */
  priority: number;
  /** static = 只有静态推断；evidence = 有读者数据支撑 */
  confidence: string;
  title: string;
  /** 依据（中文，含具体数字 / 条件） */
  why: string;
  /** **具体怎么改**（中文）—— 这条端点的核心价值，不是「建议优化剧情」这种空话 */
  action: string;
  /** 位置（如 `ch1/m1`、结局 label）；可能为空串（这条建议不属于某一处） */
  where: string;
  /** 结构化证据：不同 code 字段不同，界面只挑要用的读，不整体 dump */
  evidence: Record<string, unknown>;
}

export interface BranchRecommendationCounts {
  error: number;
  warn: number;
  info: number;
  total: number;
  /** 后端按 severity 原样累加：将来加等级时，未知等级也会成为这里的键 */
  [severity: string]: number;
}

export interface BranchRecommendationsOut {
  basis: BranchRecommendationBasis;
  /** 后端写给作者的中文说明：为什么只有静态建议 / 已经用了多少次试玩 */
  sampleNote: string;
  /** 这次生效的经验判断门槛（后端夹在 1–10000，默认 10） */
  minRuns: number;
  /** 已按 priority 降序排好 */
  recommendations: BranchRecommendation[];
  counts: BranchRecommendationCounts;
  summary: {
    /** 纯静态推断的条数 */
    static: number;
    /** 有读者数据支撑的条数 */
    evidence: number;
    /** 优先级最高那条的 code（没有建议时为 null） */
    topCode: string | null;
  };
  /** 剧本侧分支覆盖（与 `/analysis/branch-report` 同一个对象） */
  coverage: BranchCoverage;
  /** 后端的中文口径说明（含「没有建议 ≠ 剧本没问题」那句） */
  notes: string[];
  /**
   * 选项分类（Dunyazad 三分法的**结构代理**）：每个选项算"怎么选都一样 / 意图明确 / 两难"。
   * 判据见 `backend/app/core/choice_poetics.py`——只看选项把玩家送去哪、改了哪些状态，
   * 不判断玩家心理。缺某一类只报 info（日常系作品的轻松选择是有意为之）。
   */
  choiceVariety?: ChoiceVariety;
}

/** 一个菜单的选项分类结果 */
export interface ChoiceVarietyMenu {
  /** `章节id/menuId` */
  where: string;
  prompt: string;
  /** `all_relaxed`（怎么选都一样）| `has_dilemma`（有取舍）| `no_dilemma` | `empty` */
  verdict: string;
  counts: Record<string, number>;
  choices: Array<{
    index: number;
    text: string;
    klass: string;
    reason: string;
    target: string | null;
    varsModified: string[];
  }>;
}

export interface ChoiceVariety {
  menus: ChoiceVarietyMenu[];
  /** relaxed / obvious / dilemma 的条数，外加 `menus` 总数 */
  counts: Record<string, number>;
  /** 类名 → 给作者看的中文解释 */
  classLabels: Record<string, string>;
  /** 「怎么选都一样」的菜单（`章节id/menuId`） */
  allRelaxedMenus: string[];
  notes: string[];
}

export type BranchRecommendationsOpts = {
  /** 经验判断门槛：低于它只出静态建议（后端默认 10） */
  minRuns?: number;
  /** false = 不读读者数据，强制只看静态 */
  includeReaders?: boolean;
};

/** 改稿建议（只读；不调模型，只用已落库的读者数据）。 */
export function fetchBranchRecommendations(
  id: string,
  opts: BranchRecommendationsOpts = {}
): Promise<BranchRecommendationsOut> {
  const params = new URLSearchParams();
  params.set("min_runs", String(opts.minRuns ?? 10));
  params.set("include_readers", opts.includeReaders === false ? "false" : "true");
  return apiFetch<BranchRecommendationsOut>(
    `/projects/${id}/playtest/recommendations?${params.toString()}`,
    { skipAuthRedirect: true }
  );
}

/* ------------------------------------------------------------------ 故事层指标
 * 路由见 backend/app/api/v1/projects.py（`/analysis/story-metrics`），
 * 形状见 backend/app/core/story_metrics.py。字段名是照源码抄的，两条硬口径：
 * 1. `foreshadow.resolutionRate` 可能是 **null**（分母为 0）—— "没有伏笔" ≠ "回收率 0%"
 *    （后端就是为此返回 None 的），界面必须分开说（见 lib/storyReport.ts）。
 * 2. 情绪是**台词关键词推断**，不是语义判断：反讽/压抑会读错，所以每条结论
 *    都带证据句（`emotionArcBreaks.rows[].evidence`），让作者自己判断。
 */

/** 一条未回收的钩子（后端已按章龄降序）。 */
export interface StoryOpenHook {
  hook: string;
  /** 埋点章节 id */
  plantedChapter: string;
  /** 埋点章节标题（可能为空） */
  plantedChapterTitle: string;
  /** 从埋点章算起挂了多久（章数，账本的 ageChapters） */
  chaptersOpen: number;
}

export interface StoryForeshadow {
  total: number;
  paid: number;
  open: number;
  /** **null = 这个作品还没有记录任何伏笔**，不是 0% */
  resolutionRate: number | null;
  chapters: number;
  oldestOpenChapters: number;
  openHooks: StoryOpenHook[];
  note: string;
}

/** 逐角色的情感弧线（开头情绪 → 结尾情绪 + 刻度差）。 */
export interface StoryEmotionArc {
  character: string;
  start: string;
  end: string;
  delta: number;
}

export interface StoryEmotionArcs {
  characters: StoryEmotionArc[];
  /** 全篇情绪没动过的角色（|delta| 小于后端阈值） */
  flatArcs: StoryEmotionArc[];
  note: string;
}

/** 逐（角色 × 章）的情绪走向；每章至少 2 句台词才评估。 */
export interface StoryEmotionChapterRow {
  characterId: string;
  character: string;
  chapterId: string;
  chapterTitle: string;
  /** 在全书里的顺序；-1 = 章节已不在工程里 */
  chapterIndex: number;
  start: string;
  end: string;
  delta: number;
  lines: number;
  /** 证据原句（开头那句 / 结尾那句） */
  evidence: string[];
}

/** 局部走向与全篇相反的那一章（带 chapterId → 界面上必须指得出是哪一章）。 */
export interface StoryEmotionArcBreak {
  character: string;
  chapterId: string;
  chapterTitle: string;
  /** emotion_arc_break */
  issue: string;
  overallDelta: number;
  chapterDelta: number;
  /** 这一章实际的情绪走向："平静 → 低落" */
  actual: string;
  message: string;
}

export interface StoryEmotionArcBreaks {
  rows: StoryEmotionChapterRow[];
  breaks: StoryEmotionArcBreak[];
}

/** 与节拍表**声明**的弧线对账：arc_flat = 声明有变化、实际没变；arc_reversed = 方向相反。 */
export interface StoryDeclaredArcMismatch {
  character: string;
  /** arc_flat | arc_reversed */
  issue: string;
  /** 节拍表声明的走向："平静 → 激动" */
  declared: string;
  /** 台词推断出来的走向 */
  actual: string;
  message: string;
}

export interface StoryMetricsOut {
  foreshadow: StoryForeshadow;
  emotionArcs: StoryEmotionArcs;
  emotionArcBreaks: StoryEmotionArcBreaks;
  declaredArcMismatches: StoryDeclaredArcMismatch[];
  findings: AnalysisFinding[];
  counts: AnalysisCounts;
}

/**
 * 故事层体检：伏笔回收率 + 情感弧线（逐角色 / 逐章 / 与节拍表声明对账）。
 *
 * **纯本地计算，不调模型**；情绪那部分靠台词关键词推断，结论一律带证据句。
 */
export function fetchStoryMetrics(id: string): Promise<StoryMetricsOut> {
  return apiFetch<StoryMetricsOut>(`/projects/${id}/analysis/story-metrics`, {
    skipAuthRedirect: true,
  });
}

/* ------------------------------------------------------------ 自适应选项方案
 * 路由见 backend/app/api/v1/projects.py（`/analysis/adaptive-plan`），
 * 形状见 backend/app/core/adaptive_reader.py。三条必须原样转述给作者的语义：
 * 1. 计数器存在 `persistent` 里（**跨存档**），描述的是"这个读者一贯怎么选"。
 * 2. `recipes[].condition` 是可以直接照抄进选项条件的表达式。
 * 3. **导出默认不注入计数语句**，只有 `adaptive_reader=True` 才写进 .rpy ——
 *    否则作者会以为"导出就有了"（见 lib/storyReport.ADAPTIVE_EXPORT_NOTE）。
 */

/** 一条自适应条件示例。 */
export interface AdaptiveRecipe {
  /** 正文里被改过的变量 key（如 affection） */
  variableKey: string;
  /** Ren'Py 里的计数器引用（含 `persistent.` 前缀） */
  counter: string;
  /** 可直接照抄的选项条件 */
  condition: string;
  meaning: string;
}

/** 一个值得做成自适应的菜单。 */
export interface AdaptiveCandidate {
  menuId: string;
  chapterId: string;
  optionCount: number;
  /** 为什么值得做：所有选项后果相同 / 读者几乎总选同一个 */
  reason: string;
  suggestion: string;
}

export interface AdaptivePlanOut {
  /** 变量 key → persistent 计数器名（**不含** `persistent.` 前缀） */
  tendencyCounters: Record<string, string>;
  /** 条件示例里用的门槛（后端固定 3） */
  recipeThreshold: number;
  recipes: AdaptiveRecipe[];
  candidates: AdaptiveCandidate[];
  /** 要写进 .rpy 开头的 default 声明块；**可能为空串**（没有任何会改变量的选项） */
  prelude: string;
  notes: string[];
}

/** 自适应选项方案（只读；纯本地计算，不调模型）。 */
export function fetchAdaptivePlan(id: string): Promise<AdaptivePlanOut> {
  return apiFetch<AdaptivePlanOut>(`/projects/${id}/analysis/adaptive-plan`, {
    skipAuthRedirect: true,
  });
}

// ---- 稿件体检（离线统计，不调用模型） ----------------------------------------

export type AuditSeverity = "error" | "warn" | "info";

/** 表记 / 视角 / 称呼类线索：每条都带"第几章第几行 + 原样片段" */
export type NovelAuditIssue = {
  severity: AuditSeverity;
  code: string;
  category: string;
  message: string;
  /** 这条规则的依据（国标 / 行业标准 / 作品自身一致性）——界面上要能显示"凭什么" */
  basis?: string;
  chapterId: string;
  chapterTitle: string;
  chapterOrdinal: number;
  /** 正文行号；按章级判定（如引号配对）时为 null */
  line: number | null;
  quote: string;
};

/** 注音写法问题（`｜汉字《注音》` / `{汉字|注音}` 写坏了） */
export type NovelAuditRubyIssue = {
  code: string;
  severity: AuditSeverity;
  chapterId: string;
  chapterTitle: string;
  line: number | null;
  column: number | null;
  snippet: string;
  message: string;
};

export type NovelAuditCoverage = {
  chaptersTotal: number;
  chaptersScanned: number;
  chaptersWithText: number;
  coverageRatio: number;
  chaptersWithoutText: string[];
  textTruncatedChapters: string[];
  unscannedChapters: string[];
  issuesFound: number;
  issuesReported: number;
  issuesTruncated: number;
  truncated: boolean;
};

export type NovelAuditConsistency = {
  issues: NovelAuditIssue[];
  counts: {
    total: number;
    bySeverity: Record<string, number>;
    byCode: Record<string, number>;
    byCategory: Record<string, number>;
  };
  summary: string;
  coverage: NovelAuditCoverage;
  notes: string[];
  pov: {
    dominant: string;
    dominantLabel: string;
    bookFirstPerson: number;
    bookThirdPerson: number;
    chapters: Array<Record<string, unknown>>;
    heuristic: boolean;
  };
  address: { pairs: Array<Record<string, unknown>>; heuristic: boolean };
};

export type NovelAuditChapter = {
  chapterId: string;
  chapterTitle: string;
  /** 全书序号（0 起算） */
  chapterIndex: number;
  volumeId: string;
  /** prose = 数的是正文；blocks = 数的是脚本块 */
  source: string;
  truncated: boolean;
  words: { total: number; dialogue: number; narration: number; choice: number; chars: number };
  ratio: { dialogue: number | null; narration: number | null };
  lines: { dialogue: number; narration: number; choice: number };
  paragraphs: { count: number; avgChars: number; longCount: number; longRatio: number };
  /** 句长读数（文体剖面）：没有正文时各分位是 null，不是 0 */
  sentence?: {
    count: number;
    p50: number | null;
    p90: number | null;
    shortRatio: number | null;
    longRatio: number | null;
    shortThreshold: number;
    longThreshold: number;
  };
  /** 地の文的人称倾向（对白不计）；没有人称标记时 firstRatio 为 null */
  person?: { first: number; third: number; firstRatio: number | null; checked: boolean };
  punctuation: Record<string, number>;
  onomatopoeia: { count: number; strictCount: number; per1000Chars: number };
  ruby: { count: number; per1000Chars: number };
  hook: { score: number; level: string };
  relativeHints?: string[];
};

export type NovelAuditCraft = {
  perChapter: NovelAuditChapter[];
  summary: string;
  /**
   * 文体剖面：**描述性读数**（对白驱动程度/句长/人称/拟声/注音/连载节奏），每条带依据。
   *
   * 依据是《轻浅的美学》（轻小说文体特征）、《ライトノベル表現論》（会话中心）、
   * 《日本轻小说模式的演变及特征》（连载节奏）。**读数不是评分**，不产出建议。
   */
  styleProfile?: {
    summary: {
      avgChapterWords: number | null;
      hookMedian: number | null;
      onomatopoeiaPer1000: number | null;
      rubyPer1000: number | null;
    };
    readings: Array<{ kind: string; label: string; value: string; basis: string }>;
    basis: Record<string, string>;
    note: string;
  };
  rubyIssues: NovelAuditRubyIssue[];
  hookScores: Array<{
    chapterId: string;
    chapterTitle: string;
    score: number;
    level: string;
    heuristic: boolean;
    endingKind: string;
    endingTail: string;
    chapterIndex: number;
  }>;
  notes: string[];
  coverage: {
    chaptersTotal: number;
    chaptersAnalyzed: number;
    chaptersSkipped: string[];
    truncated: boolean;
    emptyChapters: string[];
    wordsScanned: number;
    note: string;
  };
};

export type NovelAuditOut = {
  parts: string[];
  consistency?: NovelAuditConsistency;
  craft?: NovelAuditCraft;
};

/**
 * 稿件体检（**不调用模型**，纯文本统计）。
 *
 * 为什么不放进"一致性审计"：这条路径不烧 token、不占模型并发闸，几十毫秒就回来，
 * 所以可以每改完一章顺手跑一次；带模型的一致性扫描语义层更贵，两者互补。
 */
export function fetchNovelAudit(
  id: string,
  opts: { parts?: string; focus?: string; chapterId?: string } = {}
): Promise<NovelAuditOut> {
  const params = new URLSearchParams();
  if (opts.parts) params.set("parts", opts.parts);
  if (opts.focus) params.set("focus", opts.focus);
  if (opts.chapterId) params.set("chapter_id", opts.chapterId);
  const qs = params.toString();
  return apiFetch<NovelAuditOut>(
    `/projects/${id}/analysis/novel-audit${qs ? `?${qs}` : ""}`,
    { method: "POST", timeoutMs: TIMEOUTS.quick }
  );
}
