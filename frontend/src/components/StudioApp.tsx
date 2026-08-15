import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import { useNavigate } from "react-router-dom";
import {
  ApiError,
  archiveChapterMemory,
  createProject,
  createShare,
  createSnapshot,
  deleteProject as apiDeleteProject,
  deleteSnapshot as apiDeleteSnapshot,
  duplicateProject as apiDuplicateProject,
  exportJson,
  exportRpy,
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
  type SnapshotSummary,
} from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { ScriptEditor } from "./ScriptEditor";
import { MapStudio } from "./MapStudio";
import { MapExtractReview } from "./MapExtractReview";
import { ColorPicker } from "./ColorPicker";
import { AgentFloat } from "./AgentFloat";
import { AnalysisPanels } from "./AnalysisPanels";
import { SystemPanel } from "./SystemPanel";
import { SettingsGear, SettingsModal } from "./SettingsModal";
import { CharacterWorkshop } from "./CharacterWorkshop";
import { FocusChrome } from "./FocusChrome";
import { useConfirm, usePrompt } from "./ConfirmDialog";
import { EmptyStage } from "./EmptyStage";
import { ProjectLibraryPanel } from "./ProjectLibraryPanel";
import { StudioErrorBoundary } from "./StudioErrorBoundary";
import {
  SaveConflictDialog,
  type SaveConflictChoice,
} from "./SaveConflictDialog";
import {
  clearConflictDraft,
  downloadProjectJson,
  stashConflictDraft,
} from "../lib/conflictDraft";
import {
  StatusToast,
  classifyStatusToast,
} from "./StatusToast";
import {
  blockTextRange,
  blocksToEditable,
  editableToBlocks,
} from "../lib/scriptCodec";
import { normalizeProject } from "../lib/vnLocal";
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
import type { Character, Location, StoryBible, VnProject } from "../types/vn";
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

  const [tab, setTab] = useState<Tab>(
    (cachedWs.tab as Tab) || wsDefaults.tab
  );
  const [writeSub, setWriteSub] = useState<"script" | "analysis">(
    cachedWs.writeSub || wsDefaults.writeSub
  );
  const [worldSub, setWorldSub] = useState<"characters" | "bible">(
    cachedWs.worldSub || wsDefaults.worldSub
  );
  const [systemSub, setSystemSub] = useState<"variables" | "sprites">(
    cachedWs.systemSub || wsDefaults.systemSub
  );
  const [projectSub, setProjectSub] = useState<"library" | "export" | "history">(
    cachedWs.projectSub || wsDefaults.projectSub
  );
  const [chapterId, setChapterId] = useState(cachedWs.chapterId || "");
  const [editor, setEditor] = useState("");
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
  const [memoryArchives, setMemoryArchives] = useState<MemoryArchiveSummary[]>(
    []
  );
  const [memoryDetail, setMemoryDetail] = useState<MemoryArchiveDetail | null>(
    null
  );
  const [memoryDetailBusy, setMemoryDetailBusy] = useState(false);
  /** 导出页：先生成预览，再允许下载 */
  const [rpyPreview, setRpyPreview] = useState<string | null>(null);
  const [rpyStale, setRpyStale] = useState(false);
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
  }, [project?.id, chapterId]);

  const refreshProjectsList = useCallback(async () => {
    const list = await listProjects();
    setProjectsList(list);
    return list;
  }, []);

  const loadProjectInto = useCallback(async (id: string, preferredChapterId?: string) => {
    skipNextProjectSave.current = true;
    setProjectLoading(true);
    try {
      const p = await getProject(id);
      setProject(p);
      const ws = loadWorkspace();
      const wantChapter =
        preferredChapterId ||
        (ws.projectId === id ? ws.chapterId : "") ||
        "";
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
  }, []);

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
  }, [
    project?.id,
    chapterId,
    tab,
    writeSub,
    worldSub,
    systemSub,
    projectSub,
  ]);

  // Sync editor text whenever project or chapter switches (not on every save).
  useEffect(() => {
    if (!project || !chapterId) return;
    const ch = project.chapters.find((c) => c.id === chapterId);
    if (!ch) return;
    editorRef.current = blocksToEditable(ch.blocks, project.characters);
    setEditor(editorRef.current);
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
    const range = blockTextRange(
      ch.blocks,
      project.characters,
      pending.blockIndex
    );
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [project]);

  async function persistProject(p: VnProject, opts?: { silent?: boolean; force?: boolean }) {
    const silent = opts?.silent ?? true;
    try {
      if (!silent) setStatus("保存中…");
      const saved = await putProject(p.id, p, p.updatedAt, {
        force: opts?.force,
      });
      skipNextProjectSave.current = true;
      setProject(saved);
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
      if (e instanceof ApiError && e.status === 409) {
        stashConflictDraft(p);
        const detail = e.detail as
          | { serverUpdatedAt?: string; message?: string }
          | undefined;
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
    // eslint-disable-next-line react-hooks/exhaustive-deps
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

  function commitEditor() {
    if (editorCommitTimer.current) {
      window.clearTimeout(editorCommitTimer.current);
      editorCommitTimer.current = null;
    }
    if (!project || !chapter) return;
    const blocks = editableToBlocks(editorRef.current);
    updateActive((p) => ({
      ...p,
      chapters: p.chapters.map((c) =>
        c.id === chapter.id ? { ...c, blocks } : c
      ),
    }));
  }

  function scheduleEditorCommit() {
    if (editorCommitTimer.current) window.clearTimeout(editorCommitTimer.current);
    editorCommitTimer.current = window.setTimeout(() => commitEditor(), 900);
  }

  function buildLatestProject(): VnProject | null {
    if (!project) return null;
    return {
      ...project,
      chapters: project.chapters.map((c) =>
        c.id === chapterId
          ? { ...c, blocks: editableToBlocks(editorRef.current) }
          : c
      ),
    };
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
      characters: p.characters.map((c) =>
        c.id === id ? { ...c, ...patch } : c
      ),
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

  function updateLocation(id: string, patch: Partial<Location>) {
    updateActive((p) => ({
      ...p,
      locations: (p.locations ?? []).map((l) =>
        l.id === id ? { ...l, ...patch } : l
      ),
    }));
  }

  function deleteLocation(id: string) {
    updateActive((p) => ({
      ...p,
      locations: (p.locations ?? []).filter((l) => l.id !== id),
      locationLinks: (p.locationLinks ?? []).filter(
        (l) => l.fromId !== id && l.toId !== id
      ),
    }));
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
        skipNextProjectSave.current = true;
        setProject(saved);
      }
      const result = await mapExtract(projectId, { mode });
      const warn =
        result.warnings && result.warnings.length
          ? `（${result.warnings[0]}）`
          : "";
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
      setStatus(
        `找到候选：地点 ${newPlaces}、通路 ${newLinks}，请勾选后写入${warn}`
      );
      setTab("map");
    } catch (e) {
      setError(e instanceof Error ? e.message : "提取失败");
    }
  }

  async function confirmMapExtract(
    placeIds: string[],
    linkIds: string[]
  ) {
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
      setStatus(
        `已写入地图：新增地点 ${result.addedCount}，通路 ${result.linkCount}`
      );
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
        editorRef.current = blocksToEditable(ch.blocks, restored.characters);
        setEditor(editorRef.current);
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
    } catch (e) {
      setError(e instanceof Error ? e.message : "删除快照失败");
    }
  }

  async function createShareLink() {
    if (!project) return;
    commitEditor();
    try {
      const latest = buildLatestProject();
      if (latest) {
        const saved = await putProject(latest.id, latest, latest.updatedAt);
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
    return (
      <div className={`vnss-app ${styles.boot}`}>
        <div className={styles.bootArc} aria-hidden>
          <span>LOAD</span>
        </div>
        <p className={styles.bootKicker}>SCRIPT STUDIO</p>
        <p className={styles.bootTitle}>加载中</p>
      </div>
    );
  }

  if (projectsList.length === 0) {
    return (
      <div className={`vnss-app ${styles.boot}`}>
        <div className={styles.bootArc} aria-hidden>
          <span>LIB</span>
        </div>
        <p className={styles.bootKicker}>SCRIPT STUDIO</p>
        <h1 className={styles.bootTitle}>还没有剧本</h1>
        <p className={styles.bootLead}>先建一个空白工程，或载入示例开场。</p>
        <div className={styles.bootEmpty}>
          <EmptyStage
            stamp="LIB"
            title="项目库空着"
            line={mascotLine("emptyLibrary")}
          >
            <div className={styles.aiQuick}>
              <button type="button" onClick={() => void createBlank()}>
                空白剧本
              </button>
              <button type="button" onClick={() => void createDemo()}>
                示例《雨夜车站》
              </button>
            </div>
          </EmptyStage>
        </div>
      </div>
    );
  }

  if (!project || projectLoading) {
    return (
      <div className={`vnss-app ${styles.boot}`}>
        <div className={styles.bootArc} aria-hidden>
          <span>LOAD</span>
        </div>
        <p className={styles.bootKicker}>SCRIPT STUDIO</p>
        <p className={styles.bootTitle}>加载中</p>
      </div>
    );
  }

  const locations = project.locations ?? [];
  const links = project.locationLinks ?? [];
  const bible = project.bible ?? {};
  const toast = classifyStatusToast(status, error);
  const writeQuiet = tab === "write" && writeSub === "script";

  return (
    <>
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
          tab === "write" && writeSub === "script" && focusMode
            ? styles.focusMode
            : ""
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
      <header className={`${styles.top} vnss-frost`}>
        <div className={styles.brandBlock}>
          <span className={styles.brandMark} aria-hidden>
            <em>SS</em>
            <span>VN</span>
          </span>
          <div className={styles.brandText}>
            <p className={styles.brandKicker}>VISUAL NOVEL</p>
            <p className={styles.brand}>Script Studio</p>
            <input
              className={styles.titleInput}
              value={project.title}
              onChange={(e) =>
                updateActive((p) => ({ ...p, title: e.target.value }))
              }
              aria-label="作品标题"
              placeholder="作品标题"
            />
          </div>
        </div>
        <div className={styles.topActions}>
          {tab === "write" && writeSub === "script" && !focusMode ? (
            <button
              type="button"
              className={styles.focusToggle}
              aria-pressed={false}
              onClick={requestFocusSession}
              title="专注全屏写作 (Ctrl+\\)"
            >
              专注
            </button>
          ) : null}
          <details className={styles.moreMenu}>
            <summary>更多</summary>
            <div className={styles.morePanel} role="menu">
              <button
                type="button"
                role="menuitem"
                onClick={() => void createBlank()}
              >
                新建剧本
              </button>
              <button
                type="button"
                role="menuitem"
                onClick={() => fileRef.current?.click()}
              >
                导入文件
              </button>
              <button type="button" role="menuitem" onClick={commitEditor}>
                保存章节
              </button>
            </div>
          </details>
          <input
            ref={fileRef}
            type="file"
            hidden
            accept=".docx,.txt,.md,.rpy,.json,.fountain"
            onChange={(e) => {
              const f = e.target.files?.[0];
              if (f) void handleImportFile(f);
              e.target.value = "";
            }}
          />
          <button
            type="button"
            className={styles.primary}
            onClick={() => {
              setTab("project");
              setProjectSub("export");
              void generateRpy();
            }}
          >
            导出 .rpy
          </button>
          {user?.username ? (
            <span className={styles.userChip} title={user.username}>
              {user.username}
            </span>
          ) : null}
          <button type="button" className={styles.ghost} onClick={handleLogout}>
            退出
          </button>
        </div>
      </header>

      <div className={styles.layout}>
        <main className={styles.main}>
          <nav className={`${styles.tabs} vnss-frost`} aria-label="剧本篇章">
            <span className={styles.tabsRail} aria-hidden />
            {(
              [
                ["write", "01", "写作"],
                ["world", "02", "设定"],
                ["voice", "03", "角色工坊"],
                ["map", "04", "地图"],
                ["system", "05", "VN状态"],
                ["project", "06", "项目"],
              ] as const
            ).map(([id, idx, label]) => (
              <button
                key={id}
                type="button"
                className={tab === id ? styles.tabActive : styles.tab}
                onClick={() => {
                  if (id !== "write" || writeSub !== "script") commitEditor();
                  setTab(id);
                }}
              >
                <span className={styles.tabIdx} aria-hidden>
                  {idx}
                </span>
                <span className={styles.tabLabel}>{label}</span>
              </button>
            ))}
          </nav>

          {tab === "project" && (
            <section className={styles.panel}>
              <div className={styles.subNav}>
                {(
                  [
                    ["library", "剧本库"],
                    ["export", "导出"],
                    ["history", "快照 / 分享"],
                  ] as const
                ).map(([id, label]) => (
                  <button
                    key={id}
                    type="button"
                    className={
                      projectSub === id ? styles.subActive : styles.subTab
                    }
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
                  onImportClick={() => fileRef.current?.click()}
                  onDuplicate={(id) => void duplicateProjectById(id)}
                  onDelete={(id) => void deleteProjectById(id)}
                />
              )}

              {projectSub === "export" && (
                <>
                  <div className={styles.toolbar}>
                    <span>
                      先根据当前剧本生成 .rpy 预览，确认无误后再下载；工程 JSON 可随时导出。
                    </span>
                    <div className={styles.aiQuick}>
                      <button
                        type="button"
                        className={styles.primary}
                        onClick={() => void generateRpy()}
                      >
                        生成 .rpy
                      </button>
                      <button
                        type="button"
                        disabled={!rpyPreview || rpyStale}
                        onClick={downloadRpy}
                        title={
                          !rpyPreview
                            ? "请先生成"
                            : rpyStale
                              ? "剧本已改动，请重新生成"
                              : "下载预览中的 .rpy"
                        }
                      >
                        下载 .rpy
                      </button>
                      <button type="button" onClick={() => void downloadJson()}>
                        下载工程 .json
                      </button>
                    </div>
                  </div>
                  {rpyStale && rpyPreview && (
                    <p className={styles.hint}>
                      剧本已修改，预览已过期 — 请重新点击「生成 .rpy」。
                    </p>
                  )}
                  {!rpyPreview ? (
                    <EmptyStage
                      stamp="EXP"
                      title="尚无导出预览"
                      line={mascotLine("emptyExport")}
                    >
                      <button
                        type="button"
                        className={styles.primary}
                        onClick={() => void generateRpy()}
                      >
                        生成 .rpy
                      </button>
                    </EmptyStage>
                  ) : (
                    <pre className={styles.pre}>{rpyPreview}</pre>
                  )}
                </>
              )}

              {projectSub === "history" && (
                <>
                  <div className={styles.toolbar}>
                    <span>版本快照可回退大改稿；只读链接给画师 / 配音看设定</span>
                  </div>
                  <div className={styles.shareBox}>
                    <strong>长程章节记忆</strong>
                    <p style={{ margin: 0, fontSize: "0.85rem", color: "var(--ink-soft)" }}>
                      借鉴 NovelMaster：每 10 章一段 continuity，拆成 PostgreSQL TEXT
                      切片；Agent 会自动注入最新段。
                    </p>
                    <div className={styles.aiQuick}>
                      <button
                        type="button"
                        className={styles.primary}
                        onClick={() => void archiveLongMemory()}
                      >
                        归档长程记忆
                      </button>
                    </div>
                    <ul className={styles.snapList}>
                      {memoryArchives.map((a) => (
                        <li key={a.id}>
                          <span>
                            {a.label}
                            {a.isLatest ? " · 最新" : ""}
                            <br />
                            <small>
                              第 {a.rangeFrom}–{a.rangeTo} 章 · {a.wordCount} 字
                            </small>
                          </span>
                          <button
                            type="button"
                            className={styles.ghost}
                            disabled={memoryDetailBusy}
                            onClick={() => void openMemoryArchive(a.id)}
                          >
                            查看
                          </button>
                        </li>
                      ))}
                      {memoryArchives.length === 0 && (
                        <li>尚未归档。章节较多时点上方按钮生成。</li>
                      )}
                    </ul>
                    {memoryDetail && (
                      <div className={styles.memoryPeek}>
                        <div className={styles.toolbar}>
                          <strong>{memoryDetail.label}</strong>
                          <button
                            type="button"
                            className={styles.ghost}
                            onClick={() => setMemoryDetail(null)}
                          >
                            关闭
                          </button>
                        </div>
                        <p className={styles.hint}>
                          continuity 切片预览（Agent 注入用最新段）
                        </p>
                        <pre className={styles.pre}>
                          {(memoryDetail.continuityText || "").slice(0, 4000) ||
                            "（无 continuity 正文）"}
                          {(memoryDetail.continuityText || "").length > 4000
                            ? "\n…(已截断)"
                            : ""}
                        </pre>
                      </div>
                    )}
                  </div>
                  <div className={styles.shareBox}>
                    <strong>快照</strong>
                    <div className={styles.aiQuick}>
                      <input
                        value={snapLabel}
                        onChange={(e) => setSnapLabel(e.target.value)}
                        placeholder="快照备注（可选）"
                      />
                      <button
                        type="button"
                        className={styles.primary}
                        onClick={() => void takeSnapshot()}
                      >
                        保存当前快照
                      </button>
                    </div>
                    <ul className={styles.snapList}>
                      {snapshots.map((s) => (
                        <li key={s.id}>
                          <span>
                            {s.label}
                            <br />
                            <small>
                              {new Date(s.createdAt).toLocaleString()}
                            </small>
                          </span>
                          <span>
                            <button
                              type="button"
                              className={styles.ghost}
                              onClick={() => void restoreSnapshotById(s.id)}
                            >
                              回退到此
                            </button>
                            <button
                              type="button"
                              className={styles.ghost}
                              onClick={() => void deleteSnapshotById(s.id)}
                            >
                              删除
                            </button>
                          </span>
                        </li>
                      ))}
                      {snapshots.length === 0 && <li>尚无快照</li>}
                    </ul>
                  </div>
                  <div className={styles.shareBox}>
                    <strong>只读分享</strong>
                    <p className={styles.hint}>
                      生成链接后任何人都可打开只读页面查看设定摘要；可随时撤销。
                    </p>
                    <div className={styles.aiQuick}>
                      <button
                        type="button"
                        className={styles.primary}
                        onClick={() => void createShareLink()}
                      >
                        生成并复制链接
                      </button>
                      {project.shareId && (
                        <button type="button" onClick={() => void revokeShareLink()}>
                          撤销分享
                        </button>
                      )}
                    </div>
                    {shareUrl && (
                      <input readOnly value={shareUrl} onFocus={(e) => e.target.select()} />
                    )}
                  </div>
                </>
              )}
            </section>
          )}

          {tab === "write" && (
            <>
              <div className={styles.subNav} style={{ padding: "0.75rem 1.1rem 0" }}>
                <button
                  type="button"
                  className={
                    writeSub === "script" ? styles.subActive : styles.subTab
                  }
                  onClick={() => setWriteSub("script")}
                >
                  剧本
                </button>
                <button
                  type="button"
                  className={
                    writeSub === "analysis" ? styles.subActive : styles.subTab
                  }
                  onClick={() => {
                    void (async () => {
                      commitEditor();
                      await flushPendingSave();
                      setWriteSub("analysis");
                    })();
                  }}
                >
                  分析
                </button>
                <div className={styles.chapterBar}>
                  <span className={styles.inlineLabel}>篇章</span>
                  <div
                    className={styles.chapterStrip}
                    role="listbox"
                    aria-label="篇章"
                  >
                    {project.chapters.map((c, i) => (
                      <button
                        key={c.id}
                        type="button"
                        role="option"
                        aria-selected={c.id === chapterId}
                        className={
                          c.id === chapterId
                            ? styles.chapterChipOn
                            : styles.chapterChip
                        }
                        onClick={() => {
                          if (c.id === chapterId) return;
                          commitEditor();
                          setChapterId(c.id);
                        }}
                      >
                        <em>{String(i + 1).padStart(2, "0")}</em>
                        <span>{c.title || `第 ${i + 1} 章`}</span>
                      </button>
                    ))}
                  </div>
                  <button
                    type="button"
                    className={styles.ghost}
                    onClick={() => void addChapter()}
                  >
                    + 章
                  </button>
                  <button
                    type="button"
                    className={styles.ghost}
                    disabled={project.chapters.length <= 1}
                    onClick={() => void deleteChapter(chapterId)}
                  >
                    删章
                  </button>
                </div>
              </div>
              {writeSub === "script" && (
            <section className={styles.panel}>
              <div className={styles.toolbar}>
                <label className={styles.inlineLabel}>
                  章节名
                  <input
                    value={chapter?.title ?? ""}
                    onChange={(e) => {
                      const title = e.target.value;
                      updateActive((p) => ({
                        ...p,
                        chapters: p.chapters.map((c) =>
                          c.id === chapterId ? { ...c, title } : c
                        ),
                      }));
                    }}
                  />
                </label>
                {reviseDraft ? (
                  <div className={styles.reviseDraftActions}>
                    <button
                      type="button"
                      className={styles.reviseDraftBtn}
                      title="打开未写入的改稿对照（刷新后仍可进入）"
                      onClick={() => {
                        if (focusMode) {
                          setStatus("请先退出专注模式，再打开改稿对照");
                          return;
                        }
                        requestOpenReviseReview(project.id, chapterId);
                      }}
                    >
                      改稿对照
                    </button>
                    <button
                      type="button"
                      className={styles.ghost}
                      title="丢弃本章未写入的改稿预览"
                      onClick={() => {
                        clearChapterReviseDraft(project.id, chapterId);
                        setReviseDraft(null);
                        setStatus("已丢弃本章改稿预览");
                      }}
                    >
                      丢弃预览
                    </button>
                  </div>
                ) : (
                  <span className={styles.hintInline}>
                    地名会高亮，点击可跳到地图 · 续写用右下角 Agent
                  </span>
                )}
              </div>
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
                onChange={(next) => {
                  editorRef.current = next;
                  setEditor(next);
                  if (rpyPreview) setRpyStale(true);
                  scheduleEditorCommit();
                }}
                onSelect={(e) => {
                  const t = e.currentTarget;
                  setSelection(
                    t.value.slice(t.selectionStart, t.selectionEnd)
                  );
                }}
              />
              </StudioErrorBoundary>
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
            <>
              <div className={styles.subNav} style={{ padding: "0.75rem 1.1rem 0" }}>
                <button
                  type="button"
                  className={
                    worldSub === "characters" ? styles.subActive : styles.subTab
                  }
                  onClick={() => setWorldSub("characters")}
                >
                  角色卡
                </button>
                <button
                  type="button"
                  className={
                    worldSub === "bible" ? styles.subActive : styles.subTab
                  }
                  onClick={() => setWorldSub("bible")}
                >
                  世界观 / 大纲
                </button>
              </div>
              {worldSub === "characters" && (
            <section className={styles.panel}>
              <div className={styles.toolbar}>
                <span>角色卡（删除不会自动改写对白）</span>
                <button
                  type="button"
                  className={styles.primary}
                  onClick={addCharacter}
                >
                  添加角色
                </button>
              </div>
              <div className={styles.charGrid}>
                {project.characters.map((c) => (
                  <article key={c.id} className={styles.charCard}>
                    <div className={styles.cardHead}>
                      <strong>{c.displayName || "未命名"}</strong>
                      <button
                        type="button"
                        className={styles.danger}
                        onClick={() => void deleteCharacter(c.id)}
                      >
                        删除
                      </button>
                    </div>
                    <label>
                      显示名
                      <input
                        value={c.displayName}
                        onChange={(e) =>
                          updateCharacter(c.id, {
                            displayName: e.target.value,
                          })
                        }
                      />
                    </label>
                    <label>
                      define 名
                      <input
                        value={c.defineName}
                        onChange={(e) =>
                          updateCharacter(c.id, {
                            defineName: e.target.value.replace(
                              /[^A-Za-z0-9_]/g,
                              ""
                            ),
                          })
                        }
                      />
                    </label>
                    <label>
                      颜色
                      <ColorPicker
                        value={c.color ?? "#6b7280"}
                        onChange={(color) =>
                          updateCharacter(c.id, { color })
                        }
                      />
                    </label>
                    <label>
                      语气
                      <textarea
                        rows={2}
                        value={c.voice ?? ""}
                        onChange={(e) =>
                          updateCharacter(c.id, { voice: e.target.value })
                        }
                      />
                    </label>
                    <label>
                      简介
                      <textarea
                        rows={3}
                        value={c.bio ?? ""}
                        onChange={(e) =>
                          updateCharacter(c.id, { bio: e.target.value })
                        }
                      />
                    </label>
                    <label>
                      人物关系
                      <textarea
                        rows={2}
                        value={c.relationships ?? ""}
                        onChange={(e) =>
                          updateCharacter(c.id, {
                            relationships: e.target.value,
                          })
                        }
                      />
                    </label>
                  </article>
                ))}
              </div>
            </section>
              )}
              {worldSub === "bible" && (
            <section className={styles.panel}>
              <div className={styles.toolbar}>
                <span>故事设定独立于角色卡，会进入 AI 上下文</span>
              </div>
              <div className={styles.bibleGrid}>
                <label>
                  Logline（一句话）
                  <input
                    value={project.logline ?? ""}
                    onChange={(e) =>
                      updateActive((p) => ({ ...p, logline: e.target.value }))
                    }
                  />
                </label>
                <label>
                  类型 / 题材
                  <input
                    value={project.genre ?? ""}
                    onChange={(e) =>
                      updateActive((p) => ({ ...p, genre: e.target.value }))
                    }
                  />
                </label>
                <label className={styles.full}>
                  世界观
                  <textarea
                    rows={4}
                    value={bible.world ?? ""}
                    onChange={(e) => updateBible({ world: e.target.value })}
                    placeholder="世界规则、时代、超自然设定…"
                  />
                </label>
                <label className={styles.full}>
                  故事背景 / 前情
                  <textarea
                    rows={4}
                    value={bible.background ?? ""}
                    onChange={(e) =>
                      updateBible({ background: e.target.value })
                    }
                    placeholder="开场前发生了什么…"
                  />
                </label>
                <label className={styles.full}>
                  大纲 / 节拍
                  <textarea
                    rows={6}
                    value={bible.outline ?? ""}
                    onChange={(e) => updateBible({ outline: e.target.value })}
                    placeholder="分幕或章节节拍…"
                  />
                </label>
                <label className={styles.full}>
                  主题 / 基调 / 禁忌
                  <textarea
                    rows={3}
                    value={bible.themes ?? ""}
                    onChange={(e) => updateBible({ themes: e.target.value })}
                  />
                </label>
                <label className={styles.full}>
                  其他备忘
                  <textarea
                    rows={3}
                    value={bible.notes ?? ""}
                    onChange={(e) => updateBible({ notes: e.target.value })}
                  />
                </label>
              </div>
            </section>
              )}
            </>
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
                    pendingEditorFocus.current = { chapterId: id, blockIndex };
                    setEditorFocusNonce((n) => n + 1);
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
              editorRef.current = blocksToEditable(ch.blocks, p.characters);
              setEditor(editorRef.current);
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

      {!focusMode ? (
        <SettingsGear onClick={() => setSettingsOpen(true)} />
      ) : null}
      {settings && (
        <SettingsModal
          open={settingsOpen}
          onClose={() => setSettingsOpen(false)}
          settings={settings}
          onChange={setSettings}
        />
      )}
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
