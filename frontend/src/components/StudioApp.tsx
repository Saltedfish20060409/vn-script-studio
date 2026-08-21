import { useCallback, useEffect, useMemo, useRef, useState } from "react";
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
  getProject,
  getSettings,
  importProjectFile,
  listChapterMemory,
  listProjects,
  listSnapshots,
  mapExtract,
  mapExtractAccept,
  patchProject,
  putProject,
  putSettings,
  restoreSnapshot as apiRestoreSnapshot,
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
import { useConfirm, usePrompt } from "../lib/confirmDialog";
import { EmptyStage } from "./EmptyStage";
import { ProjectLibraryPanel } from "./ProjectLibraryPanel";
import { CollabPanel } from "./CollabPanel";
import { CommentsPanel } from "./CommentsPanel";
import { PwaInstallPrompt } from "./PwaInstallPrompt";
import { ProjectExportPanel } from "./ProjectExportPanel";
import { ProjectHistoryPanel } from "./ProjectHistoryPanel";
import { WritingStatsPanel } from "./WritingStatsPanel";
import { StudioBootScreen } from "./StudioBootScreen";
import { StudioChapterBar } from "./StudioChapterBar";
import { StudioTabs } from "./StudioTabs";
import { StudioTopBar } from "./StudioTopBar";
import { TemplatePicker } from "./TemplatePicker";
import { OnboardingOverlay } from "./OnboardingOverlay";
import { hasSeenTour } from "../lib/onboarding";
import { QPet } from "./QPet";
import { WorldPanel } from "./WorldPanel";
import { WriteToolbar, type WriteMode } from "./WriteToolbar";
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
import { blockTextRange, blocksToEditable, editableToBlocks } from "../lib/scriptCodec";
import { chapterProse, proseFingerprint, rpyIsStale } from "../lib/scriptProse";
import { normalizeProject } from "../lib/vnLocal";
import { diffProjectAgainst } from "../lib/projectDiff";
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
  const prompt = usePrompt();
  const cachedWs = useMemo(() => loadWorkspace(), []);
  const wsDefaults = workspaceDefaults();

  const [bootLoading, setBootLoading] = useState(true);
  const [projectsList, setProjectsList] = useState<ProjectSummary[]>([]);
  const [project, setProject] = useState<VnProject | null>(null);
  const [projectLoading, setProjectLoading] = useState(false);
  /** Collaboration: chapter lock held by another member + live member/lock events. */
  const [activeLocks, setActiveLocks] = useState<ChapterLockInfo[]>([]);
  const [collabNote, setCollabNote] = useState("");
  const myUserId = user?.id ?? "";

  const [tab, setTab] = useState<Tab>((cachedWs.tab as Tab) || wsDefaults.tab);
  const [writeSub, setWriteSub] = useState<"script" | "analysis">(
    cachedWs.writeSub || wsDefaults.writeSub
  );
  const [worldSub, setWorldSub] = useState<"characters" | "bible" | "lore">(
    cachedWs.worldSub || wsDefaults.worldSub
  );
  const [systemSub, setSystemSub] = useState<"variables" | "sprites">(
    cachedWs.systemSub || wsDefaults.systemSub
  );
  const [projectSub, setProjectSub] = useState<
    "library" | "stats" | "analysis" | "export" | "history" | "members"
  >(cachedWs.projectSub || wsDefaults.projectSub);
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
  const [focusSetupOpen, setFocusSetupOpen] = useState(false);
  const [focusPrefs, setFocusPrefs] = useState<FocusTimerPrefs | null>(null);
  const shellRef = useRef<HTMLDivElement>(null);

  const fileRef = useRef<HTMLInputElement>(null);
  const renameInputRef = useRef<HTMLInputElement>(null);

  const editorRef = useRef("");
  const editorTaRef = useRef<HTMLTextAreaElement | null>(null);
  const pendingEditorFocus = useRef<{
    chapterId: string;
    blockIndex: number;
  } | null>(null);
  const [editorFocusNonce, setEditorFocusNonce] = useState(0);
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
  useEffect(() => {
    if (!project || !chapterId) return;
    const ch = project.chapters.find((c) => c.id === chapterId);
    if (!ch) return;
    loadEditorFromChapter(ch, project.characters, writeModeRef.current);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project?.id, chapterId]);

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
  useEffect(() => {
    const onHide = () => {
      if (document.visibilityState === "hidden") {
        void flushPendingSave();
      }
    };
    const onUnload = () => {
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
        setStatus("发现版本冲突 — 请选择保留本地或使用服务器");
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
      setStatus("已下载本地稿 JSON，冲突对话框仍打开");
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
      setError("先写一点自然语言剧本，再生成 RPY。");
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
      setStatus(out.usedLlm ? "已根据剧本生成 RPY" : "已按规则把剧本转成 RPY（未走模型）");
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
      } else {
        const blob = await exportDocx(latest.id);
        downloadBlob(`${latest.title || "script"}.docx`, blob);
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
      body: "云端工程将被移除，此操作不可从列表撤销。",
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

  async function commitRename() {
    if (!renamingId) return;
    const title = renameDraft.trim() || "未命名剧本";
    const id = renamingId;
    setRenamingId(null);
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
      body: "剧本中相关对白不会自动改写，需手动处理残留指称。",
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
      body: "章节正文将一并移除，请确认已不需要此稿。",
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
      setStatus(mode === "smart" ? "智能提取地图中…" : "按 scene 提取中…");
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
          `未发现新地点或通路。可在剧本写 scene bg xxx，或在对白/设定中出现明确场所。${warn}`
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
            : "仅 scene",
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
      setStatus("正在按章节切片归档长程记忆…");
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
          ? `长程记忆已归档：${result.count} 段（最新 ${result.latestLabel}），Agent 续写会自动读取`
          : "章节不足，未生成归档（可勾选不完整段或继续写章）"
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
      body: "当前未快照的改动会丢失。",
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

  return (
    <>
      <PwaInstallPrompt />
      {tourOpen && project && (
        <OnboardingOverlay onDone={() => setTourOpen(false)} />
      )}
      <QPet editorRef={editorTaRef} cheerSignal={petCheer} />
      {playOpen && project && chapter && (
        <ScriptPlayer
          chapter={chapter}
          characters={project.characters ?? []}
          projectTitle={project.title}
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
        } ${tab !== "write" ? styles.menuStage : ""}`}
      >
        <FocusChrome
          setupOpen={focusSetupOpen}
          initialPrefs={loadFocusTimerPrefs()}
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
          onOpenCollab={() => {
            setTab("project");
            setProjectSub("members");
          }}
          onLogout={handleLogout}
        />

        <div className={styles.layout}>
          <main className={`${styles.main} vnss-rise-in`} key={tab}>
            <StudioTabs
              tab={tab}
              onSelect={(id) => {
                if (id !== "write" || writeSub !== "script") commitEditor();
                setTab(id);
              }}
            />

            {tab === "project" && (
              <section className={styles.panel}>
                <div className={styles.subNav}>
                  {(
                    [
                      ["library", "剧本库"],
                      ["stats", "写作统计"],
                      ["analysis", "结构分析"],
                      ["export", "导出"],
                      ["history", "快照 / 分享"],
                      ["members", "成员"],
                    ] as const
                  ).map(([id, label]) => (
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

                {projectSub === "library" && project && (
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
                    commitEditor();
                    setChapterId(id);
                  }}
                  onAddChapter={() => void addChapter()}
                  onDeleteChapter={() => void deleteChapter(chapterId)}
                />
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
                        setStatus("已丢弃本章改稿预览");
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
                      <ScriptEditor
                        textareaRef={editorTaRef}
                        frameClassName={styles.scriptEditor}
                        value={editor}
                        locations={project.locations ?? []}
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
                          scheduleEditorCommit();
                        }}
                        onSelect={(e) => {
                          const t = e.currentTarget;
                          setSelection(t.value.slice(t.selectionStart, t.selectionEnd));
                        }}
                      />
                    </StudioErrorBoundary>
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
                              "试玩读的是 RPY 稿。请切到 RPY 后点「根据剧本生成」，或直接手写脚本。"
                            );
                            persistWriteMode("rpy");
                            if (ch) {
                              loadEditorFromChapter(ch, project.characters, "rpy");
                            }
                            return;
                          }
                          setPlayOpen(true);
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
                onSelectCharacters={() => setWorldSub("characters")}
                onSelectBible={() => setWorldSub("bible")}
                onSelectLore={() => setWorldSub("lore")}
                onAddCharacter={addCharacter}
                onDeleteCharacter={(id) => void deleteCharacter(id)}
                onUpdateCharacter={updateCharacter}
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

        {!focusMode ? (
          <StudioErrorBoundary label="审稿 Agent">
            <AgentFloat
              project={project}
              chapterId={chapterId}
              selection={selection}
              draft={editor}
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

        {!focusMode ? <SettingsGear onClick={() => setSettingsOpen(true)} /> : null}
        {settings && (
          <SettingsModal
            open={settingsOpen}
            onClose={() => setSettingsOpen(false)}
            settings={settings}
            onChange={setSettings}
          />
        )}
        <HelpSheet open={helpOpen} onClose={() => setHelpOpen(false)} />
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
      </div>
    </>
  );
}
