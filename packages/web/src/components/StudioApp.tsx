"use client";

import { useCallback, useEffect, useMemo, useRef, useState } from "react";
import mammoth from "mammoth";
import {
  createDemoProject,
  emptyProject,
  exportToRenpy,
  extractMapFromScript,
  normalizeProject,
  projectFromPlainText,
  touchProject,
  uid,
  type Character,
  type Location,
  type StoryBible,
  type VnProject,
} from "@vnss/core";
import { MapStudio } from "./MapStudio";
import { ColorPicker } from "./ColorPicker";
import { AgentFloat } from "./AgentFloat";
import { AnalysisPanels } from "./AnalysisPanels";
import { SystemPanel } from "./SystemPanel";
import { SettingsGear, SettingsModal } from "./SettingsModal";
import { blocksToEditable, editableToBlocks } from "@/lib/scriptCodec";
import {
  listProjects,
  loadLibrary,
  saveLibrary,
  type ProjectLibrary,
} from "@/lib/storage";
import { publishShare } from "@/lib/share";
import {
  applySettingsToDom,
  loadSettings,
  type AppSettings,
} from "@/lib/settings";
import styles from "./StudioApp.module.css";

/** 顶栏只保留 5 组，细项用二级切换 */
type Tab = "write" | "world" | "map" | "system" | "project";

function downloadText(filename: string, content: string, mime: string) {
  const blob = new Blob([content], { type: mime });
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  a.click();
  URL.revokeObjectURL(url);
}

export function StudioApp() {
  const [library, setLibrary] = useState<ProjectLibrary | null>(null);
  const [tab, setTab] = useState<Tab>("write");
  const [writeSub, setWriteSub] = useState<"script" | "analysis">("script");
  const [worldSub, setWorldSub] = useState<"characters" | "bible">("characters");
  const [systemSub, setSystemSub] = useState<"variables" | "sprites">("variables");
  const [projectSub, setProjectSub] = useState<"library" | "export" | "history">(
    "library"
  );
  const [chapterId, setChapterId] = useState("");
  const [editor, setEditor] = useState("");
  const [selection, setSelection] = useState("");
  const [error, setError] = useState("");
  const [status, setStatus] = useState("");
  const [settingsOpen, setSettingsOpen] = useState(false);
  const [settings, setSettings] = useState<AppSettings | null>(null);
  const [renamingId, setRenamingId] = useState<string | null>(null);
  const [renameDraft, setRenameDraft] = useState("");
  const [shareUrl, setShareUrl] = useState("");
  const [snapLabel, setSnapLabel] = useState("");
  /** 导出页：先生成预览，再允许下载 */
  const [rpyPreview, setRpyPreview] = useState<string | null>(null);
  const [rpyStale, setRpyStale] = useState(false);
  const fileRef = useRef<HTMLInputElement>(null);
  const renameInputRef = useRef<HTMLInputElement>(null);

  const project = library?.projects[library.activeId] ?? null;

  const persist = useCallback((next: ProjectLibrary) => {
    setLibrary(next);
    saveLibrary(next);
  }, []);

  const updateActive = useCallback((updater: (p: VnProject) => VnProject) => {
    setLibrary((prev) => {
      if (!prev) return prev;
      const current = prev.projects[prev.activeId];
      if (!current) return prev;
      const updated = touchProject(updater(current));
      const next: ProjectLibrary = {
        ...prev,
        projects: { ...prev.projects, [updated.id]: updated },
      };
      saveLibrary(next);
      return next;
    });
  }, []);

  function replaceActiveProject(nextProject: VnProject) {
    setLibrary((prev) => {
      if (!prev) return prev;
      const id = prev.activeId;
      const updated = touchProject({ ...nextProject, id });
      const next: ProjectLibrary = {
        ...prev,
        projects: { ...prev.projects, [id]: updated },
      };
      saveLibrary(next);
      return next;
    });
  }

  useEffect(() => {
    const s = loadSettings();
    setSettings(s);
    applySettingsToDom(s);
    const lib = loadLibrary();
    setLibrary(lib);
    const p = lib.projects[lib.activeId];
    setChapterId(p?.chapters[0]?.id ?? "");
  }, []);

  useEffect(() => {
    if (!library) return;
    const p = library.projects[library.activeId];
    if (!p || !chapterId) return;
    const ch = p.chapters.find((c) => c.id === chapterId);
    if (!ch) return;
    setEditor(blocksToEditable(ch.blocks, p.characters));
    // Only reload editor when switching project/chapter — not on every save.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [library?.activeId, chapterId]);

  const chapter = useMemo(
    () => project?.chapters.find((c) => c.id === chapterId),
    [project, chapterId]
  );

  useEffect(() => {
    setRpyPreview(null);
    setRpyStale(false);
  }, [library?.activeId]);

  function buildLatestProject(): VnProject | null {
    if (!project) return null;
    return {
      ...project,
      chapters: project.chapters.map((c) =>
        c.id === chapterId
          ? { ...c, blocks: editableToBlocks(editor) }
          : c
      ),
    };
  }

  function generateRpy() {
    if (!project) return;
    const latest = buildLatestProject();
    if (!latest) return;
    // 同步写入章节，避免预览与磁盘不一致
    updateActive(() => latest);
    const text = exportToRenpy(latest);
    setRpyPreview(text);
    setRpyStale(false);
    setStatus("已根据当前剧本生成 .rpy，可预览后下载");
    setError("");
  }

  function commitEditor() {
    if (!project || !chapter) return;
    const blocks = editableToBlocks(editor);
    updateActive((p) => ({
      ...p,
      chapters: p.chapters.map((c) =>
        c.id === chapter.id ? { ...c, blocks } : c
      ),
    }));
  }

  function switchProject(id: string) {
    if (!library || !library.projects[id]) return;
    commitEditor();
    persist({ ...library, activeId: id });
    setChapterId(library.projects[id].chapters[0]?.id ?? "");
    setTab("write");
    setWriteSub("script");
    setStatus(`已切换到「${library.projects[id].title}」`);
  }

  function addProjectToLibrary(p: VnProject) {
    if (!library) return;
    const normalized = normalizeProject(p);
    persist({
      activeId: normalized.id,
      projects: { ...library.projects, [normalized.id]: normalized },
    });
    setChapterId(normalized.chapters[0]?.id ?? "");
    setTab("write");
    setWriteSub("script");
  }

  function createBlank() {
    const title = window.prompt("新剧本标题", "未命名剧本");
    if (title === null) return;
    addProjectToLibrary(emptyProject(title.trim() || "未命名剧本"));
    setStatus("已创建空白剧本");
  }

  function createDemo() {
    const demo = createDemoProject();
    demo.id = uid("demo");
    addProjectToLibrary(demo);
    setStatus("已加入示例剧本");
  }

  function deleteProject(id: string) {
    if (!library) return;
    const ids = Object.keys(library.projects);
    if (ids.length <= 1) {
      setError("至少保留一个剧本");
      return;
    }
    if (!window.confirm(`确定删除「${library.projects[id]?.title}」？`)) return;
    const projects = { ...library.projects };
    delete projects[id];
    const activeId =
      library.activeId === id ? Object.keys(projects)[0] : library.activeId;
    persist({ activeId, projects });
    setChapterId(projects[activeId].chapters[0]?.id ?? "");
    setStatus("已删除剧本");
  }

  function startRename(id: string) {
    if (!library?.projects[id]) return;
    setRenamingId(id);
    setRenameDraft(library.projects[id].title);
    requestAnimationFrame(() => renameInputRef.current?.focus());
  }

  function commitRename() {
    if (!library || !renamingId) return;
    const title = renameDraft.trim() || "未命名剧本";
    const current = library.projects[renamingId];
    if (!current) {
      setRenamingId(null);
      return;
    }
    const updated = touchProject({ ...current, title });
    persist({
      ...library,
      projects: { ...library.projects, [renamingId]: updated },
    });
    setRenamingId(null);
    setStatus(`已重命名为「${title}」`);
  }

  function cancelRename() {
    setRenamingId(null);
    setRenameDraft("");
  }

  async function handleImportFile(file: File) {
    setError("");
    const name = file.name.replace(/\.[^.]+$/, "") || "导入剧本";
    try {
      const lower = file.name.toLowerCase();
      let text = "";
      if (lower.endsWith(".docx")) {
        const buf = await file.arrayBuffer();
        const result = await mammoth.extractRawText({ arrayBuffer: buf });
        text = result.value;
      } else if (
        lower.endsWith(".doc") &&
        !lower.endsWith(".docx")
      ) {
        setError("暂不支持旧版 .doc，请另存为 .docx / .txt / .rpy");
        return;
      } else if (lower.endsWith(".json")) {
        const raw = await file.text();
        const parsed = normalizeProject(JSON.parse(raw) as VnProject);
        parsed.id = uid("proj");
        addProjectToLibrary(parsed);
        setStatus(`已导入工程 JSON：${parsed.title}`);
        return;
      } else {
        text = await file.text();
      }
      if (!text.trim()) {
        setError("文件内容为空");
        return;
      }
      addProjectToLibrary(projectFromPlainText(name, text));
      setStatus(`已从「${file.name}」创建剧本`);
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
    const id = uid("ch");
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


  function extractLocs() {
    commitEditor();
    let added = 0;
    let linked = 0;
    updateActive((p) => {
      const withBlocks = {
        ...p,
        chapters: p.chapters.map((c) =>
          c.id === chapterId
            ? { ...c, blocks: editableToBlocks(editor) }
            : c
        ),
      };
      const result = extractMapFromScript(withBlocks);
      added = result.addedCount;
      linked = result.linkCount;
      return {
        ...withBlocks,
        locations: result.locations,
        locationLinks: result.locationLinks,
      };
    });
    if (added === 0 && linked === 0) {
      setStatus(
        "未发现新的 scene（需剧本中有 scene bg xxx）。已有地点不会重复添加。"
      );
    } else {
      setStatus(
        `已从剧本提取：新增 ${added} 个地点，新增 ${linked} 条通路（按 scene 顺序）`
      );
    }
    setTab("map");
  }

  function takeSnapshot() {
    if (!project) return;
    commitEditor();
    const label =
      snapLabel.trim() ||
      `快照 ${new Date().toLocaleString()}`;
    const snapshotProject = {
      ...project,
      chapters: project.chapters.map((c) =>
        c.id === chapterId
          ? { ...c, blocks: editableToBlocks(editor) }
          : c
      ),
    };
    updateActive((p) => ({
      ...p,
      snapshots: [
        {
          id: uid("snap"),
          label,
          createdAt: new Date().toISOString(),
          payload: JSON.stringify(snapshotProject),
        },
        ...(p.snapshots ?? []),
      ].slice(0, 40),
    }));
    setSnapLabel("");
    setStatus(`已保存快照「${label}」`);
  }

  function restoreSnapshot(snapId: string) {
    if (!project) return;
    const snap = (project.snapshots ?? []).find((s) => s.id === snapId);
    if (!snap) return;
    if (!window.confirm(`回退到「${snap.label}」？当前未快照的改动会丢失。`)) {
      return;
    }
    try {
      const restored = normalizeProject(JSON.parse(snap.payload) as VnProject);
      replaceActiveProject({
        ...restored,
        id: project.id,
        snapshots: project.snapshots,
        shareId: project.shareId,
      });
      const ch = restored.chapters[0];
      if (ch) {
        setChapterId(ch.id);
        setEditor(blocksToEditable(ch.blocks, restored.characters));
      }
      setStatus(`已回退到「${snap.label}」`);
    } catch {
      setError("快照损坏，无法回退");
    }
  }

  function createShareLink() {
    if (!project) return;
    commitEditor();
    const shareId = project.shareId || uid("share");
    const latest = {
      ...project,
      shareId,
      chapters: project.chapters.map((c) =>
        c.id === chapterId
          ? { ...c, blocks: editableToBlocks(editor) }
          : c
      ),
    };
    updateActive((p) => ({ ...p, shareId }));
    publishShare(latest, shareId);
    const url = `${window.location.origin}/share/${shareId}`;
    setShareUrl(url);
    void navigator.clipboard?.writeText(url);
    setStatus("已生成只读链接并复制到剪贴板（同浏览器可直接打开）");
  }

  function downloadSharePack() {
    if (!project) return;
    const shareId = project.shareId || uid("share");
    const latest = { ...project, shareId };
    updateActive((p) => ({ ...p, shareId }));
    const payload = publishShare(latest, shareId);
    downloadText(
      `${project.title || "share"}.vnss-share.json`,
      JSON.stringify(payload, null, 2),
      "application/json"
    );
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

  function downloadJson() {
    if (!project) return;
    commitEditor();
    downloadText(
      `${project.title || "project"}.json`,
      JSON.stringify(project, null, 2),
      "application/json"
    );
  }

  if (!library || !project) {
    return <div className={styles.boot}>加载中…</div>;
  }

  const projects = listProjects(library);
  const locations = project.locations ?? [];
  const links = project.locationLinks ?? [];
  const bible = project.bible ?? {};
  const apiConfig = settings
    ? {
        apiKey: settings.apiKey || undefined,
        apiBaseUrl: settings.apiBaseUrl || undefined,
        apiModel: settings.apiModel || undefined,
        craftMode: settings.craftMode || "auto",
        selfReview: settings.selfReview || "auto",
        criticApiKey: settings.criticApiKey || undefined,
        criticApiBaseUrl: settings.criticApiBaseUrl || undefined,
        criticApiModel: settings.criticApiModel || undefined,
      }
    : undefined;

  return (
    <>
      {settings?.bgImage ? <div className="vnss-wallpaper" aria-hidden /> : null}
      <div className={`vnss-app ${styles.shell}`}>
      <header className={styles.top}>
        <div className={styles.brandBlock}>
          <p className={styles.brand}>VN Script Studio</p>
          <input
            className={styles.titleInput}
            value={project.title}
            onChange={(e) =>
              updateActive((p) => ({ ...p, title: e.target.value }))
            }
            aria-label="作品标题"
          />
        </div>
        <div className={styles.topActions}>
          <button type="button" className={styles.ghost} onClick={createBlank}>
            新建
          </button>
          <button
            type="button"
            className={styles.ghost}
            onClick={() => fileRef.current?.click()}
          >
            导入文件
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
              generateRpy();
            }}
          >
            生成 / 导出 .rpy
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
        <aside className={styles.side}>
          <p className={styles.sideLabel}>当前剧本</p>
          <select
            className={styles.select}
            value={library.activeId}
            onChange={(e) => switchProject(e.target.value)}
          >
            {projects.map((p) => (
              <option key={p.id} value={p.id}>
                {p.title}
              </option>
            ))}
          </select>

          <p className={styles.sideLabel}>章节</p>
          <ul className={styles.chapterList}>
            {project.chapters.map((c) => (
              <li key={c.id} className={styles.chapterRow}>
                <button
                  type="button"
                  className={
                    c.id === chapterId ? styles.chapterActive : styles.chapterBtn
                  }
                  onClick={() => {
                    commitEditor();
                    setChapterId(c.id);
                    setTab("write");
                    setWriteSub("script");
                  }}
                >
                  {c.title}
                </button>
                <button
                  type="button"
                  className={styles.iconBtn}
                  title="删除章节"
                  onClick={() => deleteChapter(c.id)}
                >
                  ×
                </button>
              </li>
            ))}
          </ul>
          <button type="button" className={styles.ghost} onClick={addChapter}>
            + 章节
          </button>

          <p className={styles.sideLabel}>角色</p>
          <ul className={styles.charMini}>
            {project.characters.map((c) => (
              <li key={c.id}>
                <span style={{ color: c.color }}>{c.displayName}</span>
                <code>{c.defineName}</code>
              </li>
            ))}
          </ul>
        </aside>

        <main className={styles.main}>
          <nav className={styles.tabs}>
            {(
              [
                ["write", "写作"],
                ["world", "设定"],
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
                  <button type="button" onClick={createBlank}>
                    空白剧本
                  </button>
                  <button type="button" onClick={createDemo}>
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
                {projects.map((p) => (
                  <article
                    key={p.id}
                    className={
                      p.id === library.activeId
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
                        onBlur={commitRename}
                        onKeyDown={(e) => {
                          if (e.key === "Enter") {
                            e.preventDefault();
                            commitRename();
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
                    <p>{p.logline || p.bible?.background || "暂无简介"}</p>
                    <p className={styles.meta}>
                      {p.chapters.length} 章 · {p.characters.length} 角色 ·{" "}
                      {(p.locations ?? []).length} 地点
                    </p>
                    <div className={styles.cardActions}>
                      <button
                        type="button"
                        className={styles.primary}
                        onClick={() => switchProject(p.id)}
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
                        onClick={() => deleteProject(p.id)}
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
                        onClick={generateRpy}
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
                      <button type="button" onClick={downloadJson}>
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
                        onClick={takeSnapshot}
                      >
                        保存当前快照
                      </button>
                    </div>
                    <ul className={styles.snapList}>
                      {(project.snapshots ?? []).map((s) => (
                        <li key={s.id}>
                          <span>
                            {s.label}
                            <br />
                            <small>
                              {new Date(s.createdAt).toLocaleString()}
                            </small>
                          </span>
                          <button
                            type="button"
                            className={styles.ghost}
                            onClick={() => restoreSnapshot(s.id)}
                          >
                            回退到此
                          </button>
                        </li>
                      ))}
                      {(project.snapshots ?? []).length === 0 && (
                        <li>尚无快照</li>
                      )}
                    </ul>
                  </div>
                  <div className={styles.shareBox}>
                    <strong>只读分享</strong>
                    <p className={styles.hint}>
                      生成链接后，对方用同机浏览器打开即可；跨设备请下载只读包发给对方，在分享页导入。
                    </p>
                    <div className={styles.aiQuick}>
                      <button
                        type="button"
                        className={styles.primary}
                        onClick={createShareLink}
                      >
                        生成并复制链接
                      </button>
                      <button type="button" onClick={downloadSharePack}>
                        下载只读包
                      </button>
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
                  续写 / 改写 / 润色请用右下角审稿 Agent
                </span>
              </div>
              <textarea
                className={styles.editor}
                value={editor}
                onChange={(e) => {
                  setEditor(e.target.value);
                  if (rpyPreview) setRpyStale(true);
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
                    onChange={updateActive}
                    apiConfig={apiConfig}
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
                onExtractFromScript={extractLocs}
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
        prepareProject={() => ({
          ...project,
          chapters: project.chapters.map((c) =>
            c.id === chapterId
              ? { ...c, blocks: editableToBlocks(editor) }
              : c
          ),
        })}
        onProjectChange={(p) => {
          replaceActiveProject(p);
          const ch =
            p.chapters.find((c) => c.id === chapterId) ?? p.chapters[0];
          if (ch) {
            setChapterId(ch.id);
            setEditor(blocksToEditable(ch.blocks, p.characters));
          }
        }}
        onChapterFocus={(id) => {
          setChapterId(id);
          setTab("write");
          setWriteSub("script");
        }}
        apiConfig={apiConfig}
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
