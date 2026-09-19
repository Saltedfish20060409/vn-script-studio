import {
  useCallback,
  useEffect,
  useMemo,
  useRef,
  useState,
  useSyncExternalStore,
} from "react";
import { useNavigate } from "react-router-dom";
import {
  ApiError,
  archiveChapterMemory,
  compareSnapshot,
  createProject,
  createShare,
  createSnapshot,
  deleteProject as apiDeleteProject,
  deleteSnapshot as apiDeleteSnapshot,
  duplicateProject as apiDuplicateProject,
  exportDocx,
  exportJson,
  exportMarkdown,
  exportRenpyBundle,
  exportRpy,
  generateRpyFromProse,
  getChapterMemoryArchive,
  getLatestMemory,
  getProject,
  getSettings,
  importProjectFile,
  listChapterMemory,
  listProjects,
  listSnapshots,
  mapExtract,
  mapExtractAccept,
  marksHint,
  patchProject,
  putProject,
  putSettings,
  restoreSnapshot as apiRestoreSnapshot,
  reviseMark,
  revokeShare,
  type MapExtractProposal,
  type MemoryArchiveDetail,
  type MemoryArchiveSummary,
  type ProjectSummary,
  type SnapshotDiffResult,
  type SnapshotSummary,
} from "../api/client";
import { useAuth } from "../lib/authContext";
import {
  getProjectLocks,
  lockChapter,
  subscribeProjectEvents,
  unlockChapter,
  type ChapterLockInfo,
} from "../api/collab";
import { ScriptEditor } from "./ScriptEditor";
import { MapStudio } from "./MapStudio";
import { MapExtractReview } from "./MapExtractReview";
import { AgentFloat } from "./AgentFloat";
import { AnalysisPanels } from "./AnalysisPanels";
import { SystemPanel } from "./SystemPanel";
import { SettingsGear, SettingsModal } from "./SettingsModal";
import { CharacterWorkshop } from "./CharacterWorkshop";
import { FocusChrome } from "./FocusChrome";
import { FilingFooter } from "./FilingFooter";
import { useConfirm, usePrompt } from "../lib/confirmDialog";
import { EmptyStage } from "./EmptyStage";
import { FirstRunChecklist } from "./FirstRunChecklist";
import { ProjectLibraryPanel } from "./ProjectLibraryPanel";
import { CollabPanel } from "./CollabPanel";
import { CommentsPanel } from "./CommentsPanel";
import { MarksPanel } from "./MarksPanel";
import { MarkCard } from "./MarkCard";
import { PwaInstallPrompt } from "./PwaInstallPrompt";
import { ProjectExportPanel } from "./ProjectExportPanel";
import { ProjectHistoryPanel } from "./ProjectHistoryPanel";
import { ProjectLedgerPanel } from "./ProjectLedgerPanel";
import { WritingStatsPanel } from "./WritingStatsPanel";
import { StudioBootScreen } from "./StudioBootScreen";
import { StudioChapterBar } from "./StudioChapterBar";
import { STUDIO_TABS } from "../lib/studioTabs";
import { StudioTabs } from "./StudioTabs";
import { StudioTopBar } from "./StudioTopBar";
import { TemplatePicker } from "./TemplatePicker";
import { OnboardingOverlay } from "./OnboardingOverlay";
import { hasSeenTour } from "../lib/onboarding";
import { QPet } from "./QPet";
import { AdminPanel } from "./AdminPanel";
import { ClickFx } from "./ClickFx";import { WorldPanel } from "./WorldPanel";
import { DesktopView, type DesktopApp } from "./DesktopView";
import { AgentChat } from "./AgentChat";
import { DeskPetApp } from "./DeskPetApp";
import { shouldShowDesktop, rearmBoot } from "../lib/desktopView";
import { openNotice } from "../lib/notice";
import { WriteToolbar, type WriteMode } from "./WriteToolbar";
import { ScriptCommandBar } from "./ScriptCommandBar";
import { AssetAuditPanel } from "./AssetAuditPanel";
import { LocalizationPanel } from "./LocalizationPanel";
import { MusicPlayerBar } from "./MusicPlayerBar";
import { HelpSheet } from "./HelpSheet";
import { StudioErrorBoundary } from "./StudioErrorBoundary";
import { SaveConflictDialog, type SaveConflictChoice } from "./SaveConflictDialog";
import { ScriptPlayer } from "./ScriptPlayer";
import {
  clearConflictDraft,
  downloadProjectJson,
  stashConflictDraft,
} from "../lib/conflictDraft";
import { StatusToast } from "./StatusToast";
import { classifyStatusToast } from "../lib/statusToast";
import { loadMusicBar, subscribeMusicBar } from "../lib/musicBar";
import { caretKey, loadCaretMap, readCaret, rememberCaret } from "../lib/caretMemory";
import {
  applyMark,
  createMark,
  currentMarkRange,
  loadMarks,
  pendingMarks,
  refreshMarks,
  revertMark,
  saveMarks,
  type Mark,
} from "../lib/marks";
import type { MarkRange } from "../lib/markHighlight";
import { blockTextRange, blocksToEditable, editableToBlocks } from "../lib/scriptCodec";
import { insertCommandAtLine } from "../lib/insertCommand";
import { chapterProse, proseFingerprint, rpyIsStale } from "../lib/scriptProse";
import { normalizeProject } from "../lib/vnLocal";
import { diffProjectAgainst } from "../lib/projectDiff";
import { EVENTS, trackOncePerUser } from "../lib/track";
import {
  applySettingsToDom,
  DEFAULT_SETTINGS,
  fromServerSettings,
  loadAppearanceCache,
  mergeSettingsAfterSave,
  saveAppearanceCache,
  toServerSettingsPatch,
  type AppSettings,
} from "../lib/settings";
import {
  loadWorkspace,
  saveWorkspace,
  workspaceDefaults,
  type StudioTab,
  type WorkspaceSnapshot,
} from "../lib/workspacePersist";
import {
  enterFullscreen,
  exitFullscreen,
  loadFocusMode,
  loadFocusTimerPrefs,
  saveFocusMode,
  saveFocusTimerPrefs,
  type FocusTimerPrefs,
} from "../lib/focusMode";
import {
  clearChapterReviseDraft,
  getChapterReviseDraft,
  requestOpenReviseReview,
  REVISE_DRAFT_EVENT,
  type ChapterReviseDraft,
} from "../lib/chapterReviseDraft";
import { mascotLine } from "../lib/mascotCopy";
import type { Character, StoryBible, VnProject } from "../types/vn";
import styles from "./StudioApp.module.css";

/** 顶栏只保留 5 组，细项用二级切换 */
type Tab = StudioTab;

/** tab 序号（与 StudioTabs 顺序一致）：用于切换滑动方向 */
const TAB_ORDER: StudioTab[] = [
  "write",
  "world",
  "voice",
  "map",
  "system",
  "project",
];

function tabIndex(tab: StudioTab): number {
  const i = TAB_ORDER.indexOf(tab);
  return i < 0 ? 0 : i;
}

function downloadText(filename: string, content: string, mime: string) {
  const blob = new Blob([content], { type: mime });
  downloadBlob(filename, blob);
}

function downloadBlob(filename: string, blob: Blob) {
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export function StudioApp() {
  const { logout, user } = useAuth();
  const navigate = useNavigate();
  const confirm = useConfirm();
  /** 底部固定音乐条开着时会把页脚（使用指南 / 备案号）压在下面，页脚要往上让 */
  const musicBarOn = useSyncExternalStore(subscribeMusicBar, loadMusicBar, loadMusicBar);
  const prompt = usePrompt();
  const cachedWs = useMemo(() => loadWorkspace(), []);
  const wsDefaults = workspaceDefaults();

  // 窄屏跟随窗口宽度：桌面视图在手机上自动让位给工作台（触屏没有双击/右键）
  useEffect(() => {
    const onResize = () => setViewportWidth(window.innerWidth);
    window.addEventListener("resize", onResize);
    return () => window.removeEventListener("resize", onResize);
  }, []);

  const [bootLoading, setBootLoading] = useState(true);
  const [projectsList, setProjectsList] = useState<ProjectSummary[]>([]);
  const [project, setProject] = useState<VnProject | null>(null);
  const [projectLoading, setProjectLoading] = useState(false);
  /** Collaboration: chapter lock held by another member + live member/lock events. */
  const [activeLocks, setActiveLocks] = useState<ChapterLockInfo[]>([]);
  const [collabNote, setCollabNote] = useState("");
  const myUserId = user?.id ?? "";

  const [tab, setTab] = useState<Tab>((cachedWs.tab as Tab) || wsDefaults.tab);
  /** 视图：三栏工作台 / 桌面。默认 studio（老用户习惯不变），可在系统设置里切换。 */
  const [view, setView] = useState<"studio" | "desktop">(cachedWs.view || wsDefaults.view);
  /**
   * 桌面视图里"当前打开的剧本窗口"是否开着。
   * 一个剧本一个窗口：这个窗口里的工作台（写作页/设定/角色工坊/地图/剧情状态）和 AI 责编
   * 都只属于 `project`，切换剧本时整块内容（含对话）跟着换，不存在"共用一套界面"的情况。
   */
  const [desktopScriptOpen, setDesktopScriptOpen] = useState(false);
  const [viewportWidth, setViewportWidth] = useState(() =>
    typeof window === "undefined" ? 1280 : window.innerWidth
  );
  const [writeSub, setWriteSub] = useState<"script" | "analysis">(
    cachedWs.writeSub || wsDefaults.writeSub
  );
  const [worldSub, setWorldSub] = useState<"characters" | "bible" | "lore" | "entries">(
    cachedWs.worldSub || wsDefaults.worldSub
  );
  const [systemSub, setSystemSub] = useState<"variables" | "sprites">(
    cachedWs.systemSub || wsDefaults.systemSub
  );
  // 子页类型直接取自持久化快照，新增子页时不会再出现"改了类型忘了改这里"
  const [projectSub, setProjectSub] = useState<WorkspaceSnapshot["projectSub"]>(
    cachedWs.projectSub || wsDefaults.projectSub
  );
  const [playOpen, setPlayOpen] = useState(false);
  const [tourOpen, setTourOpen] = useState(() => !hasSeenTour());
  const [petCheer, setPetCheer] = useState(0);
  const [chapterId, setChapterId] = useState(cachedWs.chapterId || "");
  const otherLock = activeLocks.find(
    (l) => l.chapterId === chapterId && l.userId !== myUserId
  );
  const [editor, setEditor] = useState("");
  const [writeMode, setWriteMode] = useState<WriteMode>(() => {
    try {
      return localStorage.getItem("vnss-write-mode") === "rpy" ? "rpy" : "prose";
    } catch {
      return "prose";
    }
  });
  const writeModeRef = useRef<WriteMode>(writeMode);
  writeModeRef.current = writeMode;
  const [generatingRpy, setGeneratingRpy] = useState(false);
  const [helpOpen, setHelpOpen] = useState(false);
  const [adminOpen, setAdminOpen] = useState(false);
  const [adminAlert, setAdminAlert] = useState(false);
  /** 以 overview 探测为准：避免旧会话 /me 缺 is_admin 时顶栏不显示「管理」 */
  const [adminCapable, setAdminCapable] = useState(false);
  const [selection, setSelection] = useState("");
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [saveConflict, setSaveConflict] = useState<{
    local: VnProject;
    serverUpdatedAt?: string;
  } | null>(null);
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settings, setSettings] = useState<AppSettings | null>(() => {
    const cached = loadAppearanceCache();
    return cached ? { ...DEFAULT_SETTINGS, ...cached } : null;
  });
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState("");
  const [shareUrl, setShareUrl] = useState("");
  const [mapExtractReview, setMapExtractReview] = useState<{
    proposal: MapExtractProposal;
    warnings?: string[];
    modeLabel: string;
  } | null>(null);
  const [mapExtractBusy, setMapExtractBusy] = useState(false);
  const [snapLabel, setSnapLabel] = useState("");
  const [snapshots, setSnapshots] = useState<SnapshotSummary[]>([]);
  const [compareBusy, setCompareBusy] = useState(false);
  const [compareResult, setCompareResult] = useState<SnapshotDiffResult | null>(null);
  const [compareAgainstId, setCompareAgainstId] = useState<string | null>(null);
  const [memoryArchives, setMemoryArchives] = useState<MemoryArchiveSummary[]>([]);
  const [memoryDetail, setMemoryDetail] = useState<MemoryArchiveDetail | null>(null);
  const [memoryDetailBusy, setMemoryDetailBusy] = useState(false);
  /** 导出页：先生成预览，再允许下载 */
  const [rpyPreview, setRpyPreview] = useState<string | null>(null);
  const [rpyStale, setRpyStale] = useState(false);
  const [bundleBusy, setBundleBusy] = useState(false);
  const [focusMode, setFocusMode] = useState(false);
  // 顶栏"审稿"按钮的展开信号：每次 +1 让 AgentFloat 把面板拉出来
  const [agentOpenTick, setAgentOpenTick] = useState(0);
  // 桌面视角下没有浮窗：这个计数改成打开桌面上的「AI 责编」窗口
  const [desktopAppTick, setDesktopAppTick] = useState(0);
  const [focusSetupOpen, setFocusSetupOpen] = useState(false);
  const [focusPrefs, setFocusPrefs] = useState<FocusTimerPrefs | null>(null);
  // 之前每次渲染都调 loadFocusTimerPrefs()（localStorage.getItem + JSON.parse），
  // 编辑器每次按键都会触发整树重渲染。改为：仅当打开设置弹窗或保存了新 prefs
  // （startFocusSession 会 setFocusPrefs）时才重读，其余渲染直接复用缓存对象。
  const focusInitialPrefs = useMemo(() => {
    // focusSetupOpen / focusPrefs 作为「失效键」：只在打开设置弹窗或保存了新 prefs
    // 时重读 localStorage，其余渲染复用缓存（避免每次按键都读盘解析）。
    void focusSetupOpen;
    void focusPrefs;
    return loadFocusTimerPrefs();
  }, [focusSetupOpen, focusPrefs]);
  const shellRef = useRef<HTMLDivElement>(null);
  /** 页面切换滑动方向：记录上一个 tab 序号，新 tab 靠右→从右滑入，靠左→从左滑入 */
  const prevTabIndexRef = useRef(0);

  const fileRef = useRef<HTMLInputElement>(null);
  const renameInputRef = useRef<HTMLInputElement>(null);

  const editorRef = useRef("");
  const editorTaRef = useRef<HTMLTextAreaElement | null>(null);
  const pendingEditorFocus = useRef<{
    chapterId: string;
    blockIndex: number;
  } | null>(null);
  const [editorFocusNonce, setEditorFocusNonce] = useState(0);
  /** 「上次停在这里」：本章上次停笔的偏移；null = 不提示 */
  const [caretHint, setCaretHint] = useState<number | null>(null);
  /** 写作页「标记批改」：作者标出来的待改处 + AI 的对照稿 */
  const [marks, setMarks] = useState<Mark[]>([]);
  /** 正在正文旁边核对的那一条（卡片贴着它那一行） */
  const [activeMarkId, setActiveMarkId] = useState<string | null>(null);
  const [markBusyId, setMarkBusyId] = useState<string | null>(null);
  const [markProgress, setMarkProgress] = useState<{ done: number; total: number } | null>(null);
  const [hasStyleMemory, setHasStyleMemory] = useState(false);
  const markStopRef = useRef(false);
  /** 标记在正文里的实际区间（正文高亮用）；定位不到的标记不进这里，由 stale 状态表达 */
  const markRanges = useMemo<MarkRange[]>(() => {
    const out: MarkRange[] = [];
    for (const mark of marks) {
      if (mark.status === "rejected") continue;
      // 已接受的用改写稿定位：原文已经不在了，否则刚接受完就会失去锚点
      const range = currentMarkRange(editor, mark);
      if (range) out.push({ id: mark.id, from: range.from, to: range.to, active: mark.id === activeMarkId });
    }
    return out;
  }, [marks, editor, activeMarkId]);
  /** 活动标记那一段的起始偏移：卡片贴着这一行显示 */
  const activeMarkOffset = useMemo(() => {
    if (!activeMarkId) return null;
    return markRanges.find((r) => r.id === activeMarkId)?.from ?? null;
  }, [activeMarkId, markRanges]);
  /** 正在核对的那条标记（卡片内容） */
  const activeMark = useMemo(
    () => (activeMarkId ? marks.find((m) => m.id === activeMarkId) ?? null : null),
    [activeMarkId, marks]
  );
  const [mapFocus, setMapFocus] = useState<{
    id: string;
    tick: number;
  } | null>(null);
  const [reviseDraft, setReviseDraft] = useState<ChapterReviseDraft | null>(null);
  const editorCommitTimer = useRef<number | null>(null);
  const projectSaveTimer = useRef<number | null>(null);
  const skipNextProjectSave = useRef(false);
  /** Last project snapshot the server confirmed — diff base for scoped saves. */
  const lastSavedRef = useRef<VnProject | null>(null);
  const settingsSaveTimer = useRef<number | null>(null);
  const skipNextSettingsSave = useRef(true);

  // Apply cached appearance immediately (before server settings return)
  useEffect(() => {
    if (settings) applySettingsToDom(settings);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // 章节记忆自动归档状态：章节够多时显示"已自动记住前 N 章要点"（roadmap 方向 F）。
  // 依赖用纯量（projectId / 章节数），避免每次保存都因为对象换引用而重复请求。
  const memProjectId = project?.id ?? "";
  const memChapterCount = (project?.chapters ?? []).length;
  const [memAuto, setMemAuto] = useState<{
    rangeTo: number;
    label: string;
  } | null>(null);
  useEffect(() => {
    if (!memProjectId || memChapterCount < 10) {
      setMemAuto(null);
      return;
    }
    let cancelled = false;
    getLatestMemory(memProjectId)
      .then(({ latest }) => {
        if (cancelled) return;
        setMemAuto(
          latest ? { rangeTo: latest.rangeTo, label: latest.label } : null
        );
      })
      .catch(() => {
        if (!cancelled) setMemAuto(null);
      });
    return () => {
      cancelled = true;
    };
  }, [memProjectId, memChapterCount]);


  // （历史上这里每 2 分钟打一次 /admin/overview 只为判断"是不是管理员"，
  //   普通用户必然 403——3 天 2318 次无效请求，已删除。）
  // 红点提醒改成打开管理面板时由 AdminPanel 自己加载。
  useEffect(() => {
    setAdminCapable(Boolean(user?.is_admin));
    setAdminAlert(false);
  }, [user?.id, user?.is_admin]);

  // Chapter revise preview chip (survives refresh via localStorage)
  useEffect(() => {
    if (!project?.id || !chapterId) {
      setReviseDraft(null);
      return;
    }
    function refresh() {
      setReviseDraft(getChapterReviseDraft(project!.id, chapterId));
    }
    refresh();
    window.addEventListener(REVISE_DRAFT_EVENT, refresh);
    window.addEventListener("storage", refresh);
    return () => {
      window.removeEventListener(REVISE_DRAFT_EVENT, refresh);
      window.removeEventListener("storage", refresh);
    };
    // Intentionally keyed on project id / chapter only: the revise preview
    // cache lives in localStorage and must not re-run on every project edit.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project?.id, chapterId]);

  const refreshProjectsList = useCallback(async () => {
    const list = await listProjects();
    setProjectsList(list);
    return list;
  }, []);

  const loadProjectInto = useCallback(
    async (id: string, preferredChapterId?: string) => {
      skipNextProjectSave.current = true;
      setProjectLoading(true);
      try {
        const p = await getProject(id);
        setProject(p);
        lastSavedRef.current = p;
        const ws = loadWorkspace();
        const wantChapter =
          preferredChapterId || (ws.projectId === id ? ws.chapterId : "") || "";
        const chapter =
          (wantChapter && p.chapters.find((c) => c.id === wantChapter)?.id) ||
          p.chapters[0]?.id ||
          "";
        setChapterId(chapter);
        saveWorkspace({ projectId: id, chapterId: chapter });
        const snaps = await listSnapshots(id).catch(() => []);
        setSnapshots(snaps);
        const mem = await listChapterMemory(id).catch(() => ({ archives: [] }));
        setMemoryArchives(mem.archives || []);
      } finally {
        setProjectLoading(false);
      }
    },
    []
  );

  // Boot: load project list + settings
  useEffect(() => {
    let cancelled = false;
    async function boot() {
      setBootLoading(true);
      try {
        const [list, serverSettings] = await Promise.all([
          listProjects(),
          getSettings().catch(() => null),
        ]);
        if (cancelled) return;
        setProjectsList(list);
        if (serverSettings) {
          const s = fromServerSettings(serverSettings);
          setSettings(s);
          applySettingsToDom(s);
          saveAppearanceCache(s);
        }
        if (list.length > 0) {
          const ws = loadWorkspace();
          let activeId = list[0].id;
          if (ws.projectId && list.some((p) => p.id === ws.projectId)) {
            activeId = ws.projectId;
          }
          await loadProjectInto(activeId, ws.chapterId);
        }
      } catch (e) {
        if (!cancelled) {
          setError(e instanceof Error ? e.message : "加载失败");
        }
      } finally {
        if (!cancelled) setBootLoading(false);
      }
    }
    void boot();
    return () => {
      cancelled = true;
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  // Persist UI navigation state (tab / chapter / side panel)
  useEffect(() => {
    if (!project?.id) return;
    saveWorkspace({
      projectId: project.id,
      chapterId,
      tab,
      writeSub,
      worldSub,
      systemSub,
      projectSub,
    });
  }, [project?.id, chapterId, tab, writeSub, worldSub, systemSub, projectSub]);

  // Sync editor text whenever project or chapter switches (not on every save).
  // 顺便清掉"选中文本"：剧本/章节换了之后，上一段选中的文字已经不属于当前文本，
  // 留着会被当成"当前选区"发给 AI 责编（跨剧本串味）。
  // 另外算出「上次停在这里」的按钮要不要出现（只在真的打开这一章时算一次，不自动跳）。
  useEffect(() => {
    setSelection("");
    if (!project || !chapterId) return;
    const ch = project.chapters.find((c) => c.id === chapterId);
    if (!ch) return;
    loadEditorFromChapter(ch, project.characters, writeModeRef.current);
    const saved = readCaret(
      loadCaretMap(),
      caretKey(project.id, chapterId, writeModeRef.current),
      { textLength: editorRef.current.length }
    );
    setCaretHint(saved);
    // 本章的标记：读本机保存的，并按当前正文重新定位（正文改过就标成"已失效"）
    setMarks(refreshMarks(editorRef.current, loadMarks(project.id, chapterId)));
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project?.id, chapterId]);

  // 标记落盘（只在本机）：加一道"标记属于当前章节"的守卫，
  // 否则切章那一刻会用旧标记写到新章节的键上。
  useEffect(() => {
    if (!project?.id || !chapterId) return;
    if (marks.some((m) => m.chapterId !== chapterId)) return;
    saveMarks(project.id, chapterId, marks);
  }, [marks, project?.id, chapterId]);

  // 「按你的文风改」是否生效：项目里有没有学过文风（纯查询，不花 token）
  useEffect(() => {
    if (!project?.id) {
      setHasStyleMemory(false);
      return;
    }
    let alive = true;
    marksHint(project.id)
      .then((r) => {
        if (alive) setHasStyleMemory(Boolean(r.hasStyleMemory));
      })
      .catch(() => {
        if (alive) setHasStyleMemory(false);
      });
    return () => {
      alive = false;
    };
  }, [project?.id]);

  /** 记住当前光标位置（失焦、切章、离开页面时各记一次；不每键都写）。 */
  const rememberCaretNow = useCallback(() => {
    const ta = editorTaRef.current;
    if (!ta || !project?.id || !chapterId) return;
    rememberCaret(project.id, chapterId, writeModeRef.current, ta.selectionStart ?? 0);
  }, [project?.id, chapterId]);

  /** 把编辑器滚到某个偏移并选中一段（"跳到上次停笔处"和"跳到某个标记"共用）。 */
  function focusEditorRange(from: number, to: number) {
    const ta = editorTaRef.current;
    if (!ta) return;
    ta.focus();
    ta.setSelectionRange(from, to);
    setSelection(ta.value.slice(from, to));
    const before = ta.value.slice(0, from);
    const line = before.split("\n").length;
    const styles = window.getComputedStyle(ta);
    const lh = Number.parseFloat(styles.lineHeight);
    const lineHeight = Number.isFinite(lh) && lh > 0 ? lh : 22;
    const pad = Number.parseFloat(styles.paddingTop) || 0;
    ta.scrollTop = Math.max(0, (line - 3) * lineHeight - pad);
  }

  /** 跳到"上次停下的地方"：把光标放回去并滚到那一行（用户点了才动，不自动抢焦点）。 */
  function jumpToLastCaret() {
    const offset = caretHint;
    setCaretHint(null);
    if (offset === null) return;
    focusEditorRange(offset, offset);
  }

  // ---- 标记批改：标记 / 处理 / 接受 / 撤回 -------------------------------------

  /** 把当前选中的一段标成"要改"。 */
  function markSelection() {
    const ta = editorTaRef.current;
    if (!ta || !chapterId) return;
    const from = ta.selectionStart ?? 0;
    const to = ta.selectionEnd ?? 0;
    const mark = createMark({
      text: editorRef.current,
      from,
      to,
      chapterId,
      intent: "rewrite",
    });
    if (!mark) {
      setStatus("先选中一小段正文，再点「标记这段」");
      return;
    }
    setMarks((prev) => refreshMarks(editorRef.current, [...prev, mark]));
    // 立刻把卡片贴到这一段旁边（用户不用去下面找）
    setActiveMarkId(mark.id);
    setStatus("已标记这一段：在正文旁边直接处理，或点「按标记处理」批量跑");
  }

  /** 处理单个标记（改写或只给建议）。 */
  async function processMark(id: string): Promise<boolean> {
    const mark = marks.find((m) => m.id === id);
    if (!mark || !project?.id) return false;
    setMarkBusyId(id);
    setMarks((prev) =>
      prev.map((m) => (m.id === id ? { ...m, error: undefined } : m))
    );
    try {
      const out = await reviseMark(project.id, {
        chapterId: mark.chapterId,
        quote: mark.quote,
        prefix: mark.prefix,
        suffix: mark.suffix,
        instruction: mark.instruction,
        intent: mark.intent,
      });
      setMarks((prev) =>
        prev.map((m) =>
          m.id === id
            ? {
                ...m,
                replacement: out.replacement || undefined,
                advice: out.advice || undefined,
                status: "suggested" as const,
                error: undefined,
              }
            : m
        )
      );
      return true;
    } catch (e) {
      const msg = e instanceof Error ? e.message : "处理失败";
      setMarks((prev) => prev.map((m) => (m.id === id ? { ...m, error: msg } : m)));
      return false;
    } finally {
      setMarkBusyId(null);
    }
  }

  /** 逐条处理所有待处理标记：单条失败不影响其它，可随时停。 */
  async function processAllMarks() {
    const queue = pendingMarks(marks).filter((m) => m.status === "pending" || m.error);
    if (queue.length === 0) {
      setStatus("没有待处理的标记");
      return;
    }
    markStopRef.current = false;
    setMarkProgress({ done: 0, total: queue.length });
    let done = 0;
    for (const mark of queue) {
      if (markStopRef.current) break;
      await processMark(mark.id);
      done += 1;
      setMarkProgress({ done, total: queue.length });
    }
    setMarkProgress(null);
    setStatus(
      markStopRef.current ? `已停止（完成 ${done}/${queue.length}）` : `已处理 ${done} 处标记`
    );
  }

  /** 接受一条改写的标记：写进正文（可之后再撤回）。 */
  function acceptMark(id: string, edited?: string) {
    const mark = marks.find((m) => m.id === id);
    if (!mark) return;
    const override = edited && edited.trim() ? edited : undefined;
    const result = applyMark(editorRef.current, mark, override);
    if (!result) {
      setMarks((prev) => prev.map((m) => (m.id === id ? { ...m, status: "stale" } : m)));
      setStatus("这段正文已经改过了，标记失效：请跳到正文确认后再处理");
      return;
    }
    editorRef.current = result.text;
    setEditor(result.text);
    if (rpyPreview) setRpyStale(true);
    scheduleEditorCommit();
    setMarks((prev) =>
      refreshMarks(result.text, prev).map((m) =>
        m.id === id
          ? {
              ...m,
              replacement: override ?? m.replacement,
              status: "accepted" as const,
              appliedAt: Date.now(),
            }
          : m
      )
    );
    setStatus("已写入正文（可以逐条撤回）");
    // 接受完自动跳到下一条待决定的标记
    window.setTimeout(() => activateNextMark(id), 0);
  }

  /** 撤回一条已写入的改动。 */
  function revertMarkChange(id: string) {
    const mark = marks.find((m) => m.id === id);
    if (!mark) return;
    const result = revertMark(editorRef.current, mark);
    if (!result) {
      setStatus("正文后来又改过，撤回不了：可以手工改回，或按 Ctrl+Z 撤销编辑器操作");
      return;
    }
    editorRef.current = result.text;
    setEditor(result.text);
    scheduleEditorCommit();
    setMarks((prev) =>
      refreshMarks(result.text, prev).map((m) =>
        m.id === id ? { ...m, status: "suggested" as const } : m
      )
    );
    setStatus("已撤回这条改动");
  }

  function removeMark(id: string) {
    setMarks((prev) => prev.filter((m) => m.id !== id));
    setActiveMarkId((prev) => (prev === id ? null : prev));
  }

  /** 选中一条标记：编辑器滚到它那儿并选中，卡片贴过去（定位不到就说明失效了）。 */
  function selectMark(id: string) {
    setActiveMarkId(id);
    const mark = marks.find((m) => m.id === id);
    if (!mark) return;
    const range = currentMarkRange(editorRef.current, mark);
    if (!range) {
      setStatus("这一段在正文里已经找不到了（被改过或删掉），标记已失效");
      setMarks((prev) => prev.map((m) => (m.id === id ? { ...m, status: "stale" } : m)));
      return;
    }
    focusEditorRange(range.from, range.to);
  }

  /**
   * 处理完之后自动跳到下一条待决定的标记（省得自己找）。
   * 没有下一条时**留在当前这条**——卡片收起的话「撤回这次改动」就点不到了。
   */
  function activateNextMark(afterId: string) {
    const idx = marks.findIndex((m) => m.id === afterId);
    if (idx < 0) return;
    const ordered = [...marks.slice(idx + 1), ...marks.slice(0, idx)];
    const next =
      ordered.find((m) => m.status === "suggested" && (m.replacement || m.advice)) ??
      ordered.find((m) => m.status === "pending");
    if (next) selectMark(next.id);
  }

  function setMarkInstruction(id: string, value: string) {
    setMarks((prev) => prev.map((m) => (m.id === id ? { ...m, instruction: value } : m)));
  }

  function setMarkIntent(id: string, intent: "rewrite" | "advice") {
    setMarks((prev) =>
      prev.map((m) =>
        m.id === id
          ? { ...m, intent, replacement: undefined, advice: undefined, error: undefined, status: "pending" }
          : m
      )
    );
  }

  // Map → write: scroll/select the target block after chapter text is ready.
  useEffect(() => {
    const pending = pendingEditorFocus.current;
    if (!pending || !project) return;
    if (pending.chapterId !== chapterId) return;
    if (tab !== "write" || writeSub !== "script") return;
    const ch = project.chapters.find((c) => c.id === chapterId);
    if (!ch) return;
    const range = blockTextRange(ch.blocks, project.characters, pending.blockIndex);
    if (!range) {
      pendingEditorFocus.current = null;
      return;
    }
    const id = window.requestAnimationFrame(() => {
      const ta = editorTaRef.current;
      if (!ta) return;
      pendingEditorFocus.current = null;
      ta.focus();
      ta.setSelectionRange(range.start, range.end);
      setSelection(ta.value.slice(range.start, range.end));
      const before = ta.value.slice(0, range.start);
      const line = before.split("\n").length;
      const styles = window.getComputedStyle(ta);
      const lh = Number.parseFloat(styles.lineHeight);
      const lineHeight = Number.isFinite(lh) && lh > 0 ? lh : 22;
      const pad = Number.parseFloat(styles.paddingTop) || 0;
      ta.scrollTop = Math.max(0, (line - 3) * lineHeight - pad);
    });
    return () => window.cancelAnimationFrame(id);
  }, [project, chapterId, editor, tab, writeSub, editorFocusNonce]);

  // Flush draft when tab is hidden / page is closing so exit doesn't lose work
  // （顺便把"停笔位置"记下来：这两个时机过后就再也读不到光标了）
  useEffect(() => {
    const onHide = () => {
      if (document.visibilityState === "hidden") {
        rememberCaretNow();
        void flushPendingSave();
      }
    };
    const onUnload = () => {
      rememberCaretNow();
      void flushPendingSave();
    };
    document.addEventListener("visibilitychange", onHide);
    window.addEventListener("pagehide", onUnload);
    return () => {
      document.removeEventListener("visibilitychange", onHide);
      window.removeEventListener("pagehide", onUnload);
    };
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project, chapterId, tab, writeSub, worldSub, systemSub, projectSub]);

  useEffect(() => {
    setRpyPreview(null);
    setRpyStale(false);
  }, [project?.id]);

  // Collaboration: claim current-chapter lock, watch live member/lock events.
  useEffect(() => {
    if (!project || !chapterId) return;
    let cancelled = false;
    const pid = project.id;
    const cid = chapterId;

    const refreshLocks = async () => {
      try {
        const data = await getProjectLocks(pid);
        if (!cancelled) setActiveLocks(data.locks);
      } catch {
        /* member without read rights or transient — ignore */
      }
    };

    const note = (text: string) => {
      if (cancelled) return;
      setCollabNote(text);
      window.setTimeout(() => {
        if (!cancelled) setCollabNote("");
      }, 5000);
    };

    const unsub = subscribeProjectEvents(pid, (evt) => {
      if (cancelled) return;
      if (evt.type === "lock" || evt.type === "member") {
        void refreshLocks();
        if (evt.type === "lock") {
          note(
            evt.kind === "acquired"
              ? `${evt.username || "有成员"} 开始编辑${evt.chapterId ? "该章" : ""}`
              : "有成员释放了章节锁"
          );
        } else {
          note("项目成员有变化");
        }
      }
    });

    // Claim this chapter (viewer/member failures are ignored).
    void lockChapter(pid, cid)
      .catch(() => undefined)
      .then(() => void refreshLocks());
    void refreshLocks();

    return () => {
      cancelled = true;
      unsub();
      void unlockChapter(pid, cid).catch(() => undefined);
    };
    // Intentionally keyed on project id / chapter only: the lock + SSE
    // subscription must stay stable across project edits (autosaves).
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project?.id, chapterId]);

  // Debounced autosave whenever the project object changes.
  useEffect(() => {
    if (!project) return;
    if (skipNextProjectSave.current) {
      skipNextProjectSave.current = false;
      return;
    }
    if (projectSaveTimer.current) window.clearTimeout(projectSaveTimer.current);
    projectSaveTimer.current = window.setTimeout(() => {
      void persistProject(project, { silent: true });
    }, 800);
    return () => {
      if (projectSaveTimer.current) window.clearTimeout(projectSaveTimer.current);
    };
  }, [project]);

  async function persistProject(
    p: VnProject,
    opts?: { silent?: boolean; force?: boolean }
  ) {
    const silent = opts?.silent ?? true;
    try {
      if (!silent) setStatus("保存中…");
      // Collaboration stage B: compute which chapters / sections this save
      // actually changed. The server merges only those, so concurrent edits
      // to other chapters survive. Full-save (no base or force) stays as-is.
      let scoped: { chapterIds?: string[]; sections?: string[] } = {};
      if (!opts?.force) {
        const diff = diffProjectAgainst(lastSavedRef.current, p);
        if (!diff.hasChanges && lastSavedRef.current) {
          // 没有任何实际内容变化：不发保存请求。
          // 服务器 updatedAt 可能已被其他会话/自动保存推进，无变化也 PUT
          // 会触发 409 冲突弹窗（"没改也提示"）。跳过既省请求也消除误报。
          return true;
        }
        if (diff.chapterIds.length > 0 || diff.sections.length > 0) {
          scoped = { chapterIds: diff.chapterIds, sections: diff.sections };
        }
      }
      const saved = await putProject(p.id, p, p.updatedAt, {
        force: opts?.force,
        ...scoped,
      });
      lastSavedRef.current = saved;
      skipNextProjectSave.current = true;
      setProject(saved);
      setPetCheer((v) => v + 1);
      clearConflictDraft(saved.id);
      setSaveConflict(null);
      setProjectsList((prev) =>
        prev.map((s) =>
          s.id === saved.id
            ? {
                ...s,
                title: saved.title,
                logline: saved.logline,
                genre: saved.genre,
                updated_at: saved.updatedAt,
              }
            : s
        )
      );
      if (!silent) setStatus("工程已同步到服务器");
      return true;
    } catch (e) {
      if (e instanceof ApiError && e.status === 423) {
        // Chapter locked by another member — scoped save rejected.
        const detail = e.detail as
          | { message?: string; username?: string; chapterId?: string }
          | undefined;
        const who = detail?.username ? `（${detail.username}）` : "";
        setStatus("章节被其他成员锁定");
        setError(
          detail?.message ||
            `该章节正被其他成员编辑${who}，请等待其释放锁后再保存`
        );
        return false;
      }
      if (e instanceof ApiError && e.status === 409) {
        stashConflictDraft(p);
        const detail = e.detail as
          { serverUpdatedAt?: string; message?: string } | undefined;
        if (projectSaveTimer.current) {
          window.clearTimeout(projectSaveTimer.current);
          projectSaveTimer.current = null;
        }
        setSaveConflict({
          local: p,
          serverUpdatedAt: detail?.serverUpdatedAt,
        });
        setError("");
        setStatus("发现保存冲突 — 你刚写的内容和云端已有的内容不一致（可能两处都改过同一部分），请选择保留哪一份");
        return false;
      }
      setError(e instanceof Error ? e.message : "保存失败");
      return false;
    }
  }

  async function resolveSaveConflict(choice: SaveConflictChoice) {
    const pending = saveConflict;
    if (!pending) return;
    if (choice === "download") {
      downloadProjectJson(pending.local);
      setStatus("已把你这边的稿子下载成备份文件，弹窗仍保留，可以继续选择保留哪一份稿子");
      return;
    }
    if (choice === "keep_local") {
      setSaveConflict(null);
      const ok = await persistProject(pending.local, {
        silent: false,
        force: true,
      });
      if (ok) setStatus("已用本地稿覆盖服务器版本");
      return;
    }
    // take_server
    try {
      const fresh = await getProject(pending.local.id);
      skipNextProjectSave.current = true;
      lastSavedRef.current = fresh;
      setProject(fresh);
      setSaveConflict(null);
      setStatus("已载入服务器版本（本地稿仍暂存在浏览器）");
    } catch (e) {
      setError(e instanceof Error ? e.message : "拉取服务器版本失败");
    }
  }

  /** Flush editor buffer + pending project save before leave / logout */
  async function flushPendingSave() {
    if (editorCommitTimer.current) {
      window.clearTimeout(editorCommitTimer.current);
      editorCommitTimer.current = null;
    }
    if (projectSaveTimer.current) {
      window.clearTimeout(projectSaveTimer.current);
      projectSaveTimer.current = null;
    }
    const latest = buildLatestProject();
    if (!latest) return;
    saveWorkspace({
      projectId: latest.id,
      chapterId,
      tab,
      writeSub,
      worldSub,
      systemSub,
      projectSub,
    });
    await persistProject(latest);
  }

  // Debounced settings autosave.
  useEffect(() => {
    if (!settings) return;
    if (skipNextSettingsSave.current) {
      skipNextSettingsSave.current = false;
      return;
    }
    if (settingsSaveTimer.current) window.clearTimeout(settingsSaveTimer.current);
    settingsSaveTimer.current = window.setTimeout(() => {
      void persistSettings(settings);
    }, 600);
    return () => {
      if (settingsSaveTimer.current) window.clearTimeout(settingsSaveTimer.current);
    };
  }, [settings]);

  async function persistSettings(next: AppSettings) {
    try {
      const out = await putSettings(toServerSettingsPatch(next));
      const safe = mergeSettingsAfterSave(next, out);
      skipNextSettingsSave.current = true;
      setSettings(safe);
      applySettingsToDom(safe);
      saveAppearanceCache(safe);
    } catch (e) {
      // Keep local appearance even if cloud save fails (e.g. oversized image)
      saveAppearanceCache(next);
      applySettingsToDom(next);
      setError(e instanceof Error ? e.message : "设置保存失败");
    }
  }

  const updateActive = useCallback((updater: (p: VnProject) => VnProject) => {
    setProject((prev) => {
      if (!prev) return prev;
      return normalizeProject({
        ...updater(prev),
        updatedAt: new Date().toISOString(),
      });
    });
  }, []);

  function replaceActiveProject(nextProject: VnProject) {
    setProject((prev) => {
      if (!prev) return prev;
      return normalizeProject({
        ...nextProject,
        id: prev.id,
        updatedAt: new Date().toISOString(),
      });
    });
  }

  /** Apply a project snapshot already persisted on the server (preserve updatedAt). */
  function applyRemoteProject(nextProject: VnProject) {
    if (projectSaveTimer.current) {
      window.clearTimeout(projectSaveTimer.current);
      projectSaveTimer.current = null;
    }
    skipNextProjectSave.current = true;
    setError("");
    lastSavedRef.current = nextProject;
    setProject((prev) => {
      if (!prev) return prev;
      return normalizeProject({
        ...nextProject,
        id: prev.id,
      });
    });
  }

  const chapter = useMemo(
    () => project?.chapters.find((c) => c.id === chapterId),
    [project, chapterId]
  );

  function loadEditorFromChapter(
    ch: VnProject["chapters"][number],
    characters: VnProject["characters"],
    mode: WriteMode
  ) {
    const text =
      mode === "prose"
        ? chapterProse(ch, characters)
        : blocksToEditable(ch.blocks, characters);
    editorRef.current = text;
    setEditor(text);
  }

  function flushChapter(
    p: VnProject,
    chId: string,
    text: string,
    mode: WriteMode
  ): VnProject {
    return {
      ...p,
      chapters: p.chapters.map((c) => {
        if (c.id !== chId) return c;
        return mode === "prose"
          ? { ...c, prose: text }
          : { ...c, blocks: editableToBlocks(text) };
      }),
    };
  }

  function commitEditor() {
    if (editorCommitTimer.current) {
      window.clearTimeout(editorCommitTimer.current);
      editorCommitTimer.current = null;
    }
    if (!project || !chapter) return;
    const mode = writeModeRef.current;
    const text = editorRef.current;
    const chId = chapter.id;
    updateActive((p) => flushChapter(p, chId, text, mode));
  }

  function scheduleEditorCommit() {
    if (editorCommitTimer.current) window.clearTimeout(editorCommitTimer.current);
    editorCommitTimer.current = window.setTimeout(() => commitEditor(), 900);
  }

  function buildLatestProject(): VnProject | null {
    if (!project) return null;
    if (!chapter) return project;
    return flushChapter(
      project,
      chapter.id,
      editorRef.current,
      writeModeRef.current
    );
  }

  function persistWriteMode(next: WriteMode) {
    writeModeRef.current = next;
    setWriteMode(next);
    try {
      localStorage.setItem("vnss-write-mode", next);
    } catch {
      /* ignore */
    }
  }

  function switchWriteMode(next: WriteMode) {
    if (!project || !chapter || next === writeModeRef.current) return;
    if (editorCommitTimer.current) {
      window.clearTimeout(editorCommitTimer.current);
      editorCommitTimer.current = null;
    }
    const flushed = flushChapter(
      project,
      chapter.id,
      editorRef.current,
      writeModeRef.current
    );
    updateActive(() => flushed);
    persistWriteMode(next);
    const ch = flushed.chapters.find((c) => c.id === chapter.id);
    if (ch) loadEditorFromChapter(ch, flushed.characters, next);
  }

  async function generateRpyFromManuscript() {
    if (!project || !chapter) return;
    if (editorCommitTimer.current) {
      window.clearTimeout(editorCommitTimer.current);
      editorCommitTimer.current = null;
    }
    const flushed = flushChapter(
      project,
      chapter.id,
      editorRef.current,
      writeModeRef.current
    );
    const ch = flushed.chapters.find((c) => c.id === chapter.id);
    const prose = (ch?.prose || "").trim() || chapterProse(ch, flushed.characters);
    if (!prose.trim()) {
      setError("本章还没有可转换的内容。请先在编辑器里写一段正文或对白（对白写成「角色名：台词」），写完再点一次生成。");
      return;
    }
    setGeneratingRpy(true);
    setError("");
    try {
      const out = await generateRpyFromProse(project.id, chapter.id, prose, true);
      const next: VnProject = {
        ...flushed,
        chapters: flushed.chapters.map((c) =>
          c.id === chapter.id
            ? {
                ...c,
                prose,
                blocks: out.blocks,
                rpyFromProseHash: proseFingerprint(prose),
              }
            : c
        ),
      };
      updateActive(() => next);
      persistWriteMode("rpy");
      const updated = next.chapters.find((c) => c.id === chapter.id);
      if (updated) loadEditorFromChapter(updated, next.characters, "rpy");
      setRpyPreview(out.rpy);
      setRpyStale(false);
      setStatus(out.usedLlm ? "已把正文转换成可试玩的 Ren'Py 脚本" : "已把正文转换成可试玩的 Ren'Py 脚本（本次为直接转换，未使用 AI）");
    } catch (e) {
      setError(e instanceof Error ? e.message : "生成 RPY 失败");
    } finally {
      setGeneratingRpy(false);
    }
  }

  async function exportCurrentView() {
    if (!project || !chapter) return;
    if (editorCommitTimer.current) {
      window.clearTimeout(editorCommitTimer.current);
      editorCommitTimer.current = null;
    }
    const latest = buildLatestProject();
    if (!latest) return;
    commitEditor();
    try {
      await persistProject(latest);
      if (writeModeRef.current === "rpy") {
        const text = await exportRpy(latest.id);
        downloadText(`${latest.title || "script"}.rpy`, text, "text/plain;charset=utf-8");
        trackOncePerUser(EVENTS.exportDone, { kind: "rpy" });
      } else {
        const blob = await exportDocx(latest.id);
        downloadBlob(`${latest.title || "script"}.docx`, blob);
        trackOncePerUser(EVENTS.exportDone, { kind: "docx" });
      }
    } catch (e) {
      setError(e instanceof Error ? e.message : "导出失败");
    }
  }

  async function generateRpy() {
    if (!project) return;
    const latest = buildLatestProject();
    if (!latest) return;
    commitEditor();
    try {
      setStatus("生成导出中…");
      setError("");
      const saved = await putProject(latest.id, latest, latest.updatedAt);
      skipNextProjectSave.current = true;
      setProject(saved);
      const text = await exportRpy(saved.id);
      setRpyPreview(text);
      setRpyStale(false);
      setStatus("已根据当前剧本生成 .rpy，可预览后下载");
    } catch (e) {
      setError(e instanceof Error ? e.message : "生成失败");
      setStatus("");
    }
  }

  async function switchProject(id: string) {
    if (id === project?.id) return;
    commitEditor();
    setTab("write");
    setWriteSub("script");
    try {
      await loadProjectInto(id);
      const found = projectsList.find((p) => p.id === id);
      setStatus(found ? `已切换到「${found.title}」` : "已切换剧本");
    } catch (e) {
      setError(e instanceof Error ? e.message : "加载失败");
    }
  }

  async function createBlank() {
    const title = await prompt({
      title: "新剧本标题",
      defaultValue: "未命名剧本",
      confirmLabel: "创建",
    });
    if (title === null) return;
    try {
      const created = await createProject({ title: title.trim() || "未命名剧本" });
      await refreshProjectsList();
      skipNextProjectSave.current = true;
      setProject(created);
      setChapterId(created.chapters[0]?.id ?? "");
      saveWorkspace({
        projectId: created.id,
        chapterId: created.chapters[0]?.id ?? "",
        tab: "write",
        writeSub: "script",
      });
      setTab("write");
      setWriteSub("script");
      setStatus("已创建空白剧本");
    } catch (e) {
      setError(e instanceof Error ? e.message : "创建失败");
    }
  }

  async function createDemo() {
    try {
      const created = await createProject({ from_demo: true });
      await refreshProjectsList();
      skipNextProjectSave.current = true;
      setProject(created);
      setChapterId(created.chapters[0]?.id ?? "");
      saveWorkspace({
        projectId: created.id,
        chapterId: created.chapters[0]?.id ?? "",
        tab: "write",
        writeSub: "script",
      });
      setTab("write");
      setWriteSub("script");
      setStatus("已加入示例剧本");
    } catch (e) {
      setError(e instanceof Error ? e.message : "创建失败");
    }
  }

  async function createFromTemplate(templateId: string) {
    try {
      const created = await createProject({ template_id: templateId });
      await refreshProjectsList();
      skipNextProjectSave.current = true;
      setProject(created);
      setChapterId(created.chapters[0]?.id ?? "");
      saveWorkspace({
        projectId: created.id,
        chapterId: created.chapters[0]?.id ?? "",
        tab: "write",
        writeSub: "script",
      });
      setTab("write");
      setWriteSub("script");
      setStatus(`已从模板创建「${created.title}」`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "创建失败");
    }
  }

  async function deleteProjectById(id: string) {
    if (projectsList.length <= 1) {
      setError("至少保留一个剧本");
      return;
    }
    const target = projectsList.find((p) => p.id === id);
    const ok = await confirm({
      title: `删除剧本「${target?.title ?? ""}」？`,
      body: "删除后，该剧本连同全部章节、正文和设定都会被永久删除，无法恢复。如果只是想暂时放着，也可以先不删。",
      danger: true,
      confirmLabel: "确认删除",
    });
    if (!ok) return;
    try {
      await apiDeleteProject(id);
      const list = await refreshProjectsList();
      if (project?.id === id) {
        const next = list[0];
        if (next) await loadProjectInto(next.id);
        else setProject(null);
      }
      setStatus("已删除剧本");
    } catch (e) {
      setError(e instanceof Error ? e.message : "删除失败");
    }
  }

  async function duplicateProjectById(id: string) {
    try {
      const copy = await apiDuplicateProject(id);
      await refreshProjectsList();
      setStatus(`已复制为「${copy.title}」`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "复制失败");
    }
  }

  function startRename(id: string) {
    const target = projectsList.find((p) => p.id === id);
    if (!target) return;
    setRenamingId(id);
    setRenameDraft(target.title);
    requestAnimationFrame(() => renameInputRef.current?.focus());
  }

  /** 改标题（列表页的内联重命名与桌面右键重命名共用这一处，避免两份逻辑走偏） */
  async function renameProjectById(id: string, raw: string) {
    const title = raw.trim() || "未命名剧本";
    try {
      const updated = await patchProject(id, { title });
      setProjectsList((prev) =>
        prev.map((p) => (p.id === id ? { ...p, title: updated.title } : p))
      );
      if (project?.id === id) {
        setProject((prev) => (prev ? { ...prev, title: updated.title } : prev));
      }
      setStatus(`已重命名为「${title}」`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "重命名失败");
    }
  }

  async function commitRename() {
    if (!renamingId) return;
    const title = renameDraft;
    const id = renamingId;
    setRenamingId(null);
    await renameProjectById(id, title);
  }

  function cancelRename() {
    setRenamingId(null);
    setRenameDraft("");
  }

  async function handleImportFile(file: File) {
    setError("");
    try {
      const imported = await importProjectFile(file);
      await refreshProjectsList();
      skipNextProjectSave.current = true;
      setProject(imported);
      setChapterId(imported.chapters[0]?.id ?? "");
      saveWorkspace({
        projectId: imported.id,
        chapterId: imported.chapters[0]?.id ?? "",
        tab: "write",
        writeSub: "script",
      });
      setTab("write");
      setWriteSub("script");
      setStatus(`已导入「${imported.title}」`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "导入失败");
    }
  }

  function updateCharacter(id: string, patch: Partial<Character>) {
    updateActive((p) => ({
      ...p,
      characters: p.characters.map((c) => (c.id === id ? { ...c, ...patch } : c)),
    }));
  }

  function addCharacter() {
    updateActive((p) => {
      const n = p.characters.length + 1;
      const id = `char${n}`;
      return {
        ...p,
        characters: [
          ...p.characters,
          {
            id,
            defineName: id,
            displayName: `角色${n}`,
            color: "#6b7280",
            voice: "",
            bio: "",
            relationships: "",
          },
        ],
      };
    });
  }

  async function deleteCharacter(id: string) {
    const ok = await confirm({
      title: "删除该角色？",
      body: "删除角色卡片后，正文里已写好的对白不会自动修改，需要你手动检查所有提到 TA 的地方，再决定是否删除。",
      danger: true,
      confirmLabel: "确认删除",
    });
    if (!ok) return;
    updateActive((p) => ({
      ...p,
      characters: p.characters.filter((c) => c.id !== id),
    }));
  }

  function updateBible(patch: Partial<StoryBible>) {
    updateActive((p) => {
      const nextBible = { ...(p.bible ?? {}), ...patch };
      const world = nextBible.world ?? p.bible?.world ?? "";
      return {
        ...p,
        bible: nextBible,
        // Deprecated mirror of bible.world for older saves / exports
        lore: world,
      };
    });
  }

  async function addChapter() {
    const title = await prompt({
      title: "章节标题",
      defaultValue: `第${(project?.chapters.length ?? 0) + 1}章`,
      confirmLabel: "添加",
    });
    if (title === null) return;
    const id = `ch-${Date.now().toString(36)}`;
    updateActive((p) => ({
      ...p,
      chapters: [
        ...p.chapters,
        {
          id,
          title: title.trim() || "新章节",
          prose: "",
          blocks: [{ type: "label", id: "start", name: "start" }],
        },
      ],
    }));
    commitEditor();
    setChapterId(id);
  }

  async function deleteChapter(id: string) {
    if (!project || project.chapters.length <= 1) {
      setError("至少保留一章");
      return;
    }
    const ok = await confirm({
      title: "删除该章节？",
      body: "该章节连同全部正文会从云端永久删除，无法恢复。请确认这一章的内容你已经不需要了。",
      danger: true,
      confirmLabel: "确认删除",
    });
    if (!ok) return;
    const next = project.chapters.filter((c) => c.id !== id);
    updateActive((p) => ({ ...p, chapters: next }));
    if (chapterId === id) setChapterId(next[0].id);
  }

  async function extractLocs(mode: "smart" | "rules" = "smart") {
    if (!project) return;
    commitEditor();
    try {
      setStatus(mode === "smart" ? "智能提取地图中…" : "按场景标签提取中…");
      const latest = buildLatestProject();
      const projectId = latest?.id ?? project.id;
      if (latest) {
        const saved = await putProject(latest.id, latest, latest.updatedAt);
        lastSavedRef.current = saved;
        skipNextProjectSave.current = true;
        setProject(saved);
      }
      const result = await mapExtract(projectId, { mode });
      const warn =
        result.warnings && result.warnings.length ? `（${result.warnings[0]}）` : "";
      const newPlaces = result.proposal?.newPlaceIds?.length ?? result.addedCount;
      const newLinks = result.proposal?.newLinkIds?.length ?? result.linkCount;
      if (newPlaces === 0 && newLinks === 0) {
        setStatus(
          `没有从正文里识别出新的地点。想让地图更完整，可以在场景开头写清地点（例如「scene bg 车站」），或让对白/设定明确提到具体场所，然后再试一次。${warn}`
        );
        setTab("map");
        return;
      }
      setMapExtractReview({
        proposal: result.proposal,
        warnings: result.warnings,
        modeLabel:
          mode === "smart"
            ? `智能提取${result.llmUsed ? "（含模型）" : ""}`
            : "按场景标签",
      });
      setStatus(`找到候选：地点 ${newPlaces}、通路 ${newLinks}，请勾选后写入${warn}`);
      setTab("map");
    } catch (e) {
      setError(e instanceof Error ? e.message : "提取失败");
    }
  }

  async function confirmMapExtract(placeIds: string[], linkIds: string[]) {
    if (!project || !mapExtractReview) return;
    if (placeIds.length === 0 && linkIds.length === 0) {
      setMapExtractReview(null);
      setStatus("已取消写入（未选择任何候选）");
      return;
    }
    setMapExtractBusy(true);
    try {
      const result = await mapExtractAccept(project.id, {
        placeIds,
        linkIds,
        proposal: mapExtractReview.proposal,
      });
      skipNextProjectSave.current = true;
      setProject(result.project);
      setMapExtractReview(null);
      setStatus(`已写入地图：新增地点 ${result.addedCount}，通路 ${result.linkCount}`);
      setTab("map");
    } catch (e) {
      setError(e instanceof Error ? e.message : "写入地图失败");
    } finally {
      setMapExtractBusy(false);
    }
  }

  async function archiveLongMemory() {
    if (!project) return;
    commitEditor();
    try {
      setStatus("正在把前面的章节整理成记忆存档…");
      const latest = buildLatestProject();
      if (latest) {
        const saved = await putProject(latest.id, latest, latest.updatedAt);
        lastSavedRef.current = saved;
        skipNextProjectSave.current = true;
        setProject(saved);
      }
      const result = await archiveChapterMemory(project.id, {
        span: 10,
        includeIncomplete: true,
      });
      setMemoryArchives(result.archives || []);
      setMemoryDetail(null);
      setStatus(
        result.count
          ? `已把前面的章节整理成记忆存档：共 ${result.count} 段，最新到「${result.latestLabel}」。续写时 AI 会按需参考这些存档；内容太多时太久远的段落可能读不到，重要设定建议另外写在设定资料里。`
          : "章节还不够，暂未生成记忆存档（继续写几章再试，或先把重要设定写进设定资料）"
      );
    } catch (e) {
      setError(e instanceof Error ? e.message : "记忆归档失败");
    }
  }

  async function openMemoryArchive(archiveId: string) {
    if (!project) return;
    setMemoryDetailBusy(true);
    try {
      const detail = await getChapterMemoryArchive(project.id, archiveId);
      setMemoryDetail(detail);
    } catch (e) {
      setError(e instanceof Error ? e.message : "无法打开记忆归档");
    } finally {
      setMemoryDetailBusy(false);
    }
  }

  async function takeSnapshot() {
    if (!project) return;
    commitEditor();
    const label = snapLabel.trim() || `快照 ${new Date().toLocaleString()}`;
    try {
      const latest = buildLatestProject();
      if (latest) {
        const saved = await putProject(latest.id, latest, latest.updatedAt);
        lastSavedRef.current = saved;
        skipNextProjectSave.current = true;
        setProject(saved);
      }
      await createSnapshot(project.id, label);
      const snaps = await listSnapshots(project.id);
      setSnapshots(snaps);
      setSnapLabel("");
      setStatus(`已保存快照「${label}」`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "快照失败");
    }
  }

  async function restoreSnapshotById(snapId: string) {
    if (!project) return;
    const snap = snapshots.find((s) => s.id === snapId);
    if (!snap) return;
    const ok = await confirm({
      title: `回退到「${snap.label}」？`,
      body: "剧本会回到保存这个快照时的状态；从那时起新增或修改的内容都会被覆盖，无法恢复。",
      danger: true,
      confirmLabel: "确认回退",
    });
    if (!ok) {
      return;
    }
    try {
      const restored = await apiRestoreSnapshot(project.id, snapId);
      skipNextProjectSave.current = true;
      setProject(restored);
      const ch = restored.chapters[0];
      if (ch) {
        setChapterId(ch.id);
        loadEditorFromChapter(ch, restored.characters, writeModeRef.current);
      }
      setStatus(`已回退到「${snap.label}」`);
    } catch (e) {
      setError(e instanceof Error ? e.message : "回退失败");
    }
  }

  async function deleteSnapshotById(snapId: string) {
    if (!project) return;
    try {
      await apiDeleteSnapshot(project.id, snapId);
      setSnapshots((prev) => prev.filter((s) => s.id !== snapId));
      if (compareAgainstId === snapId) setCompareResult(null);
    } catch (e) {
      setError(e instanceof Error ? e.message : "删除快照失败");
    }
  }

  async function compareSnapshotById(snapId: string) {
    if (!project) return;
    commitEditor();
    setCompareBusy(true);
    setCompareAgainstId(snapId);
    setCompareResult(null);
    try {
      const latest = buildLatestProject();
      if (latest) {
        const saved = await putProject(latest.id, latest, latest.updatedAt);
        lastSavedRef.current = saved;
        skipNextProjectSave.current = true;
        setProject(saved);
      }
      const diff = await compareSnapshot(project.id, snapId);
      setCompareResult(diff);
    } catch (e) {
      setError(e instanceof Error ? e.message : "对比失败");
      setCompareAgainstId(null);
    } finally {
      setCompareBusy(false);
    }
  }

  async function createShareLink() {
    if (!project) return;
    commitEditor();
    try {
      const latest = buildLatestProject();
      if (latest) {
        const saved = await putProject(latest.id, latest, latest.updatedAt);
        lastSavedRef.current = saved;
        skipNextProjectSave.current = true;
        setProject(saved);
      }
      const res = await createShare(project.id);
      const url = `${window.location.origin}${res.url}`;
      setShareUrl(url);
      void navigator.clipboard?.writeText(url);
      skipNextProjectSave.current = true;
      setProject((prev) => (prev ? { ...prev, shareId: res.token } : prev));
      setStatus("已生成只读链接并复制到剪贴板");
    } catch (e) {
      setError(e instanceof Error ? e.message : "生成分享失败");
    }
  }

  async function revokeShareLink() {
    if (!project?.shareId) return;
    try {
      await revokeShare(project.id, project.shareId);
      skipNextProjectSave.current = true;
      setProject((prev) => (prev ? { ...prev, shareId: undefined } : prev));
      setShareUrl("");
      setStatus("已撤销分享链接");
    } catch (e) {
      setError(e instanceof Error ? e.message : "撤销失败");
    }
  }

  function downloadRpy() {
    if (!project) return;
    if (!rpyPreview || rpyStale) {
      setError("请先在「项目 → 导出」点击「生成 .rpy」");
      setTab("project");
      setProjectSub("export");
      return;
    }
    downloadText(
      `${project.title || "script"}.rpy`,
      rpyPreview,
      "text/plain;charset=utf-8"
    );
    trackOncePerUser(EVENTS.exportDone, { kind: "rpy_manual" });
    setStatus("已下载 .rpy");
  }

  async function downloadJson() {
    if (!project) return;
    commitEditor();
    try {
      setStatus("导出工程中…");
      setError("");
      const latest = buildLatestProject();
      if (latest) {
        const saved = await putProject(latest.id, latest, latest.updatedAt);
        lastSavedRef.current = saved;
        skipNextProjectSave.current = true;
        setProject(saved);
      }
      const blob = await exportJson(project.id);
      downloadBlob(`${project.title || "project"}.json`, blob);
      setStatus("已下载工程 .json");
    } catch (e) {
      setError(e instanceof Error ? e.message : "导出失败");
      setStatus("");
    }
  }

  async function downloadMarkdown() {
    if (!project) return;
    commitEditor();
    try {
      setStatus("导出 Markdown…");
      setError("");
      const blob = await exportMarkdown(project.id);
      downloadBlob(`${project.title || "project"}.md`, blob);
      setStatus("已下载 Markdown 稿");
    } catch (e) {
      setError(e instanceof Error ? e.message : "导出失败");
      setStatus("");
    }
  }

  async function downloadDocxFile() {
    if (!project) return;
    commitEditor();
    try {
      setStatus("导出 Word…");
      setError("");
      const blob = await exportDocx(project.id);
      downloadBlob(`${project.title || "project"}.docx`, blob);
      setStatus("已下载 Word 稿");
    } catch (e) {
      setError(e instanceof Error ? e.message : "导出失败");
      setStatus("");
    }
  }

  async function downloadRenpyBundle() {
    if (!project) return;
    commitEditor();
    setBundleBusy(true);
    try {
      setStatus("打包 Ren'Py 项目…");
      setError("");
      const blob = await exportRenpyBundle(project.id);
      downloadBlob(`${project.title || "vn"}-renpy.zip`, blob);
      setStatus("已下载 Ren'Py 项目包");
    } catch (e) {
      setError(e instanceof Error ? e.message : "打包失败");
      setStatus("");
    } finally {
      setBundleBusy(false);
    }
  }

  // Fullscreen cannot resume without a gesture; clear sticky flag from older sessions.
  useEffect(() => {
    if (loadFocusMode()) saveFocusMode(false);
  }, []);

  async function exitFocusSession() {
    setFocusMode(false);
    saveFocusMode(false);
    setFocusPrefs(null);
    setFocusSetupOpen(false);
    try {
      await exitFullscreen();
    } catch {
      /* user gesture / browser policy */
    }
  }

  async function startFocusSession(prefs: FocusTimerPrefs) {
    saveFocusTimerPrefs(prefs);
    setFocusPrefs(prefs);
    setFocusSetupOpen(false);
    setFocusMode(true);
    saveFocusMode(true);
    setTab("write");
    setWriteSub("script");
    try {
      await enterFullscreen(shellRef.current ?? document.documentElement);
    } catch {
      setStatus("浏览器拒绝全屏，仍以专注界面继续（可再试一次）");
    }
  }

  function requestFocusSession() {
    if (focusMode) {
      void exitFocusSession();
      return;
    }
    if (tab !== "write" || writeSub !== "script") {
      commitEditor();
      setTab("write");
      setWriteSub("script");
    }
    setFocusSetupOpen(true);
  }

  useEffect(() => {
    function onFsChange() {
      if (!document.fullscreenElement && focusMode) {
        setFocusMode(false);
        saveFocusMode(false);
        setFocusPrefs(null);
      }
    }
    document.addEventListener("fullscreenchange", onFsChange);
    document.addEventListener("webkitfullscreenchange", onFsChange as EventListener);
    return () => {
      document.removeEventListener("fullscreenchange", onFsChange);
      document.removeEventListener(
        "webkitfullscreenchange",
        onFsChange as EventListener
      );
    };
  }, [focusMode]);

  useEffect(() => {
    function onKey(e: KeyboardEvent) {
      if (!(e.ctrlKey || e.metaKey) || e.key !== "\\") return;
      if (tab !== "write" || writeSub !== "script") return;
      e.preventDefault();
      requestFocusSession();
    }
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [focusMode, tab, writeSub]);

  const dismissToast = useCallback(() => {
    setStatus("");
    setError("");
  }, []);

  function handleLogout() {
    void (async () => {
      try {
        await flushPendingSave();
      } catch {
        /* still leave */
      }
      logout();
      navigate("/login", { replace: true });
    })();
  }

  if (bootLoading) {
    return <StudioBootScreen stamp="LOAD" title="加载中" />;
  }

  if (projectsList.length === 0) {
    return (
      <StudioBootScreen
        stamp="LIB"
        title="还没有剧本"
        titleTag="h1"
        lead="先建一个空白工程，或载入示例开场。"
      >
        <EmptyStage stamp="LIB" title="项目库空着" line={mascotLine("emptyLibrary")}>
          <div className={styles.aiQuick}>
            <button type="button" onClick={() => void createBlank()}>
              空白剧本
            </button>
            <button type="button" onClick={() => void createDemo()}>
              示例《雨夜车站》
            </button>
          </div>
          <TemplatePicker onPick={(tid) => void createFromTemplate(tid)} />
        </EmptyStage>
      </StudioBootScreen>
    );
  }

  if (!project || projectLoading) {
    return <StudioBootScreen stamp="LOAD" title="加载中" />;
  }

  const locations = project.locations ?? [];
  const links = project.locationLinks ?? [];
  const bible = project.bible ?? {};
  const toast = classifyStatusToast(status, error);
  const writeQuiet = tab === "write" && writeSub === "script";
  /** 桌面视图：只在用户选了它、且屏幕够宽时显示（窄屏自动回工作台）。 */
  const showDesktop = shouldShowDesktop({ view, width: viewportWidth });

  /**
   * 桌面上的"应用"：每个都是**自己的窗口形态**，不是跳回原界面。
   * 系统设置 / 帮助 / 公告按 Windows 习惯只进开始菜单（onDesktop 不设）。
   */
  const desktopApps: DesktopApp[] = [
    {
      id: "library",
      label: "剧本库",
      glyph: "🗂️",
      // 不放桌面：桌面本身列的就是剧本，这个窗口是"管理全部剧本"的工具（导入/模板/搜索），
      // 跟 Windows 把资源管理器放在开始菜单里一样。
      defaultRect: { x: 120, y: 90, w: 620, h: 460 },
      render: () => (
        <ProjectLibraryPanel
          projectsList={projectsList}
          activeId={project?.id ?? ""}
          renamingId={renamingId}
          renameDraft={renameDraft}
          renameInputRef={renameInputRef}
          onRenameDraftChange={setRenameDraft}
          onStartRename={startRename}
          onCommitRename={() => void commitRename()}
          onCancelRename={cancelRename}
          onOpen={(id) => {
            setDesktopScriptOpen(true);
            if (id !== project?.id) void switchProject(id);
          }}
          onCreateBlank={() => {
            void createBlank();
            setDesktopScriptOpen(true);
          }}
          onCreateDemo={() => void createDemo()}
          onPickTemplate={(tid) => void createFromTemplate(tid)}
          onImportClick={() => fileRef.current?.click()}
          onDuplicate={(id) => void duplicateProjectById(id)}
          onDelete={(id) => void deleteProjectById(id)}
        />
      ),
    },
    {
      id: "agent",
      label: "AI 责编",
      glyph: "🧠",
      onDesktop: true,
      defaultRect: { x: 200, y: 70, w: 620, h: 560 },
      render: () =>
        project ? (
          // 标题写明"正在读哪个剧本"：上下文是后端按当前剧本组装的，
          // 换个剧本就是另一套设定/角色/章节，对话也各自独立（不共享记忆）。
          <div className={styles.scopeWrap}>
            <p className={styles.scopeNote}>
              正在读《{project.title}》· {(project.chapters ?? []).length} 章 ·
              只依据这个剧本的内容回答
            </p>
            <div className={styles.scopeBody}>
              <AgentChat
                project={project}
                chapterId={chapterId}
                selection={selection}
                draft={editor}
                prepareProject={() => buildLatestProject() ?? project}
                onProjectChange={(next) => {
                  applyRemoteProject(next);
                  const ch = next.chapters.find((c) => c.id === chapterId) ?? next.chapters[0];
                  if (ch) {
                    setChapterId(ch.id);
                    loadEditorFromChapter(ch, next.characters, writeModeRef.current);
                  }
                }}
                onChapterFocus={(id) => {
                  setChapterId(id);
                  setTab("write");
                  setWriteSub("script");
                }}
              />
            </div>
          </div>
        ) : (
          <p className={styles.panelNote}>先打开一个剧本，AI 责编才能看到它的上下文。</p>
        ),
    },
    {
      id: "music",
      label: "音乐播放器",
      glyph: "🎵",
      onDesktop: true,
      defaultRect: { x: 320, y: 420, w: 520, h: 260 },
      render: () => <MusicPlayerBar contextLabel={chapter?.title ?? ""} embedded />,
    },
    {
      id: "pet",
      label: "桌宠",
      glyph: "🐾",
      onDesktop: true,
      defaultRect: { x: 420, y: 160, w: 380, h: 240 },
      render: () => <DeskPetApp />,
    },
    {
      id: "settings",
      label: "系统设置",
      glyph: "⚙️",
      defaultRect: { x: 160, y: 60, w: 720, h: 560 },
      render: () =>
        settings ? (
          <SettingsModal
            embedded
            open
            onClose={() => {}}
            settings={settings}
            onChange={setSettings}
            view={view}
            onViewChange={(next) => {
              setView(next);
              saveWorkspace({ view: next });
            }}
          />
        ) : null,
    },
    {
      id: "help",
      label: "帮助 / FAQ",
      glyph: "❓",
      defaultRect: { x: 220, y: 80, w: 680, h: 520 },
      render: () => <HelpSheet embedded open onClose={() => {}} />,
    },
    {
      id: "notice",
      label: "更新公告",
      glyph: "📢",
      run: () => openNotice(),
    },
    {
      id: "assets",
      label: "素材与体检",
      glyph: "🧩",
      defaultRect: { x: 260, y: 110, w: 680, h: 520 },
      render: () =>
        project ? (
          <AssetAuditPanel projectId={project.id} />
        ) : (
          <p className={styles.panelNote}>先打开一个剧本才能体检素材。</p>
        ),
    },
  ];

  /** 从桌面进入某个工作台页签（只有"切换为工作台视图"用得上）。 */
  function exitDesktopTo(nextTab?: Tab, sub?: WorkspaceSnapshot["projectSub"]) {
    setView("studio");
    saveWorkspace({ view: "studio" });
    if (nextTab) setTab(nextTab);
    if (sub) setProjectSub(sub);
  }

  return (
    <>
      <PwaInstallPrompt />
      {tourOpen && project && (
        <OnboardingOverlay onDone={() => setTourOpen(false)} />
      )}
      {/* 桌面视图：图标是"快捷方式"，双击剧本 = 打开**这个剧本自己的窗口**（不是跳走） */}
      {showDesktop ? (
        <DesktopView
          username={user?.username}
          projects={projectsList.map((p) => ({
            id: p.id,
            title: p.title,
            chapters: p.chapters_count,
            updatedAt: p.updated_at,
          }))}
          activeProjectId={project?.id}
          activeProjectTitle={project?.title}
          scriptOpen={desktopScriptOpen}
          onCloseScript={() => setDesktopScriptOpen(false)}
          onScriptMinimize={() => setDesktopScriptOpen(false)}
          onSwitchToStudioView={() => exitDesktopTo()}
          onLogout={() => {
            // 注销回登录页，并重新武装开机画面（"重启"的感觉）
            rearmBoot();
            handleLogout();
          }}
          onOpenProject={(id: string) => {
            // 双击剧本 = 在桌面上打开这个剧本的工作台窗口（写作页/设定/角色/地图/剧情状态）
            setDesktopScriptOpen(true);
            if (id !== project?.id) void switchProject(id);
          }}
          onNewProject={() => {
            void createBlank();
            setDesktopScriptOpen(true);
          }}
          onRenameProject={(id) => {
            const target = projectsList.find((p) => p.id === id);
            void prompt({
              title: "重命名剧本",
              defaultValue: target?.title ?? "",
              confirmLabel: "保存",
            }).then((next) => {
              if (next !== null) void renameProjectById(id, next);
            });
          }}
          onDuplicateProject={(id) => void duplicateProjectById(id)}
          onDeleteProject={(id) => void deleteProjectById(id)}
          scriptTabs={STUDIO_TABS.map(([id, , label]) => ({ id, label }))}
          onOpenScriptTab={(id) => {
            // 从桌面直接进这个剧本的某一页（设定 / 角色工坊 / 地图 / 剧情状态…）
            if (id !== "write" || writeSub !== "script") commitEditor();
            setTab(id as Tab);
            setDesktopScriptOpen(true);
          }}
          openAppRequest={{ id: "agent", nonce: desktopAppTick }}
          resume={
            project
              ? {
                  projectTitle: project.title,
                  chapterLabel: (() => {
                    const i = (project.chapters ?? []).findIndex((c) => c.id === chapterId);
                    const ch = i >= 0 ? project.chapters[i] : undefined;
                    const name = ch?.title?.trim() || (i >= 0 ? `第 ${i + 1} 章` : "第 1 章");
                    return name;
                  })(),
                }
              : undefined
          }
          onResume={() => setDesktopScriptOpen(true)}
          apps={desktopApps}
        />
      ) : null}
      <QPet editorRef={editorTaRef} cheerSignal={petCheer} />
      <ClickFx />
      {/* 全局底部音乐条：工作台里常驻；桌面视图里音乐是"应用窗口"，就不再叠一条 */}
      {!showDesktop ? <MusicPlayerBar contextLabel={chapter?.title ?? ""} /> : null}
      {playOpen && project && chapter && (
        <ScriptPlayer
          chapter={chapter}
          characters={project.characters ?? []}
          projectTitle={project.title}
          variables={project.variables ?? []}
          onExit={() => setPlayOpen(false)}
        />
      )}
      <SaveConflictDialog
        open={Boolean(saveConflict)}
        localTitle={saveConflict?.local.title}
        serverUpdatedAt={saveConflict?.serverUpdatedAt}
        onChoose={(c) => {
          void resolveSaveConflict(c);
        }}
      />
      {settings?.bgImage ? (
        <>
          <div className="vnss-wallpaper" aria-hidden />
          <div className="vnss-wallpaper-scrim" aria-hidden />
          <div className="vnss-grain" aria-hidden />
        </>
      ) : null}
      <div
        ref={shellRef}
        className={`vnss-app ${styles.shell} ${
          tab === "write" && writeSub === "script" ? styles.writeQuiet : ""
        } ${
          tab === "write" && writeSub === "script" && focusMode ? styles.focusMode : ""
        } ${tab !== "write" ? styles.menuStage : ""} ${
          showDesktop && !desktopScriptOpen ? styles.shellHidden : ""
        } ${showDesktop && desktopScriptOpen ? styles.shellUnderDesktop : ""}`}
        aria-hidden={showDesktop && !desktopScriptOpen ? true : undefined}
      >
        <FocusChrome
          setupOpen={focusSetupOpen}
          initialPrefs={focusInitialPrefs}
          onSetupCancel={() => setFocusSetupOpen(false)}
          onSetupConfirm={(prefs) => void startFocusSession(prefs)}
          active={Boolean(focusMode && tab === "write" && writeSub === "script")}
          prefs={focusPrefs}
          draft={editor}
          onExit={() => void exitFocusSession()}
        />
        {toast ? (
          <StatusToast
            message={toast.message}
            kind={toast.kind}
            quiet={writeQuiet && toast.kind !== "error"}
            onDismiss={dismissToast}
          />
        ) : null}
        <StudioTopBar
          title={project.title}
          username={user?.username}
          showFocusToggle={tab === "write" && writeSub === "script" && !focusMode}
          showAgent={!focusMode}
          onOpenAgent={() => {
            // 桌面视角没有浮窗：顶栏「审稿」改成打开桌面上的「AI 责编」窗口
            if (showDesktop) setDesktopAppTick((t) => t + 1);
            else setAgentOpenTick((t) => t + 1);
          }}
          fileInputRef={fileRef}
          onTitleChange={(value) => updateActive((p) => ({ ...p, title: value }))}
          onFocusToggle={requestFocusSession}
          onNewProject={() => void createBlank()}
          onImportClick={() => fileRef.current?.click()}
          onFileChange={(e) => {
            const f = e.target.files?.[0];
            if (f) void handleImportFile(f);
            e.target.value = "";
          }}
          onSaveChapter={commitEditor}
          onExport={() => void exportCurrentView()}
          exportLabel={writeMode === "rpy" ? "导出 .rpy" : "导出 .docx"}
          onOpenHelp={() => setHelpOpen(true)}
          onOpenAdmin={() => setAdminOpen(true)}
          showAdmin={Boolean(user?.is_admin || adminCapable)}
          adminAlert={adminAlert}
          onOpenCollab={() => {
            setTab("project");
            setProjectSub("members");
          }}
          onLogout={handleLogout}
        />

        <div className={styles.layout}>
          <main
            className={`${styles.main} ${
              tabIndex(tab) > prevTabIndexRef.current
                ? styles.tabSlideR
                : styles.tabSlideL
            }`}
            key={tab}
          >
            <StudioTabs
              tab={tab}
              onSelect={(id) => {
                if (id !== "write" || writeSub !== "script") commitEditor();
                prevTabIndexRef.current = tabIndex(tab);
                setTab(id);
              }}
            />

            {tab === "project" && (
              <section className={styles.panel}>
                <div className={styles.subNav}>
                  {(
                    [
                      ["library", "剧本库"],
                      ["ledger", "账本 / 摘要"],
                      ["stats", "写作统计"],
                      ["analysis", "结构分析"],
                      ["assets", "素材"],
                      ["localization", "本地化"],
                      ["export", "导出"],
                      ["history", "快照 / 分享"],
                      ["members", "成员"],
                    ] as const
                  )
                    // 桌面视图里这个窗口只属于当前剧本，"剧本库"（列出全部剧本、切来切去）
                    // 不该出现在这里：桌面上双击哪个就是哪个，右键能重命名/复制/删除。
                    .filter(([id]) => !(showDesktop && id === "library"))
                    .map(([id, label]) => (
                    <button
                      key={id}
                      type="button"
                      className={projectSub === id ? styles.subActive : styles.subTab}
                      onClick={() => setProjectSub(id)}
                    >
                      {label}
                    </button>
                  ))}
                </div>

                {projectSub === "library" && showDesktop && (
                  <p className={styles.panelNote}>
                    桌面视图里不再重复"剧本库"这一页 —— 剧本就在桌面上：双击打开，
                    右键可以重命名 / 复制 / 删除。要导入、用模板或管理全部剧本，
                    从开始菜单打开「剧本库」窗口。
                  </p>
                )}

                {projectSub === "library" && !showDesktop && project && (
                  <ProjectLibraryPanel
                    projectsList={projectsList}
                    activeId={project.id}
                    renamingId={renamingId}
                    renameDraft={renameDraft}
                    renameInputRef={renameInputRef}
                    onRenameDraftChange={setRenameDraft}
                    onStartRename={startRename}
                    onCommitRename={() => void commitRename()}
                    onCancelRename={cancelRename}
                    onOpen={(id) => void switchProject(id)}
                    onCreateBlank={() => void createBlank()}
                    onCreateDemo={() => void createDemo()}
                    onPickTemplate={(tid) => void createFromTemplate(tid)}
                    onImportClick={() => fileRef.current?.click()}
                    onDuplicate={(id) => void duplicateProjectById(id)}
                    onDelete={(id) => void deleteProjectById(id)}
                  />
                )}

                {projectSub === "ledger" && project && (
                  <ProjectLedgerPanel
                    project={project}
                    onOpenChapter={(id) => {
                      setChapterId(id);
                      setTab("write");
                    }}
                  />
                )}

                {projectSub === "stats" && project && (
                  <WritingStatsPanel projectId={project.id} />
                )}

                {projectSub === "analysis" && project && (
                  <AnalysisPanels
                    project={project}
                    chapterId={chapterId}
                    draft={editor}
                    onChange={updateActive}
                    onRemoteProject={applyRemoteProject}
                  />
                )}

                {projectSub === "assets" && project && (
                  <AssetAuditPanel
                    projectId={project.id}
                    onOpenChapter={(id) => {
                      setChapterId(id);
                      setTab("write");
                    }}
                  />
                )}

                {projectSub === "localization" && project && (
                  <LocalizationPanel
                    projectId={project.id}
                    chapters={project.chapters ?? []}
                  />
                )}

                {projectSub === "export" && (
                  <ProjectExportPanel
                    rpyPreview={rpyPreview}
                    rpyStale={rpyStale}
                    onGenerateRpy={() => void generateRpy()}
                    onDownloadRpy={downloadRpy}
                    onDownloadJson={() => void downloadJson()}
                    onDownloadMarkdown={() => void downloadMarkdown()}
                    onDownloadDocx={() => void downloadDocxFile()}
                    onDownloadBundle={() => void downloadRenpyBundle()}
                    bundleBusy={bundleBusy}
                  />
                )}

                {projectSub === "history" && (
                  <ProjectHistoryPanel
                    memoryArchives={memoryArchives}
                    memoryDetailBusy={memoryDetailBusy}
                    memoryDetail={memoryDetail}
                    snapLabel={snapLabel}
                    snapshots={snapshots}
                    compareBusy={compareBusy}
                    compareResult={compareResult}
                    compareAgainstId={compareAgainstId}
                    shareUrl={shareUrl}
                    hasShare={Boolean(project.shareId)}
                    onArchiveMemory={() => void archiveLongMemory()}
                    onOpenMemoryArchive={(id) => void openMemoryArchive(id)}
                    onCloseMemoryDetail={() => setMemoryDetail(null)}
                    onSnapLabelChange={setSnapLabel}
                    onTakeSnapshot={() => void takeSnapshot()}
                    onRestoreSnapshot={(id) => void restoreSnapshotById(id)}
                    onDeleteSnapshot={(id) => void deleteSnapshotById(id)}
                    onCompareSnapshot={(id) => void compareSnapshotById(id)}
                    onCloseCompare={() => {
                      setCompareResult(null);
                      setCompareAgainstId(null);
                    }}
                    onCreateShare={() => void createShareLink()}
                    onRevokeShare={() => void revokeShareLink()}
                  />
                )}

                {projectSub === "members" && project && (
                  <CollabPanel projectId={project.id} />
                )}
              </section>
            )}

            {tab === "write" && (
              <>
                {otherLock || collabNote ? (
                  <div className={styles.collabNote} role="status">
                    {otherLock
                      ? `${otherLock.username} 正在编辑本章（锁至 ${new Date(
                          otherLock.expiresAt
                        ).toLocaleTimeString()}）`
                      : collabNote}
                  </div>
                ) : null}
                <StudioChapterBar
                  writeSub={writeSub}
                  chapterId={chapterId}
                  chapters={project.chapters}
                  onSelectScript={() => setWriteSub("script")}
                  onSelectAnalysis={() => {
                    void (async () => {
                      commitEditor();
                      await flushPendingSave();
                      setWriteSub("analysis");
                    })();
                  }}
                  onSelectChapter={(id) => {
                    if (id === chapterId) return;
                    // 切章前先记住这一章停在哪（切换后就读不到旧光标了）
                    rememberCaretNow();
                    commitEditor();
                    setChapterId(id);
                  }}
                  onAddChapter={() => void addChapter()}
                  onDeleteChapter={() => void deleteChapter(chapterId)}
                />
                {writeSub === "script" && memAuto ? (
                  <div className={styles.collabNote} role="status">
                    已自动记住前 {memAuto.rangeTo} 章要点（AI 续写时会参考；长篇前情不容易丢）。
                    <button
                      type="button"
                      className={styles.hintInline}
                      onClick={() => {
                        setTab("project");
                        setProjectSub("history");
                      }}
                    >
                      查看 / 修改记忆
                    </button>
                  </div>
                ) : null}
                {writeSub === "script" && (
                  <FirstRunChecklist
                    hasContent={Boolean((chapter?.prose || editor || "").trim().length > 20)}
                    onOpenAgent={() => {
                      if (showDesktop) setDesktopAppTick((t) => t + 1);
                      else setAgentOpenTick((t) => t + 1);
                    }}
                    onGenerateRpy={() => {
                      setTab("project");
                      setProjectSub("export");
                      void generateRpyFromManuscript();
                    }}
                    onExport={() => void exportCurrentView()}
                    onStep={(step) =>
                      trackOncePerUser(`onboarding_${step}`, { step })
                    }
                  />
                )}
                {writeSub === "script" && (
                  <section className={styles.panel}>
                    <WriteToolbar
                      chapterTitle={chapter?.title ?? ""}
                      writeMode={writeMode}
                      rpyStale={rpyIsStale({
                        prose: writeMode === "prose" ? editor : chapter?.prose,
                        rpyFromProseHash: chapter?.rpyFromProseHash,
                      })}
                      generating={generatingRpy}
                      showReviseActions={Boolean(reviseDraft)}
                      onWriteModeChange={switchWriteMode}
                      onGenerateRpy={() => void generateRpyFromManuscript()}
                      onChapterTitleChange={(title) => {
                        updateActive((p) => ({
                          ...p,
                          chapters: p.chapters.map((c) =>
                            c.id === chapterId ? { ...c, title } : c
                          ),
                        }));
                      }}
                      onOpenRevise={() => {
                        if (focusMode) {
                          setStatus("请先退出专注模式，再打开改稿对照");
                          return;
                        }
                        requestOpenReviseReview(project.id, chapterId);
                      }}
                      onDiscardRevise={() => {
                        clearChapterReviseDraft(project.id, chapterId);
                        setReviseDraft(null);
                        setStatus("已放弃这次改稿的对照预览。正文保持原样，没有做任何改动。");
                      }}
                      onDictateInsert={(text) => {
                        // Insert transcript at the editor caret; fall back to append.
                        const ta = editorTaRef.current;
                        let next = editorRef.current;
                        if (ta && ta.selectionStart !== null && ta.selectionEnd !== null) {
                          const pos = ta.selectionStart;
                          next =
                            next.slice(0, pos) + text + next.slice(ta.selectionEnd);
                        } else {
                          next = next ? `${next}\n${text}` : text;
                        }
                        editorRef.current = next;
                        setEditor(next);
                        if (rpyPreview) setRpyStale(true);
                        scheduleEditorCommit();
                        setStatus("已插入语音转写");
                      }}
                    />
                    <StudioErrorBoundary label="写作编辑器">
                      {/* 「上次停在这里」：不自动跳光标，给一个可以点的入口（长章节才有用） */}
                      {caretHint !== null ? (
                        <div className={styles.caretHint} data-testid="caret-hint">
                          <button
                            type="button"
                            className={styles.caretHintBtn}
                            data-testid="caret-hint-jump"
                            onClick={jumpToLastCaret}
                            title="把光标放回上次停笔的地方，并滚到那一行"
                          >
                            ↩ 上次停在这里
                          </button>
                          <button
                            type="button"
                            className={styles.caretHintClose}
                            aria-label="忽略这次标记"
                            onClick={() => setCaretHint(null)}
                          >
                            ×
                          </button>
                        </div>
                      ) : null}
                      <ScriptEditor
                        textareaRef={editorTaRef}
                        frameClassName={styles.scriptEditor}
                        value={editor}
                        locations={project.locations ?? []}
                        marks={markRanges}
                        anchorOffset={activeMarkOffset}
                        overlay={
                          activeMark ? (
                            <MarkCard
                              mark={activeMark}
                              index={Math.max(
                                0,
                                marks.findIndex((m) => m.id === activeMark.id)
                              )}
                              total={marks.length}
                              busy={markBusyId === activeMark.id}
                              hasStyleMemory={hasStyleMemory}
                              onProcess={() => void processMark(activeMark.id)}
                              onAccept={(edited) => acceptMark(activeMark.id, edited)}
                              onReject={() =>
                                setMarks((prev) =>
                                  prev.map((m) =>
                                    m.id === activeMark.id ? { ...m, status: "rejected" } : m
                                  )
                                )
                              }
                              onRevert={() => revertMarkChange(activeMark.id)}
                              onClose={() => setActiveMarkId(null)}
                              onPrev={() => {
                                const i = marks.findIndex((m) => m.id === activeMark.id);
                                const prev = marks[i - 1];
                                if (prev) selectMark(prev.id);
                              }}
                              onNext={() => {
                                const i = marks.findIndex((m) => m.id === activeMark.id);
                                const next = marks[i + 1];
                                if (next) selectMark(next.id);
                              }}
                              onRemove={() => removeMark(activeMark.id)}
                              onInstruction={(value) => setMarkInstruction(activeMark.id, value)}
                              onIntent={(intent) => setMarkIntent(activeMark.id, intent)}
                              onJump={() => selectMark(activeMark.id)}
                            />
                          ) : null
                        }
                        onPlaceClick={(locationId, label) => {
                          commitEditor();
                          setMapFocus({ id: locationId, tick: Date.now() });
                          setTab("map");
                          setStatus(`已在地图定位「${label}」`);
                        }}
                        placeholder={
                          writeMode === "prose"
                            ? "用自然语言写剧本。旁白直接写，对白写成「林夏：……」"
                            : 'Ren\'Py：旁白用 "……"，对白用 角色名 "台词"'
                        }
                        onChange={(next) => {
                          editorRef.current = next;
                          setEditor(next);
                          if (rpyPreview) setRpyStale(true);
                          // 人一动手写，"上次停在这里"就没意义了，收起来
                          setCaretHint(null);
                          // 正文一变就重新校验标记：被标记的那段没了 → 标成"已失效"
                          setMarks((prev) => (prev.length ? refreshMarks(next, prev) : prev));
                          scheduleEditorCommit();
                        }}
                        onBlur={rememberCaretNow}
                        onKeyDown={(e) => {
                          // Ctrl/Cmd+M：把选中的这段标成"要改"（标记批改的快捷键）
                          if ((e.ctrlKey || e.metaKey) && (e.key === "m" || e.key === "M")) {
                            e.preventDefault();
                            markSelection();
                          }
                        }}
                        onSelect={(e) => {
                          const t = e.currentTarget;
                          setSelection(t.value.slice(t.selectionStart, t.selectionEnd));
                        }}
                      />
                      {writeMode === "rpy" ? (
                        <ScriptCommandBar
                          characters={project.characters ?? []}
                          sprites={project.sprites ?? []}
                          variables={project.variables ?? []}
                          onInsert={(payload) => {
                            // 按**行边界**插入：光标在同一行中间时也不会把指令粘到
                            // `show ...` 后面（用户反馈过这个 bug）。
                            const ta = editorTaRef.current;
                            const cur = editorRef.current ?? "";
                            const pos =
                              ta && ta.selectionStart !== null
                                ? ta.selectionStart
                                : cur.length;
                            const { text: next, caret } = insertCommandAtLine(
                              cur,
                              payload,
                              pos,
                              ta?.selectionEnd ?? undefined
                            );
                            editorRef.current = next;
                            setEditor(next);
                            if (rpyPreview) setRpyStale(true);
                            scheduleEditorCommit();
                            window.requestAnimationFrame(() => {
                              const el = editorTaRef.current;
                              if (!el) return;
                              el.focus();
                              el.setSelectionRange(caret, caret);
                            });
                          }}
                        />
                      ) : null}
                    </StudioErrorBoundary>
                    <MarksPanel
                      marks={marks}
                      activeId={activeMarkId}
                      busyId={markBusyId}
                      progress={markProgress}
                      hasStyleMemory={hasStyleMemory}
                      selectionLength={selection.length}
                      onMarkSelection={markSelection}
                      onProcessAll={() => void processAllMarks()}
                      onStop={() => {
                        markStopRef.current = true;
                      }}
                      onSelect={selectMark}
                      onRemove={removeMark}
                    />
                    <CommentsPanel
                      projectId={project.id}
                      chapterId={chapterId}
                      chapterTitle={chapter?.title ?? ""}
                      myUserId={myUserId}
                    />
                    <div className={styles.aiQuick} style={{ marginTop: "0.9rem" }}>
                      <button
                        type="button"
                        className={styles.primary}
                        onClick={() => {
                          commitEditor();
                          const latest = buildLatestProject();
                          const ch =
                            latest?.chapters.find((c) => c.id === chapterId) ??
                            chapter;
                          const playable = (ch?.blocks ?? []).some(
                            (b) =>
                              b.type === "dialogue" ||
                              b.type === "narration" ||
                              b.type === "menu"
                          );
                          if (!playable) {
                            setError(
                              "试玩需要先有一份可运行的脚本。请点「根据剧本生成」，把本章正文转成可试玩脚本后再点「试玩本章」；想自己改也可以切到脚本模式手动调整。"
                            );
                            persistWriteMode("rpy");
                            if (ch) {
                              loadEditorFromChapter(ch, project.characters, "rpy");
                            }
                            return;
                          }
                          setPlayOpen(true);
                          trackOncePerUser(EVENTS.playtestOpened, {});
                        }}
                        title="以视觉小说方式试玩当前章节（分支/选项可点）"
                      >
                        ▶ 试玩本章
                      </button>
                    </div>
                  </section>
                )}
                {writeSub === "analysis" && (
                  <section className={styles.panel}>
                    <AnalysisPanels
                      project={project}
                      chapterId={chapterId}
                      draft={editor}
                      onChange={updateActive}
                      onRemoteProject={applyRemoteProject}
                    />
                  </section>
                )}
              </>
            )}

            {tab === "world" && (
              <WorldPanel
                worldSub={worldSub}
                projectId={project.id}
                characters={project.characters}
                logline={project.logline ?? ""}
                genre={project.genre ?? ""}
                bible={bible}
                loreEntries={project.loreEntries ?? []}
                onSelectCharacters={() => setWorldSub("characters")}
                onSelectBible={() => setWorldSub("bible")}
                onSelectLore={() => setWorldSub("lore")}
                onSelectEntries={() => setWorldSub("entries")}
                onAddCharacter={addCharacter}
                onDeleteCharacter={(id) => void deleteCharacter(id)}
                onUpdateCharacter={updateCharacter}
                onLoreEntriesChange={(next) =>
                  updateActive((p) => ({ ...p, loreEntries: next }))
                }
                onLoglineChange={(value) =>
                  updateActive((p) => ({ ...p, logline: value }))
                }
                onGenreChange={(value) => updateActive((p) => ({ ...p, genre: value }))}
                onBibleChange={updateBible}
              />
            )}

            {tab === "voice" && (
              <CharacterWorkshop
                project={project}
                onProjectChange={(next) => {
                  replaceActiveProject(normalizeProject(next));
                }}
              />
            )}

            {tab === "map" && (
              <section className={styles.panel}>
                <MapStudio
                  locations={locations}
                  links={links}
                  chapters={project.chapters}
                  customElements={project.customMapElements ?? []}
                  strokes={project.mapStrokes ?? []}
                  focusLocationId={mapFocus?.id ?? null}
                  focusTick={mapFocus?.tick ?? 0}
                  onChangeLocations={(locs) =>
                    updateActive((p) => ({ ...p, locations: locs }))
                  }
                  onChangeLinks={(nextLinks) =>
                    updateActive((p) => ({ ...p, locationLinks: nextLinks }))
                  }
                  onChangeCustomElements={(customMapElements) =>
                    updateActive((p) => ({ ...p, customMapElements }))
                  }
                  onChangeStrokes={(mapStrokes) =>
                    updateActive((p) => ({ ...p, mapStrokes }))
                  }
                  onJumpToChapter={(id, blockIndex) => {
                    commitEditor();
                    if (typeof blockIndex === "number") {
                      persistWriteMode("rpy");
                      pendingEditorFocus.current = { chapterId: id, blockIndex };
                      setEditorFocusNonce((n) => n + 1);
                      if (id === chapterId) {
                        const ch = project.chapters.find((c) => c.id === id);
                        if (ch) {
                          loadEditorFromChapter(ch, project.characters, "rpy");
                        }
                      }
                    } else {
                      pendingEditorFocus.current = null;
                    }
                    setChapterId(id);
                    saveWorkspace({
                      projectId: project.id,
                      chapterId: id,
                      tab: "write",
                      writeSub: "script",
                    });
                    setTab("write");
                    setWriteSub("script");
                  }}
                  onExtractFromScript={() => void extractLocs("smart")}
                  onExtractRulesOnly={() => void extractLocs("rules")}
                />
              </section>
            )}

            {tab === "system" && (
              <SystemPanel
                project={project}
                onChange={updateActive}
                sub={systemSub}
                onSub={setSystemSub}
              />
            )}
          </main>
        </div>

        {/* AI 责编：桌面视角下它已经是桌面上的一个"应用窗口"，就不再叠一个浮动面板
            （同一功能两套 UI 只会让人不知道该点哪个，浮窗还会压住编辑器）。 */}
        {!focusMode && !showDesktop ? (
          <StudioErrorBoundary label="审稿 Agent">
            <AgentFloat
              project={project}
              chapterId={chapterId}
              selection={selection}
              draft={editor}
              openRequest={agentOpenTick}
              prepareProject={() => buildLatestProject() ?? project}
              onProjectChange={(p) => {
                applyRemoteProject(p);
                const ch = p.chapters.find((c) => c.id === chapterId) ?? p.chapters[0];
                if (ch) {
                  setChapterId(ch.id);
                  loadEditorFromChapter(ch, p.characters, writeModeRef.current);
                }
              }}
              onChapterFocus={(id) => {
                setChapterId(id);
                setTab("write");
                setWriteSub("script");
              }}
            />
          </StudioErrorBoundary>
        ) : null}

        {/* 悬浮设置齿轮：桌面视角里不画 —— 开始菜单里就有「系统设置」，
            而且它固定浮在左下角会压在任务栏上方挡着工作台（用户反馈过"底下的设置"）。 */}
        {!focusMode && !showDesktop ? (
          <SettingsGear onClick={() => setSettingsOpen(true)} />
        ) : null}
        {settings && (
          <SettingsModal
            open={settingsOpen}
            onClose={() => setSettingsOpen(false)}
            settings={settings}
            onChange={setSettings}
            view={view}
            onViewChange={(next) => {
              setView(next);
              saveWorkspace({ view: next });
              // 切到桌面时顺手关掉设置，否则弹窗会盖在"桌面"上
              if (next === "desktop") setSettingsOpen(false);
            }}
          />
        )}
        <HelpSheet open={helpOpen} onClose={() => setHelpOpen(false)} />
        <AdminPanel open={adminOpen} onClose={() => setAdminOpen(false)} />
        {mapExtractReview ? (
          <MapExtractReview
            proposal={mapExtractReview.proposal}
            warnings={mapExtractReview.warnings}
            modeLabel={mapExtractReview.modeLabel}
            busy={mapExtractBusy}
            onCancel={() => {
              if (mapExtractBusy) return;
              setMapExtractReview(null);
              setStatus("已取消写入地图候选");
            }}
            onConfirm={(placeIds, linkIds) => {
              void confirmMapExtract(placeIds, linkIds);
            }}
          />
        ) : null}
        {/* 页脚（使用指南 / 备案号）：工作台视图里底部音乐条是 fixed 的，会盖住它，
            所以这里给它让出音乐条的高度；桌面视角没有音乐条，也就不要那段空白。 */}
        <div className={!showDesktop && musicBarOn ? styles.footerLift : undefined}>
          <FilingFooter />
        </div>
      </div>
    </>
  );
}
