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
  patchProject,
  putProject,
  putSettings,
  restoreSnapshot as apiRestoreSnapshot,
  revokeShare,
  type MemoryArchiveDetail,
  type MemoryArchiveSummary,
  type ProjectSummary,
  type SnapshotSummary,
} from "../api/client";
import { useAuth } from "../auth/AuthContext";
import { MapStudio } from "./MapStudio";
import { ColorPicker } from "./ColorPicker";
import { AgentFloat } from "./AgentFloat";
import { AnalysisPanels } from "./AnalysisPanels";
import { SystemPanel } from "./SystemPanel";
import { SettingsGear, SettingsModal } from "./SettingsModal";
import { CharacterWorkshop } from "./CharacterWorkshop";
import { blocksToEditable, editableToBlocks } from "../lib/scriptCodec";
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
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settings, setSettings] = useState<AppSettings | null>(() => {
    const cached = loadAppearanceCache();
    return cached ? { ...DEFAULT_SETTINGS, ...cached } : null;
  });
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState("");
  const [shareUrl, setShareUrl] = useState("");
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

  const fileRef = useRef<HTMLInputElement>(null);
  const renameInputRef = useRef<HTMLInputElement>(null);

  const editorRef = useRef("");
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

  async function persistProject(p: VnProject, opts?: { silent?: boolean }) {
    const silent = opts?.silent ?? true;
    try {
      if (!silent) setStatus("保存中…");
      const saved = await putProject(p.id, p, p.updatedAt);
      skipNextProjectSave.current = true;
      setProject(saved);
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
        setError("项目已在别处更新，建议刷新页面查看最新版本");
      } else {
        setError(e instanceof Error ? e.message : "保存失败");
      }
      return false;
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
      const saved = await putProject(latest.id, latest, latest.updatedAt);
      skipNextProjectSave.current = true;
      setProject(saved);
      const text = await exportRpy(saved.id);
      setRpyPreview(text);
      setRpyStale(false);
      setStatus("已根据当前剧本生成 .rpy，可预览后下载");
      setError("");
    } catch (e) {
      setError(e instanceof Error ? e.message : "生成失败");
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
    const title = window.prompt("新剧本标题", "未命名剧本");
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
    if (!window.confirm(`确定删除「${target?.title ?? ""}」？`)) return;
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

  function deleteCharacter(id: string) {
    if (!window.confirm("删除该角色？剧本中相关对白不会自动改写。")) return;
    updateActive((p) => ({
      ...p,
      characters: p.characters.filter((c) => c.id !== id),
    }));
  }

  function updateBible(patch: Partial<StoryBible>) {
    updateActive((p) => ({
      ...p,
      bible: { ...(p.bible ?? {}), ...patch },
      lore: patch.world !== undefined ? patch.world : p.bible?.world ?? p.lore,
    }));
  }

  function addChapter() {
    const title = window.prompt("章节标题", `第${(project?.chapters.length ?? 0) + 1}章`);
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

  function deleteChapter(id: string) {
    if (!project || project.chapters.length <= 1) {
      setError("至少保留一章");
      return;
    }
    if (!window.confirm("删除该章节？")) return;
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
      if (latest) {
        const saved = await putProject(latest.id, latest, latest.updatedAt);
        skipNextProjectSave.current = true;
        setProject(saved);
      }
      const result = await mapExtract(project.id, { mode });
      skipNextProjectSave.current = true;
      setProject(result.project);
      const warn =
        result.warnings && result.warnings.length
          ? `（${result.warnings[0]}）`
          : "";
      if (result.addedCount === 0 && result.linkCount === 0) {
        setStatus(
          `未发现新地点。可在剧本写 scene bg xxx，或在对白/设定中出现明确场所。${warn}`
        );
      } else {
        const llmBit =
          result.llmUsed && (result.llmAddedCount || result.llmLinkCount)
            ? `，其中模型补充地点 ${result.llmAddedCount ?? 0}、通路 ${result.llmLinkCount ?? 0}`
            : result.llmUsed
              ? "（已调用模型）"
              : "";
        setStatus(
          `地图提取完成（${result.mode ?? mode}）：新增地点 ${result.addedCount}，通路 ${result.linkCount}${llmBit}${warn}`
        );
      }
      setTab("map");
    } catch (e) {
      setError(e instanceof Error ? e.message : "提取失败");
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
    if (!window.confirm(`回退到「${snap.label}」？当前未快照的改动会丢失。`)) {
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
      const latest = buildLatestProject();
      if (latest) {
        const saved = await putProject(latest.id, latest, latest.updatedAt);
        skipNextProjectSave.current = true;
        setProject(saved);
      }
      const blob = await exportJson(project.id);
      downloadBlob(`${project.title || "project"}.json`, blob);
    } catch (e) {
      setError(e instanceof Error ? e.message : "导出失败");
    }
  }

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
    return <div className={styles.boot}>加载中…</div>;
  }

  if (projectsList.length === 0) {
    return (
      <div className={styles.boot}>
        <p>还没有剧本，先创建一个吧</p>
        <div className={styles.aiQuick} style={{ marginTop: "1rem" }}>
          <button type="button" onClick={() => void createBlank()}>
            空白剧本
          </button>
          <button type="button" onClick={() => void createDemo()}>
            示例《雨夜车站》
          </button>
        </div>
      </div>
    );
  }

  if (!project || projectLoading) {
    return <div className={styles.boot}>加载中…</div>;
  }

  const locations = project.locations ?? [];
  const links = project.locationLinks ?? [];
  const bible = project.bible ?? {};

  return (
    <>
      {settings?.bgImage ? (
        <>
          <div className="vnss-wallpaper" aria-hidden />
          <div className="vnss-wallpaper-scrim" aria-hidden />
          <div className="vnss-grain" aria-hidden />
        </>
      ) : null}
      <div className={`vnss-app ${styles.shell}`}>
      <header className={`${styles.top} vnss-frost`}>
        <div className={styles.brandBlock}>
          <span className={styles.brandMark} aria-hidden>
            VN
          </span>
          <div className={styles.brandText}>
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
          <button type="button" className={styles.ghost} onClick={() => void createBlank()}>
            新建
          </button>
          <button
            type="button"
            className={styles.ghost}
            onClick={() => fileRef.current?.click()}
          >
            导入
          </button>
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
          <button type="button" className={styles.ghost} onClick={commitEditor}>
            保存章节
          </button>
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

      {(status || error) && (
        <div className={styles.banner}>
          {error ? (
            <span className={styles.error}>{error}</span>
          ) : (
            <span>{status}</span>
          )}
          <button
            type="button"
            className={styles.ghost}
            onClick={() => {
              setStatus("");
              setError("");
            }}
          >
            关闭
          </button>
        </div>
      )}

      <div className={styles.layout}>
        <main className={styles.main}>
          <nav className={`${styles.tabs} vnss-frost`}>
            {(
              [
                ["write", "写作"],
                ["world", "设定"],
                ["voice", "角色工坊"],
                ["map", "地图"],
                ["system", "VN状态"],
                ["project", "项目"],
              ] as const
            ).map(([id, label]) => (
              <button
                key={id}
                type="button"
                className={tab === id ? styles.tabActive : styles.tab}
                onClick={() => {
                  if (id !== "write" || writeSub !== "script") commitEditor();
                  setTab(id);
                }}
              >
                {label}
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

              {projectSub === "library" && (
                <>
              <div className={styles.toolbar}>
                <span>管理多个剧本：新建、导入 Word/文本/JSON，或载入示例</span>
                <div className={styles.aiQuick}>
                  <button type="button" onClick={() => void createBlank()}>
                    空白剧本
                  </button>
                  <button type="button" onClick={() => void createDemo()}>
                    示例《雨夜车站》
                  </button>
                  <button type="button" onClick={() => fileRef.current?.click()}>
                    导入文件
                  </button>
                </div>
              </div>
              <p className={styles.hint}>
                支持 .docx / .txt / .md / .rpy / 工程 .json。卡片可点「重命名」或双击标题改名；顶栏标题也可随时改。
              </p>
              <div className={styles.libraryGrid}>
                {projectsList.map((p) => (
                  <article
                    key={p.id}
                    className={
                      p.id === project.id
                        ? styles.libraryCardActive
                        : styles.libraryCard
                    }
                  >
                    {renamingId === p.id ? (
                      <input
                        ref={renameInputRef}
                        className={styles.libraryRename}
                        value={renameDraft}
                        onChange={(e) => setRenameDraft(e.target.value)}
                        onBlur={() => void commitRename()}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") {
                            e.preventDefault();
                            void commitRename();
                          }
                          if (e.key === "Escape") {
                            e.preventDefault();
                            cancelRename();
                          }
                        }}
                        aria-label="重命名剧本"
                      />
                    ) : (
                      <h3
                        className={styles.libraryTitle}
                        title="双击重命名"
                        onDoubleClick={() => startRename(p.id)}
                      >
                        {p.title}
                      </h3>
                    )}
                    <p>{p.logline || "暂无简介"}</p>
                    <p className={styles.meta}>
                      更新于 {new Date(p.updated_at).toLocaleString()}
                    </p>
                    <div className={styles.cardActions}>
                      <button
                        type="button"
                        className={styles.primary}
                        onClick={() => void switchProject(p.id)}
                      >
                        打开
                      </button>
                      <button
                        type="button"
                        className={styles.ghost}
                        onClick={() => startRename(p.id)}
                      >
                        重命名
                      </button>
                      <button
                        type="button"
                        className={styles.ghost}
                        onClick={() => void duplicateProjectById(p.id)}
                      >
                        复制
                      </button>
                      <button
                        type="button"
                        className={styles.ghost}
                        onClick={() => void deleteProjectById(p.id)}
                      >
                        删除
                      </button>
                    </div>
                  </article>
                ))}
              </div>
                </>
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
                    <p className={styles.hint}>
                      尚未生成。点击「生成 .rpy」会从当前章节与角色设定编译 Ren&apos;Py 脚本。
                    </p>
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
                    commitEditor();
                    setWriteSub("analysis");
                  }}
                >
                  分析
                </button>
                <div className={styles.chapterBar}>
                  <label className={styles.inlineLabel}>
                    章节
                    <select
                      className={styles.select}
                      value={chapterId}
                      onChange={(e) => {
                        commitEditor();
                        setChapterId(e.target.value);
                      }}
                    >
                      {project.chapters.map((c) => (
                        <option key={c.id} value={c.id}>
                          {c.title}
                        </option>
                      ))}
                    </select>
                  </label>
                  <button
                    type="button"
                    className={styles.ghost}
                    onClick={addChapter}
                  >
                    + 章
                  </button>
                  <button
                    type="button"
                    className={styles.ghost}
                    disabled={project.chapters.length <= 1}
                    onClick={() => deleteChapter(chapterId)}
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
                <span className={styles.hintInline}>
                  续写 / 改写 / 润色请用右下角审稿 Agent · 换剧本在「项目」
                </span>
              </div>
              <textarea
                className={styles.editor}
                value={editor}
                onChange={(e) => {
                  editorRef.current = e.target.value;
                  setEditor(e.target.value);
                  if (rpyPreview) setRpyStale(true);
                  scheduleEditorCommit();
                }}
                onSelect={(e) => {
                  const t = e.currentTarget;
                  setSelection(
                    t.value.slice(t.selectionStart, t.selectionEnd)
                  );
                }}
                spellCheck={false}
              />
            </section>
              )}
              {writeSub === "analysis" && (
                <section className={styles.panel}>
                  <AnalysisPanels
                    project={project}
                    chapterId={chapterId}
                    draft={editor}
                    onChange={updateActive}
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
                        onClick={() => deleteCharacter(c.id)}
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
                mapStyle={project.mapStyle ?? "campus"}
                customElements={project.customMapElements ?? []}
                strokes={project.mapStrokes ?? []}
                onChangeLocations={(locs) =>
                  updateActive((p) => ({ ...p, locations: locs }))
                }
                onChangeLinks={(nextLinks) =>
                  updateActive((p) => ({ ...p, locationLinks: nextLinks }))
                }
                onChangeStyle={(mapStyle) => updateActive((p) => ({ ...p, mapStyle }))}
                onChangeCustomElements={(customMapElements) =>
                  updateActive((p) => ({ ...p, customMapElements }))
                }
                onChangeStrokes={(mapStrokes) =>
                  updateActive((p) => ({ ...p, mapStrokes }))
                }
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

      <AgentFloat
        project={project}
        chapterId={chapterId}
        selection={selection}
        draft={editor}
        prepareProject={() => buildLatestProject() ?? project}
        onProjectChange={(p) => {
          replaceActiveProject(p);
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

      <SettingsGear onClick={() => setSettingsOpen(true)} />
      {settings && (
        <SettingsModal
          open={settingsOpen}
          onClose={() => setSettingsOpen(false)}
          settings={settings}
          onChange={setSettings}
        />
      )}
      </div>
    </>
  );
}
