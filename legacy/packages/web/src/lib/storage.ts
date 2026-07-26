import {
  createDemoProject,
  normalizeProject,
  type VnProject,
} from "@vnss/core";

const LIBRARY_KEY = "vnss-library-v2";
const LEGACY_KEY = "vnss-project-v1";

export interface ProjectLibrary {
  activeId: string;
  projects: Record<string, VnProject>;
}

export function loadLibrary(): ProjectLibrary {
  try {
    const raw = localStorage.getItem(LIBRARY_KEY);
    if (raw) {
      const parsed = JSON.parse(raw) as ProjectLibrary;
      const projects: Record<string, VnProject> = {};
      for (const [id, p] of Object.entries(parsed.projects || {})) {
        projects[id] = normalizeProject(p);
      }
      const ids = Object.keys(projects);
      if (ids.length === 0) {
        const demo = createDemoProject();
        return { activeId: demo.id, projects: { [demo.id]: demo } };
      }
      const activeId =
        parsed.activeId && projects[parsed.activeId]
          ? parsed.activeId
          : ids[0];
      return { activeId, projects };
    }
  } catch {
    /* fall through */
  }

  try {
    const legacy = localStorage.getItem(LEGACY_KEY);
    if (legacy) {
      const p = normalizeProject(JSON.parse(legacy) as VnProject);
      return { activeId: p.id, projects: { [p.id]: p } };
    }
  } catch {
    /* fall through */
  }

  const demo = createDemoProject();
  return { activeId: demo.id, projects: { [demo.id]: demo } };
}

export function saveLibrary(lib: ProjectLibrary) {
  localStorage.setItem(LIBRARY_KEY, JSON.stringify(lib));
}

export function listProjects(lib: ProjectLibrary): VnProject[] {
  return Object.values(lib.projects).sort((a, b) =>
    (b.updatedAt || "").localeCompare(a.updatedAt || "")
  );
}
